from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io import read_jsonl, write_jsonl


DEFAULT_SPLITS = {"train": 0.8, "dev": 0.1, "test": 0.1}


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
        examples.append(
            {
                "id": example_id,
                "graph_profile": row.get("graph_profile"),
                "category": row.get("category"),
                "difficulty": features.get("difficulty", "unknown"),
                "question": row.get("question"),
                "cypher": row.get("cypher"),
                "normalized_cypher": validation.get("normalized_cypher"),
                "structural_features": features,
                "entity_values": row.get("entity_values", []),
                "template": row.get("template"),
                "template_metadata": row.get("template_metadata", {}),
                "reverse_cypher": row.get("reverse_cypher"),
                "result_rows_sample": result_rows[:result_sample_limit],
                "result_row_count_observed": len(result_rows),
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


def assign_splits(
    examples: list[dict[str, Any]],
    *,
    split_ratios: dict[str, float] | None = None,
    seed: str = "pipe-cypher-v1",
) -> dict[str, list[dict[str, Any]]]:
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
    }


def export_benchmark_package(
    *,
    records_paths: list[str | Path],
    output_dir: str | Path,
    accepted_only: bool = True,
    split_seed: str = "pipe-cypher-v1",
    result_sample_limit: int = 5,
) -> dict[str, Any]:
    rows = load_generation_records(records_paths)
    examples = materialize_benchmark_examples(
        rows,
        accepted_only=accepted_only,
        result_sample_limit=result_sample_limit,
    )
    splits = assign_splits(examples, seed=split_seed)
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
