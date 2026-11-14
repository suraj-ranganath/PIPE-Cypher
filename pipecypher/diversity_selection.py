from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .diversity_metrics import (
    canonical_query_signature,
    jaccard,
    operator_combination_signature,
    structural_substructures,
    template_family_signature,
    tokenize,
)


DEFAULT_SPLIT_RATIOS = {"train": 0.8, "dev": 0.1, "test": 0.1}


@dataclass(frozen=True)
class SelectionWeights:
    query_signature: float = 0.24
    template_family: float = 0.18
    structural_substructure: float = 0.22
    schema_atom: float = 0.14
    value_atom: float = 0.08
    lexical_novelty: float = 0.10
    quality: float = 0.04
    cap_penalty: float = 0.35


def select_diverse_examples(
    examples: list[dict[str, Any]],
    *,
    target_per_group: int,
    group_keys: tuple[str, ...] = ("graph_profile", "category"),
    seed: int | str = 13,
    weights: SelectionWeights | None = None,
    max_signature_share: float = 0.20,
    max_template_family_share: float = 0.25,
) -> dict[str, Any]:
    """Select a balanced, diversity-optimized subset from quality-passing examples."""

    if target_per_group <= 0:
        raise ValueError("target_per_group must be positive")
    weights = weights or SelectionWeights()
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for example in examples:
        groups[_group_key(example, group_keys)].append(example)

    selected: list[dict[str, Any]] = []
    group_reports: dict[str, Any] = {}
    for group_key, rows in sorted(groups.items()):
        target = min(target_per_group, len(rows))
        result = _select_group(
            rows,
            target=target,
            seed=f"{seed}:{'::'.join(group_key)}",
            weights=weights,
            max_signature_share=max_signature_share,
            max_template_family_share=max_template_family_share,
        )
        selected.extend(result["examples"])
        group_reports["::".join(group_key)] = result["report"]

    selected = sorted(selected, key=lambda row: str(row.get("id", "")))
    return {
        "examples": selected,
        "report": {
            "method": "greedy_mmr_cypher_diversity",
            "target_per_group": target_per_group,
            "group_keys": list(group_keys),
            "groups": group_reports,
            "input_examples": len(examples),
            "selected_examples": len(selected),
            "seed": str(seed),
            "weights": weights.__dict__,
            "max_signature_share": max_signature_share,
            "max_template_family_share": max_template_family_share,
        },
    }


def assign_diversity_splits(
    examples: list[dict[str, Any]],
    *,
    mode: str = "signature_disjoint",
    split_ratios: dict[str, float] | None = None,
    seed: int | str = 13,
    group_keys: tuple[str, ...] = ("graph_profile", "category"),
) -> dict[str, list[dict[str, Any]]]:
    """Assign splits while optionally keeping structural blocks out of multiple splits."""

    ratios = split_ratios or DEFAULT_SPLIT_RATIOS
    if mode == "iid":
        return _assign_iid_splits(examples, ratios=ratios, seed=seed, group_keys=group_keys)
    if mode not in {"signature_disjoint", "template_family_disjoint"}:
        raise ValueError(
            "mode must be one of: iid, signature_disjoint, template_family_disjoint"
        )

    splits = {"train": [], "dev": [], "test": []}
    blocks = _split_blocks(examples, mode=mode)
    ordered_blocks = sorted(
        blocks.values(),
        key=lambda block: (
            -len(block),
            _stable_hash(f"{seed}:{_block_id(block)}"),
        ),
    )
    targets = _split_counts(len(examples), ratios)
    counts = Counter({name: 0 for name in ("train", "dev", "test")})
    for block in ordered_blocks:
        split = min(
            ("train", "dev", "test"),
            key=lambda name: (
                -(targets[name] - counts[name]),
                counts[name] + len(block) - targets[name],
                _stable_hash(f"{seed}:{name}:{_block_id(block)}"),
            ),
        )
        splits[split].extend(block)
        counts[split] += len(block)

    return {name: sorted(rows, key=lambda row: str(row.get("id", ""))) for name, rows in splits.items()}


def split_disjointness_audit(
    splits: dict[str, list[dict[str, Any]]],
    *,
    mode: str,
) -> dict[str, Any]:
    key_fn = _block_key_fn(mode)
    holders: dict[str, set[str]] = defaultdict(set)
    for split, rows in splits.items():
        for row in rows:
            holders[key_fn(row)].add(split)
    leaked = {key: sorted(value) for key, value in holders.items() if len(value) > 1}
    return {
        "mode": mode,
        "blocks": len(holders),
        "leaked_blocks": len(leaked),
        "leakage_free": not leaked,
        "examples": {key: value for key, value in list(sorted(leaked.items()))[:20]},
    }


def _select_group(
    examples: list[dict[str, Any]],
    *,
    target: int,
    seed: str,
    weights: SelectionWeights,
    max_signature_share: float,
    max_template_family_share: float,
) -> dict[str, Any]:
    remaining = sorted(
        examples,
        key=lambda row: _stable_hash(f"{seed}:{row.get('id', row.get('question', ''))}"),
    )
    selected: list[dict[str, Any]] = []
    state = _SelectionState()
    cap_events = Counter()
    while remaining and len(selected) < target:
        signature_cap = max(2, math.ceil(target * max_signature_share))
        family_cap = max(2, math.ceil(target * max_template_family_share))
        scored = [
            (
                _candidate_score(
                    row,
                    state=state,
                    weights=weights,
                    signature_cap=signature_cap,
                    family_cap=family_cap,
                ),
                row,
            )
            for row in remaining
        ]
        scored.sort(
            key=lambda item: (
                item[0]["score"],
                _stable_hash(f"{seed}:tie:{item[1].get('id', item[1].get('question', ''))}"),
            ),
            reverse=True,
        )
        best_score, best = scored[0]
        for event in best_score["cap_events"]:
            cap_events[event] += 1
        selected.append(best)
        state.add(best)
        remaining = [row for row in remaining if row is not best]

    return {
        "examples": selected,
        "report": {
            "input": len(examples),
            "target": target,
            "selected": len(selected),
            "query_signatures": len(state.query_signatures),
            "template_families": len(state.template_families),
            "structural_substructures": len(state.structural_substructures),
            "operator_combinations": len(state.operator_combinations),
            "cap_events": dict(sorted(cap_events.items())),
            "underfilled": len(selected) < target,
        },
    }


def _candidate_score(
    row: dict[str, Any],
    *,
    state: "_SelectionState",
    weights: SelectionWeights,
    signature_cap: int,
    family_cap: int,
) -> dict[str, Any]:
    signature = canonical_query_signature(str(row.get("normalized_cypher") or row.get("cypher", "")))
    family = template_family_signature(row)
    substructures = structural_substructures(row)
    schema_atoms = _schema_atoms(row)
    values = _value_atoms(row)
    tokens = set(tokenize(str(row.get("question", ""))))
    operator = operator_combination_signature(row)
    lexical_novelty = 1.0 - max((jaccard(tokens, prior) for prior in state.question_tokens), default=0.0)
    score = (
        weights.query_signature * _novelty(signature, state.query_signatures)
        + weights.template_family * _novelty(family, state.template_families)
        + weights.structural_substructure
        * _set_novelty(substructures, state.structural_substructures)
        + weights.schema_atom * _set_novelty(schema_atoms, state.schema_atoms)
        + weights.value_atom * _set_novelty(values, state.value_atoms)
        + weights.lexical_novelty * lexical_novelty
        + weights.quality * _quality_score(row)
        + 0.03 * _novelty(operator, state.operator_combinations)
    )
    cap_events: list[str] = []
    if state.query_signature_counts[signature] + 1 > signature_cap:
        score -= weights.cap_penalty
        cap_events.append("query_signature_cap")
    if state.template_family_counts[family] + 1 > family_cap:
        score -= weights.cap_penalty
        cap_events.append("template_family_cap")
    return {"score": score, "cap_events": cap_events}


class _SelectionState:
    def __init__(self) -> None:
        self.query_signatures: set[str] = set()
        self.template_families: set[str] = set()
        self.operator_combinations: set[str] = set()
        self.structural_substructures: set[str] = set()
        self.schema_atoms: set[str] = set()
        self.value_atoms: set[str] = set()
        self.question_tokens: list[set[str]] = []
        self.query_signature_counts: Counter[str] = Counter()
        self.template_family_counts: Counter[str] = Counter()

    def add(self, row: dict[str, Any]) -> None:
        signature = canonical_query_signature(str(row.get("normalized_cypher") or row.get("cypher", "")))
        family = template_family_signature(row)
        operator = operator_combination_signature(row)
        self.query_signatures.add(signature)
        self.template_families.add(family)
        self.operator_combinations.add(operator)
        self.structural_substructures.update(structural_substructures(row))
        self.schema_atoms.update(_schema_atoms(row))
        self.value_atoms.update(_value_atoms(row))
        self.question_tokens.append(set(tokenize(str(row.get("question", "")))))
        self.query_signature_counts[signature] += 1
        self.template_family_counts[family] += 1


def _schema_atoms(row: dict[str, Any]) -> set[str]:
    features = row.get("structural_features", {}) or {}
    atoms = {f"label:{value}" for value in features.get("labels", []) or []}
    atoms.update(f"rel:{value}" for value in features.get("relationship_types", []) or [])
    cypher = str(row.get("normalized_cypher") or row.get("cypher", ""))
    atoms.update(f"prop:{value}" for value in _property_names(cypher))
    return atoms


def _value_atoms(row: dict[str, Any]) -> set[str]:
    return {
        " ".join(str(value).casefold().split())
        for value in row.get("entity_values", []) or []
        if str(value).strip()
    }


def _property_names(cypher: str) -> set[str]:
    return set(re.findall(r"\.([A-Za-z_][A-Za-z0-9_]*)", cypher))


def _quality_score(row: dict[str, Any]) -> float:
    gates = row.get("gates", {}) or {}
    judge_scores = row.get("judge_scores", {}) or {}
    deterministic = sum(
        1.0
        for key in ("read_only", "syntax_valid", "schema_valid", "execution_success", "judge_pass")
        if gates.get(key, True)
    ) / 5.0
    semantic = float(judge_scores.get("semantic_alignment") or 1.0)
    schema_use = float(judge_scores.get("schema_use") or 1.0)
    return max(0.0, min(1.0, (deterministic + semantic + schema_use) / 3.0))


def _novelty(value: str, seen: set[str]) -> float:
    return 1.0 if value not in seen else 0.0


def _set_novelty(values: set[str], seen: set[str]) -> float:
    if not values:
        return 0.0
    return len(values - seen) / len(values)


def _group_key(row: dict[str, Any], keys: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(str(row.get(key, "unknown")) for key in keys)


def _assign_iid_splits(
    examples: list[dict[str, Any]],
    *,
    ratios: dict[str, float],
    seed: int | str,
    group_keys: tuple[str, ...],
) -> dict[str, list[dict[str, Any]]]:
    splits = {"train": [], "dev": [], "test": []}
    grouped_examples: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for example in examples:
        grouped_examples[_group_key(example, group_keys)].append(example)
    for group, rows in grouped_examples.items():
        ordered = sorted(
            rows,
            key=lambda row: _stable_hash(f"{seed}:{'::'.join(group)}:{row.get('id', '')}"),
        )
        counts = _split_counts(len(ordered), ratios)
        cursor = 0
        for split in ("train", "dev", "test"):
            splits[split].extend(ordered[cursor : cursor + counts[split]])
            cursor += counts[split]
    _ensure_nonempty_splits(splits, total=len(examples), seed=seed)
    return {name: sorted(rows, key=lambda row: str(row.get("id", ""))) for name, rows in splits.items()}


def _split_blocks(rows: Iterable[dict[str, Any]], *, mode: str) -> dict[str, list[dict[str, Any]]]:
    key_fn = _block_key_fn(mode)
    blocks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        blocks[key_fn(row)].append(row)
    return blocks


def _block_key_fn(mode: str):
    if mode == "signature_disjoint":
        return lambda row: canonical_query_signature(
            str(row.get("normalized_cypher") or row.get("cypher", ""))
        )
    if mode == "template_family_disjoint":
        return template_family_signature
    if mode == "iid":
        return lambda row: str(row.get("id", ""))
    raise ValueError(f"unsupported split mode: {mode}")


def _block_id(block: list[dict[str, Any]]) -> str:
    return "|".join(sorted(str(row.get("id", "")) for row in block))


def _split_counts(n: int, ratios: dict[str, float]) -> dict[str, int]:
    if n <= 0:
        return {"train": 0, "dev": 0, "test": 0}
    if n == 1:
        return {"train": 1, "dev": 0, "test": 0}
    if n == 2:
        return {"train": 1, "dev": 0, "test": 1}
    test_count = max(1, round(n * ratios.get("test", 0.1)))
    dev_count = max(1, round(n * ratios.get("dev", 0.1)))
    if test_count + dev_count >= n:
        test_count = 1
        dev_count = 1
    train_count = n - dev_count - test_count
    return {"train": train_count, "dev": dev_count, "test": test_count}


def _ensure_nonempty_splits(
    splits: dict[str, list[dict[str, Any]]],
    *,
    total: int,
    seed: int | str,
) -> None:
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
            continue
        ordered = sorted(
            splits[donor],
            key=lambda row: _stable_hash(f"{seed}:move:{split}:{row.get('id', '')}"),
        )
        splits[split].append(ordered[0])
        splits[donor] = [row for row in splits[donor] if row is not ordered[0]]


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def selection_report_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Diversity-Governed Selection",
        "",
        f"- Method: `{report.get('method')}`",
        f"- Input examples: {report.get('input_examples')}",
        f"- Selected examples: {report.get('selected_examples')}",
        f"- Target per group: {report.get('target_per_group')}",
        f"- Group keys: `{', '.join(report.get('group_keys', []))}`",
        "",
        "| Group | Input | Target | Selected | Signatures | Families | Substructures | Underfilled |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for group, row in sorted(report.get("groups", {}).items()):
        lines.append(
            "| {group} | {input} | {target} | {selected} | {signatures} | {families} | "
            "{substructures} | {underfilled} |".format(
                group=group,
                input=row.get("input", 0),
                target=row.get("target", 0),
                selected=row.get("selected", 0),
                signatures=row.get("query_signatures", 0),
                families=row.get("template_families", 0),
                substructures=row.get("structural_substructures", 0),
                underfilled="yes" if row.get("underfilled") else "no",
            )
        )
    lines.append("")
    return "\n".join(lines)


def report_sha256(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
