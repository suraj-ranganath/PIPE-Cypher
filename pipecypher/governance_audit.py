from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DIRECTION_ISSUES = {
    "wrong_direction",
    "undirected_relationship",
    "bidirectional_relationship",
}
SCHEMA_ISSUES = {
    "unknown_label",
    "unknown_property",
    "unknown_relationship",
    "unknown_relationship_property",
    "invalid_categorical_value",
    "missing_relationship_type",
    "unseen_relationship_pattern",
}
SAFETY_ISSUES = {"not_read_only"}
SYNTAX_ISSUES = {
    "syntax_shape",
    "unbalanced_parentheses",
    "unbalanced_brackets",
    "reserved_variable",
    "antlr_parse",
}


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_jsonl(paths: list[str | Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        jsonl_path = _resolve_jsonl_path(path)
        for line in jsonl_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _resolve_jsonl_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_dir():
        for name in ("records.jsonl", "all.jsonl"):
            nested = candidate / name
            if nested.exists():
                return nested
        raise FileNotFoundError(
            f"{candidate} is a directory but contains neither records.jsonl nor all.jsonl"
        )
    return candidate


def summarize_governance_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    issue_counts: Counter[str] = Counter()
    rejected_issue_counts: Counter[str] = Counter()
    by_graph: dict[str, Counter[str]] = defaultdict(Counter)
    by_category: dict[str, Counter[str]] = defaultdict(Counter)
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    accepted = 0

    for record in records:
        graph = str(record.get("graph_profile") or "unknown")
        category = str(record.get("category") or "unknown")
        is_accepted = bool(record.get("accepted") or record.get("gates", {}).get("accepted"))
        accepted += int(is_accepted)
        for code in _record_issue_codes(record):
            issue_counts[code] += 1
            by_graph[graph][code] += 1
            by_category[category][code] += 1
            if not is_accepted:
                rejected_issue_counts[code] += 1
            if code in DIRECTION_ISSUES and len(examples[code]) < 4:
                examples[code].append(_example(record, code))

    return {
        "records": len(records),
        "accepted_records": accepted,
        "issue_counts": dict(sorted(issue_counts.items())),
        "rejected_issue_counts": dict(sorted(rejected_issue_counts.items())),
        "issue_groups": _issue_groups(issue_counts),
        "rejected_issue_groups": _issue_groups(rejected_issue_counts),
        "by_graph": _counter_map(by_graph),
        "by_category": _counter_map(by_category),
        "direction_examples": dict(sorted(examples.items())),
    }


def summarize_downstream_governance(report: dict[str, Any]) -> dict[str, Any]:
    issue_counts: Counter[str] = Counter()
    top_level = report.get("top_predicted_issue_codes", {})
    if top_level:
        for key, value in top_level.items():
            issue_counts[str(key)] += int(value)
    else:
        for section in report.get("by_category", {}).values():
            for key, value in section.get("top_predicted_issue_codes", {}).items():
                issue_counts[str(key)] += int(value)
    return {
        "issue_counts": dict(sorted(issue_counts.items())),
        "issue_groups": _issue_groups(issue_counts),
        "total": int(report.get("total", 0)),
        "incorrect": int(report.get("incorrect", 0)),
    }


def summarize_ablation_governance(summary: dict[str, Any]) -> dict[str, Any]:
    issue_counts: Counter[str] = Counter()
    by_variant_graph: dict[str, Counter[str]] = defaultdict(Counter)
    for run in summary.get("runs", []):
        key = f"{run.get('variant', 'unknown')}::{run.get('graph', 'unknown')}"
        for issue, count in run.get("issues", {}).items():
            issue_counts[str(issue)] += int(count)
            by_variant_graph[key][str(issue)] += int(count)
    return {
        "issue_counts": dict(sorted(issue_counts.items())),
        "issue_groups": _issue_groups(issue_counts),
        "by_variant_graph": _counter_map(by_variant_graph),
        "run_count": int(summary.get("run_count", 0)),
        "target_per_category": int(summary.get("target_per_category", 0)),
    }


def merge_governance_audits(
    *,
    generation_records: dict[str, Any] | None = None,
    ablation: dict[str, Any] | None = None,
    downstream: dict[str, Any] | None = None,
) -> dict[str, Any]:
    combined = Counter()
    for source in (generation_records, ablation, downstream):
        if not source:
            continue
        for issue, count in source.get("issue_counts", {}).items():
            combined[str(issue)] += int(count)
    return {
        "generation_records": generation_records or {},
        "ablation": ablation or {},
        "downstream": downstream or {},
        "combined_issue_counts": dict(sorted(combined.items())),
        "combined_issue_groups": _issue_groups(combined),
    }


def _record_issue_codes(record: dict[str, Any]) -> list[str]:
    validation = record.get("validation")
    if not isinstance(validation, dict):
        return []
    codes = []
    for issue in validation.get("issues", []) or []:
        if isinstance(issue, dict) and issue.get("code"):
            codes.append(str(issue["code"]))
    return codes


def _issue_groups(counter: Counter[str]) -> dict[str, int]:
    return {
        "direction": sum(counter.get(code, 0) for code in DIRECTION_ISSUES),
        "schema_or_value": sum(counter.get(code, 0) for code in SCHEMA_ISSUES),
        "read_only_safety": sum(counter.get(code, 0) for code in SAFETY_ISSUES),
        "syntax_or_parser": sum(counter.get(code, 0) for code in SYNTAX_ISSUES),
    }


def _example(record: dict[str, Any], code: str) -> dict[str, Any]:
    return {
        "issue": code,
        "graph_profile": record.get("graph_profile", ""),
        "category": record.get("category", ""),
        "accepted": bool(record.get("accepted")),
        "question": record.get("question", ""),
        "cypher": record.get("cypher", ""),
    }


def _counter_map(mapping: dict[str, Counter[str]]) -> dict[str, dict[str, int]]:
    return {key: dict(sorted(counter.items())) for key, counter in sorted(mapping.items())}
