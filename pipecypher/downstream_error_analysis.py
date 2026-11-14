from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .io import read_jsonl

BUCKET_LABELS = {
    "correct": "Exact answer match",
    "prediction_error": "Prediction generation error",
    "parse_invalid": "Parse invalid",
    "unsafe_or_not_read_only": "Unsafe / not read-only",
    "schema_invalid": "Schema invalid",
    "execution_failed": "Execution failed",
    "partial_answer_mismatch": "Partial answer mismatch",
    "answer_mismatch": "Answer mismatch",
    "unknown_incorrect": "Unknown incorrect",
}


def load_evaluation_rows(path: str | Path) -> list[dict[str, Any]]:
    return read_jsonl(path)


def downstream_error_report(
    rows: list[dict[str, Any]],
    *,
    source_path: str | Path | None = None,
    top_n: int = 12,
) -> dict[str, Any]:
    report = _summary(rows, top_n=top_n)
    report["source_path"] = str(source_path or "")
    report["bucket_labels"] = BUCKET_LABELS
    report["by_graph"] = {
        key: _summary(group, top_n=top_n)
        for key, group in sorted(_group_by(rows, "graph_profile").items())
    }
    report["by_category"] = {
        key: _summary(group, top_n=top_n)
        for key, group in sorted(_group_by(rows, "category").items())
    }
    report["by_difficulty"] = {
        key: _summary(group, top_n=top_n)
        for key, group in sorted(_group_by(rows, "difficulty").items())
    }
    return report


def classify_downstream_error(row: dict[str, Any]) -> str:
    if row.get("execution_accuracy"):
        return "correct"
    if row.get("prediction_error"):
        return "prediction_error"
    if row.get("parse_valid") is False:
        return "parse_invalid"
    if row.get("read_only") is False:
        return "unsafe_or_not_read_only"
    if row.get("schema_valid") is False:
        return "schema_invalid"
    if row.get("execution_success") is False:
        return "execution_failed"
    if float(row.get("answer_f1") or 0.0) > 0.0:
        return "partial_answer_mismatch"
    if row.get("execution_success") is True:
        return "answer_mismatch"
    return "unknown_incorrect"


def _summary(rows: list[dict[str, Any]], *, top_n: int) -> dict[str, Any]:
    total = len(rows)
    bucket_counts = Counter(classify_downstream_error(row) for row in rows)
    correct = bucket_counts.get("correct", 0)
    incorrect = total - correct
    issue_counts = Counter(
        str(issue.get("code") or "unknown")
        for row in rows
        for issue in row.get("predicted_issues", []) or []
    )
    bucket_counts_ordered = _ordered_counts(bucket_counts)
    return {
        "total": total,
        "correct": int(correct),
        "incorrect": int(incorrect),
        "execution_accuracy": correct / total if total else 0.0,
        "bucket_counts": bucket_counts_ordered,
        "error_bucket_counts": {
            key: value for key, value in bucket_counts_ordered.items() if key != "correct"
        },
        "bucket_shares": {
            key: value / total if total else 0.0
            for key, value in bucket_counts_ordered.items()
        },
        "error_bucket_shares": {
            key: value / incorrect if incorrect else 0.0
            for key, value in bucket_counts_ordered.items()
            if key != "correct"
        },
        "top_predicted_issue_codes": dict(issue_counts.most_common(top_n)),
    }


def _group_by(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key) or "unknown")].append(row)
    return grouped


def _ordered_counts(counts: Counter[str]) -> dict[str, int]:
    ordered = {key: int(counts[key]) for key in BUCKET_LABELS if counts.get(key)}
    for key, value in sorted(counts.items()):
        if key not in ordered:
            ordered[key] = int(value)
    return ordered
