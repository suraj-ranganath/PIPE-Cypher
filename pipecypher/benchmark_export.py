from __future__ import annotations

import hashlib
import re
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .diversity_metrics import canonical_query_signature
from .io import read_jsonl, write_jsonl


DEFAULT_SPLITS = {"train": 0.8, "dev": 0.1, "test": 0.1}
SPLIT_STRATEGIES = ("random", "signature_disjoint")


def answer_contract(cypher: str, result_rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Separate the columns a question asks for from policy-injected context.

    Downstream scoring treats ``answer_columns`` as required and forgives
    missing ``context_columns`` (added by the contextual-return governance rule,
    not requested by the question).
    """

    from .evaluation import policy_context_columns

    columns = list(result_rows[0].keys()) if result_rows else []
    context = policy_context_columns(cypher, columns) if columns else []
    return {
        "result_columns": columns,
        "answer_columns": [column for column in columns if column not in context],
        "context_columns": context,
    }


def load_generation_records(paths: list[str | Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        records_path = Path(path)
        if records_path.is_dir():
            records_path = records_path / "records.jsonl"
        source_run = records_path.parent.name
        for row in read_jsonl(records_path):
            row = dict(row)
            row["_source_run"] = source_run
            row["_source_records_path"] = str(records_path)
            rows.append(row)
    return rows


_DUPLICATED_ID_PHRASE = re.compile(r"\b([A-Za-z]*[Ii]d)\s+(?:the\s+)?[a-z]+ with id\s+")


def normalize_id_phrasing(question: str) -> str:
    """Collapse "with companyId company with id 42" to "with companyId 42".

    The id-slot filler wrote "<label> with id <value>" even when the template
    already named the id property ("... with companyId {company}"), and some
    rewrites kept both phrases. The value and meaning are unchanged; ids are
    still computed from the original record, and the export keeps the original
    wording under ``question_normalization``.
    """

    return _DUPLICATED_ID_PHRASE.sub(lambda m: m.group(1) + " ", question)


def benchmark_id(row: dict[str, Any]) -> str:
    payload = {
        "graph_profile": row.get("graph_profile", ""),
        "category": row.get("category", ""),
        "question": row.get("question", ""),
        "cypher": row.get("cypher", ""),
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return f"pc_{digest[:16]}"


def materialize_benchmark_examples(
    rows: list[dict[str, Any]],
    *,
    accepted_only: bool = True,
    result_sample_limit: int = 5,
) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_questions: set[tuple[str, str, str]] = set()
    for row in rows:
        if accepted_only and not row.get("accepted"):
            continue
        question_key = (
            str(row.get("graph_profile", "")),
            str(row.get("category", "")),
            " ".join(str(row.get("question", "")).lower().split()),
        )
        if question_key in seen_questions:
            continue
        seen_questions.add(question_key)
        example_id = benchmark_id(row)
        if example_id in seen_ids:
            continue
        seen_ids.add(example_id)

        validation = row.get("validation", {})
        execution = row.get("execution", {})
        judge = row.get("judge", {})
        features = validation.get("structural_features", {})
        result_rows = execution.get("rows", []) or []
        generation_metadata = dict(row.get("generation_metadata") or {})
        signature = generation_metadata.get("query_signature") or canonical_query_signature(
            str(row.get("cypher") or "")
        )
        examples.append(
            {
                "id": example_id,
                "graph_profile": row.get("graph_profile"),
                "category": row.get("category"),
                # v3 builds record the calibrated tier; v1/v2 keep the structural heuristic.
                "difficulty": generation_metadata.get("difficulty_tier") or features.get("difficulty", "unknown"),
                "difficulty_heuristic": features.get("difficulty", "unknown"),
                "question": normalize_id_phrasing(str(row.get("question") or "")),
                "cypher": row.get("cypher"),
                "normalized_cypher": validation.get("normalized_cypher"),
                "structural_features": features,
                "entity_values": row.get("entity_values", []),
                "template": row.get("template"),
                "template_metadata": row.get("template_metadata", {}),
                "reverse_cypher": row.get("reverse_cypher"),
                "result_rows_sample": result_rows[:result_sample_limit],
                "result_row_count_observed": len(result_rows),
                "query_signature": signature,
                "answer_contract": answer_contract(str(row.get("cypher") or ""), result_rows),
                "generation_metadata": generation_metadata,
                "question_normalization": (
                    {"rule": "duplicated_id_phrase", "before": row.get("question")}
                    if normalize_id_phrasing(str(row.get("question") or "")) != row.get("question")
                    else None
                ),
                "gates": {
                    "read_only": bool(validation.get("read_only")),
                    "syntax_valid": bool(validation.get("syntax_valid")),
                    "schema_valid": bool(validation.get("schema_valid")),
                    "execution_success": bool(execution.get("success")),
                    "judge_pass": bool(judge.get("passed")),
                    "accepted": bool(row.get("accepted")),
                },
                "judge_scores": {
                    "ambiguity": judge.get("ambiguity_score"),
                    "semantic_alignment": judge.get("semantic_alignment_score"),
                    "schema_use": judge.get("schema_use_score"),
                    "difficulty": judge.get("difficulty"),
                },
                "source": {
                    "run": row.get("_source_run"),
                    "records_path": row.get("_source_records_path"),
                    "created_at": row.get("created_at"),
                    "model": row.get("model"),
                },
            }
        )
    return sorted(examples, key=lambda item: item["id"])


def cap_examples_per_signature(
    examples: list[dict[str, Any]], max_per_signature: int, *, seed: str = "pipe-cypher-v1"
) -> tuple[list[dict[str, Any]], int]:
    """Keep at most ``max_per_signature`` items per (graph, category, signature).

    Selection is deterministic (hash of seed and id), so sharded generation runs
    whose per-shard quotas overlap still export the same global quota as a
    single-process run.
    """

    if max_per_signature <= 0:
        return examples, 0
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for example in examples:
        signature = str(example.get("query_signature") or canonical_query_signature(str(example.get("cypher") or "")))
        groups[(str(example.get("graph_profile")), str(example.get("category")), signature)].append(example)
    kept: list[dict[str, Any]] = []
    dropped = 0
    for rows in groups.values():
        ordered = sorted(rows, key=lambda item: hashlib.sha256(f"{seed}:{item['id']}".encode("utf-8")).hexdigest())
        kept.extend(ordered[:max_per_signature])
        dropped += max(0, len(ordered) - max_per_signature)
    return sorted(kept, key=lambda item: item["id"]), dropped


def cap_examples_per_cell(
    examples: list[dict[str, Any]],
    max_per_cell: int | dict[str, int],
    *,
    seed: str = "pipe-cypher-v1",
) -> tuple[list[dict[str, Any]], int]:
    """Keep at most ``max_per_cell`` items per (graph, category), round-robin
    across signatures so trimming removes repeated signatures before rare ones.
    ``max_per_cell`` may map graph_profile -> cap (key "*" = default)."""

    caps = max_per_cell if isinstance(max_per_cell, dict) else {"*": max_per_cell}
    if not any(int(v) > 0 for v in caps.values()):
        return examples, 0
    cells: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for example in examples:
        cells[(str(example.get("graph_profile")), str(example.get("category")))].append(example)
    kept: list[dict[str, Any]] = []
    dropped = 0
    for (graph, _category), rows in cells.items():
        limit = int(caps.get(graph, caps.get("*", 0)) or 0)
        if limit <= 0 or len(rows) <= limit:
            kept.extend(rows)
            continue
        by_sig: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in sorted(rows, key=lambda item: hashlib.sha256(f"{seed}:{item['id']}".encode("utf-8")).hexdigest()):
            by_sig[str(row.get("query_signature") or canonical_query_signature(str(row.get("cypher") or "")))].append(row)
        # Round-robin across signatures keeps structural diversity when trimming.
        chosen: list[dict[str, Any]] = []
        queues = [list(v) for _, v in sorted(by_sig.items())]
        while len(chosen) < limit and any(queues):
            for queue in queues:
                if queue and len(chosen) < limit:
                    chosen.append(queue.pop(0))
        kept.extend(chosen)
        dropped += len(rows) - len(chosen)
    return sorted(kept, key=lambda item: item["id"]), dropped


def assign_splits(
    examples: list[dict[str, Any]],
    *,
    split_ratios: dict[str, float] | None = None,
    seed: str = "pipe-cypher-v1",
    strategy: str = "random",
) -> dict[str, list[dict[str, Any]]]:
    if strategy not in SPLIT_STRATEGIES:
        raise ValueError(f"unknown split strategy {strategy!r}; expected one of {SPLIT_STRATEGIES}")
    if strategy == "signature_disjoint":
        return assign_signature_disjoint_splits(examples, split_ratios=split_ratios, seed=seed)
    ratios = split_ratios or DEFAULT_SPLITS
    for split in ("train", "dev", "test"):
        if split not in ratios:
            raise ValueError(f"missing split ratio: {split}")
    if any(ratios[split] < 0 for split in ("train", "dev", "test")):
        raise ValueError("split ratios must be non-negative")

    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for example in examples:
        groups[(str(example.get("graph_profile")), str(example.get("category")))].append(example)

    splits = {"train": [], "dev": [], "test": []}
    for group_examples in groups.values():
        ordered = sorted(
            group_examples,
            key=lambda item: hashlib.sha256(f"{seed}:{item['id']}".encode("utf-8")).hexdigest(),
        )
        counts = _split_counts(len(ordered), ratios)
        cursor = 0
        for split in ("train", "dev", "test"):
            count = counts[split]
            splits[split].extend(ordered[cursor : cursor + count])
            cursor += count

    _ensure_nonempty_splits(splits, total=len(examples))
    return {split: sorted(rows, key=lambda item: item["id"]) for split, rows in splits.items()}


def assign_signature_disjoint_splits(
    examples: list[dict[str, Any]],
    *,
    split_ratios: dict[str, float] | None = None,
    seed: str = "pipe-cypher-v1",
) -> dict[str, list[dict[str, Any]]]:
    """Template-held-out split: every query signature lives in exactly one split.

    Signatures are assigned whole within each graph/category cell (hash order,
    filling test, then dev, then train by example count), so test questions never
    share a Cypher structure with train demonstrations. Cells with fewer than
    three signatures cannot be split this way and stay in train; they are listed
    in ``export_stats`` under ``signature_split_cells_train_only``.
    """

    ratios = split_ratios or DEFAULT_SPLITS
    groups: dict[tuple[str, str], dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for example in examples:
        key = (str(example.get("graph_profile")), str(example.get("category")))
        signature = str(example.get("query_signature") or canonical_query_signature(str(example.get("cypher") or "")))
        groups[key][signature].append(example)

    splits: dict[str, list[dict[str, Any]]] = {"train": [], "dev": [], "test": []}
    for (graph, category), clusters in sorted(groups.items()):
        ordered = sorted(
            clusters.items(),
            key=lambda item: hashlib.sha256(f"{seed}:{graph}:{category}:{item[0]}".encode("utf-8")).hexdigest(),
        )
        total = sum(len(rows) for _, rows in ordered)
        if len(ordered) < 3:
            for _, rows in ordered:
                for row in rows:
                    row["split_note"] = "signature_cell_train_only"
                splits["train"].extend(rows)
            continue
        targets = {
            "test": max(1, round(total * ratios["test"])),
            "dev": max(1, round(total * ratios["dev"])),
        }
        filled = {"test": 0, "dev": 0}
        remaining = list(ordered)
        for split in ("test", "dev"):
            while remaining and filled[split] < targets[split] and len(remaining) > 1:
                _, rows = remaining.pop(0)
                splits[split].extend(rows)
                filled[split] += len(rows)
        for _, rows in remaining:
            splits["train"].extend(rows)
    return {split: sorted(rows, key=lambda item: item["id"]) for split, rows in splits.items()}


def split_signature_overlap(splits: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    def sig(row: dict[str, Any]) -> str:
        return str(row.get("query_signature") or canonical_query_signature(str(row.get("cypher") or "")))

    train = {sig(row) for row in splits.get("train", [])}
    out: dict[str, Any] = {"unique_signatures": {name: len({sig(r) for r in rows}) for name, rows in splits.items()}}
    for name in ("dev", "test"):
        rows = splits.get(name, [])
        out[f"{name}_rows_sharing_train_signature"] = sum(1 for row in rows if sig(row) in train)
    return out


def export_stats(
    examples: list[dict[str, Any]],
    splits: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    by_split = {split: len(rows) for split, rows in splits.items()}
    by_graph = Counter(str(row.get("graph_profile")) for row in examples)
    by_category = Counter(str(row.get("category")) for row in examples)
    by_difficulty = Counter(str(row.get("difficulty")) for row in examples)
    by_graph_category = Counter(
        f"{row.get('graph_profile')}::{row.get('category')}" for row in examples
    )

    labels: Counter[str] = Counter()
    relationships: Counter[str] = Counter()
    for row in examples:
        features = row.get("structural_features", {})
        labels.update(features.get("labels", []))
        relationships.update(features.get("relationship_types", []))

    return {
        "total": len(examples),
        "by_split": by_split,
        "by_graph": dict(sorted(by_graph.items())),
        "by_category": dict(sorted(by_category.items())),
        "by_difficulty": dict(sorted(by_difficulty.items())),
        "by_graph_category": dict(sorted(by_graph_category.items())),
        "unique_labels": sorted(labels),
        "unique_relationship_types": sorted(relationships),
        "label_counts": dict(sorted(labels.items())),
        "relationship_type_counts": dict(sorted(relationships.items())),
        "gate_counts": _gate_counts(examples),
        "unique_query_signatures": len({row.get("query_signature") for row in examples}),
        "signature_split_overlap": split_signature_overlap(splits),
        "signature_split_cells_train_only": sorted(
            {
                f"{row.get('graph_profile')}::{row.get('category')}"
                for row in splits.get("train", [])
                if row.get("split_note") == "signature_cell_train_only"
            }
        ),
    }


def export_benchmark_package(
    *,
    records_paths: list[str | Path],
    output_dir: str | Path,
    accepted_only: bool = True,
    split_seed: str = "pipe-cypher-v1",
    result_sample_limit: int = 5,
    split_strategy: str = "random",
    max_per_signature: int = 0,
    max_per_cell: int | dict[str, int] = 0,
) -> dict[str, Any]:
    rows = load_generation_records(records_paths)
    examples = materialize_benchmark_examples(
        rows,
        accepted_only=accepted_only,
        result_sample_limit=result_sample_limit,
    )
    examples, signature_cap_dropped = cap_examples_per_signature(
        examples, max_per_signature, seed=split_seed
    )
    examples, cell_cap_dropped = cap_examples_per_cell(examples, max_per_cell, seed=split_seed)
    splits = assign_splits(examples, seed=split_seed, strategy=split_strategy)
    stats = export_stats(examples, splits)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    all_path = out / "all.jsonl"
    write_jsonl(all_path, examples)
    for split, split_rows in splits.items():
        write_jsonl(out / f"{split}.jsonl", split_rows)

    stats_path = out / "stats.json"
    stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "records_paths": [str(Path(path)) for path in records_paths],
        "accepted_only": accepted_only,
        "split_seed": split_seed,
        "split_strategy": split_strategy,
        "max_per_signature": max_per_signature,
        "signature_cap_dropped": signature_cap_dropped,
        "max_per_cell": max_per_cell,
        "cell_cap_dropped": cell_cap_dropped,
        "result_sample_limit": result_sample_limit,
        "total_examples": len(examples),
        "split_counts": stats["by_split"],
        "stats_path": str(stats_path),
        "all_path": str(all_path),
        "sha256": _canonical_sha256(examples),
    }
    manifest_path = out / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"manifest": manifest, "stats": stats, "output_dir": str(out)}


def _split_counts(n: int, ratios: dict[str, float]) -> dict[str, int]:
    if n <= 0:
        return {"train": 0, "dev": 0, "test": 0}
    if n == 1:
        return {"train": 1, "dev": 0, "test": 0}
    if n == 2:
        return {"train": 1, "dev": 0, "test": 1}

    test_count = max(1, round(n * ratios["test"]))
    dev_count = max(1, round(n * ratios["dev"]))
    if test_count + dev_count >= n:
        test_count = 1
        dev_count = 1
    train_count = n - dev_count - test_count
    return {"train": train_count, "dev": dev_count, "test": test_count}


def _gate_counts(examples: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in examples:
        for key, value in row.get("gates", {}).items():
            if value:
                counts[key] += 1
    return dict(sorted(counts.items()))


def _ensure_nonempty_splits(splits: dict[str, list[dict[str, Any]]], *, total: int) -> None:
    if total < 3:
        return
    for split in ("train", "dev", "test"):
        if splits[split]:
            continue
        donor = max(
            (name for name in ("train", "dev", "test") if len(splits[name]) > 1),
            key=lambda name: len(splits[name]),
            default=None,
        )
        if donor is None:
            return
        splits[split].append(splits[donor].pop())


def _canonical_sha256(examples: list[dict[str, Any]]) -> str:
    lines = [
        json.dumps(example, ensure_ascii=False, sort_keys=True, default=str)
        for example in sorted(examples, key=lambda item: item["id"])
    ]
    return hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest()
