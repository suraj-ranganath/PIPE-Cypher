from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .io import read_jsonl

BUCKET_LABELS = {
    "accepted": "Accepted",
    "diversity_control": "Diversity/duplicate control",
    "read_only_safety": "Read-only safety",
    "syntax_invalid": "Syntax invalid",
    "schema_invalid": "Schema invalid",
    "execution_error": "Execution error",
    "empty_result": "Empty result",
    "judge_reject": "Judge semantic reject",
    "other_reject": "Other reject",
}

JUDGE_REASON_LABELS = {
    "generic_node_scan": "Generic node scan",
    "semantic_mismatch": "Semantic mismatch",
    "schema_mismatch": "Schema mismatch",
    "ambiguity": "Ambiguity",
    "empty_result": "Empty result",
    "diversity_control": "Diversity/duplicate control",
    "other": "Other",
}


def load_record_paths(paths: list[str | Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        rows.extend(read_jsonl(_records_path(path)))
    return rows


def failure_taxonomy_report(
    records: list[dict[str, Any]],
    *,
    source_paths: list[str | Path] | None = None,
    top_n: int = 12,
) -> dict[str, Any]:
    report = _summary(records, top_n=top_n)
    report["source_paths"] = [str(path) for path in source_paths or []]
    report["bucket_labels"] = BUCKET_LABELS
    report["judge_reason_labels"] = JUDGE_REASON_LABELS
    report["by_graph"] = {
        key: _summary(rows, top_n=top_n)
        for key, rows in sorted(_group_by(records, "graph_profile").items())
    }
    report["by_category"] = {
        key: _summary(rows, top_n=top_n)
        for key, rows in sorted(_group_by(records, "category").items())
    }
    return report


def classify_failure(row: dict[str, Any]) -> str:
    if row.get("accepted"):
        return "accepted"

    judge_reason = _judge_failure_reason(row)
    if _is_diversity_control(judge_reason):
        return "diversity_control"

    validation = row.get("validation", {}) or {}
    if validation.get("read_only") is False:
        return "read_only_safety"
    if validation.get("syntax_valid") is False:
        return "syntax_invalid"
    if validation.get("schema_valid") is False:
        return "schema_invalid"

    execution = row.get("execution", {}) or {}
    if execution.get("success") is False:
        return "execution_error"
    if "execution returned no rows" in judge_reason or (
        execution.get("success") is True and not execution.get("rows") and not row.get("accepted")
    ):
        return "empty_result"

    judge = row.get("judge", {}) or {}
    if judge.get("passed") is False:
        return "judge_reject"
    return "other_reject"


def judge_reason_bucket(row: dict[str, Any]) -> str:
    if row.get("accepted"):
        return ""
    reason = _judge_failure_reason(row)
    issue_codes = set(_validation_issue_codes(row))
    if _is_diversity_control(reason):
        return "diversity_control"
    if "generic_node_scan" in issue_codes or "generic node" in reason:
        return "generic_node_scan"
    if "execution returned no rows" in reason or "no rows" in reason:
        return "empty_result"
    if "ambiguous" in reason or "ambiguity" in reason:
        return "ambiguity"
    schema_terms = ("schema", "label", "relationship", "property", "direction", "cypher")
    if any(term in reason for term in schema_terms):
        return "schema_mismatch"
    semantic_terms = ("answer", "intent", "semantic", "mismatch", "fails", "wrong")
    if any(term in reason for term in semantic_terms):
        return "semantic_mismatch"
    return "other"


def _summary(records: list[dict[str, Any]], *, top_n: int) -> dict[str, Any]:
    total = len(records)
    accepted = sum(1 for row in records if row.get("accepted"))
    rejected = total - accepted
    bucket_counts = Counter(classify_failure(row) for row in records)
    validation_issue_counts = Counter(
        code for row in records for code in _validation_issue_codes(row)
    )
    judge_reason_counts = Counter(
        bucket for row in records if (bucket := judge_reason_bucket(row))
    )
    return {
        "total": total,
        "accepted": accepted,
        "rejected": rejected,
        "accept_rate": accepted / total if total else 0.0,
        "bucket_counts": _ordered_counts(bucket_counts, BUCKET_LABELS),
        "rejection_bucket_counts": {
            key: value for key, value in _ordered_counts(bucket_counts, BUCKET_LABELS).items()
            if key != "accepted"
        },
        "top_validation_issues": dict(validation_issue_counts.most_common(top_n)),
        "top_judge_reason_buckets": dict(judge_reason_counts.most_common(top_n)),
    }


def _records_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_dir():
        return candidate / "records.jsonl"
    return candidate


def _group_by(records: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        grouped[str(row.get(key) or "unknown")].append(row)
    return grouped


def _validation_issue_codes(row: dict[str, Any]) -> list[str]:
    validation = row.get("validation", {}) or {}
    return [
        str(issue.get("code") or "unknown")
        for issue in validation.get("issues", []) or []
    ]


def _judge_failure_reason(row: dict[str, Any]) -> str:
    judge = row.get("judge", {}) or {}
    return str(judge.get("failure_reason") or "").strip().lower()


def _is_diversity_control(reason: str) -> bool:
    return "duplicate accepted question" in reason or "entity diversity cap" in reason


def _ordered_counts(counts: Counter[str], label_order: dict[str, str]) -> dict[str, int]:
    ordered = {key: int(counts[key]) for key in label_order if counts.get(key)}
    for key, value in sorted(counts.items()):
        if key not in ordered:
            ordered[key] = int(value)
    return ordered
