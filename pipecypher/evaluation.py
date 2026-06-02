from __future__ import annotations

from dataclasses import dataclass
from collections import defaultdict
from typing import Any

from .cypher_client import Neo4jCypherClient
from .models import SchemaSummary
from .text_metrics import (
    DETERMINISTIC_TEXT_METRIC_KEYS,
    OPTIONAL_TEXT_METRIC_KEYS,
    compute_text_pair_metrics,
    prefix_metrics,
)
from .validator import validate_cypher


@dataclass
class AnswerSetScores:
    precision: float
    recall: float
    f1: float
    exact: bool


def _row_key(row: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    if len(row) == 1:
        return (("_scalar", str(next(iter(row.values())))),)
    return tuple(sorted((str(k), str(v)) for k, v in row.items()))


def answer_rows_to_text(rows: list[dict[str, Any]]) -> str:
    row_keys = sorted(_row_key(row) for row in rows)
    return " | ".join("; ".join(f"{key}={value}" for key, value in row) for row in row_keys)


def answer_set_scores(
    pred_rows: list[dict[str, Any]],
    gold_rows: list[dict[str, Any]],
) -> AnswerSetScores:
    pred = {_row_key(row) for row in pred_rows}
    gold = {_row_key(row) for row in gold_rows}
    if not pred and not gold:
        return AnswerSetScores(precision=1.0, recall=1.0, f1=1.0, exact=True)
    if not pred or not gold:
        return AnswerSetScores(precision=0.0, recall=0.0, f1=0.0, exact=False)
    overlap = len(pred & gold)
    precision = overlap / len(pred)
    recall = overlap / len(gold)
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return AnswerSetScores(precision=precision, recall=recall, f1=f1, exact=pred == gold)


def evaluate_prediction(
    *,
    question: str,
    gold_cypher: str,
    predicted_cypher: str,
    schema: SchemaSummary,
    client: Neo4jCypherClient,
    include_text_metrics: bool = True,
    include_optional_text_metrics: bool = False,
) -> dict[str, Any]:
    gold_validation = validate_cypher(gold_cypher, schema)
    pred_validation = validate_cypher(predicted_cypher, schema)
    gold_exec = client.run(gold_validation.normalized_cypher) if gold_validation.ok else None
    pred_exec = client.run(pred_validation.normalized_cypher) if pred_validation.ok else None
    if gold_exec and pred_exec and gold_exec.success and pred_exec.success:
        answer_scores = answer_set_scores(pred_exec.rows, gold_exec.rows)
    else:
        answer_scores = AnswerSetScores(precision=0.0, recall=0.0, f1=0.0, exact=False)
    row = {
        "gold_execution_success": bool(gold_exec and gold_exec.success),
        "question": question,
        "parse_valid": pred_validation.syntax_valid,
        "schema_valid": pred_validation.schema_valid,
        "read_only": pred_validation.read_only,
        "execution_success": bool(pred_exec and pred_exec.success),
        "execution_accuracy": answer_scores.exact,
        "answer_precision": answer_scores.precision,
        "answer_recall": answer_scores.recall,
        "answer_f1": answer_scores.f1,
        "predicted_issues": [issue.__dict__ for issue in pred_validation.issues],
    }
    if include_text_metrics:
        gold_answer_text = (
            answer_rows_to_text(gold_exec.rows) if gold_exec and gold_exec.success else ""
        )
        pred_answer_text = (
            answer_rows_to_text(pred_exec.rows) if pred_exec and pred_exec.success else ""
        )
        row.update(
            prefix_metrics(
                compute_text_pair_metrics(
                    pred_answer_text,
                    gold_answer_text,
                    include_optional=include_optional_text_metrics,
                ),
                "answer_text",
            )
        )
        row.update(
            prefix_metrics(
                compute_text_pair_metrics(
                    pred_validation.normalized_cypher,
                    gold_validation.normalized_cypher,
                    include_optional=include_optional_text_metrics,
                ),
                "query_text",
            )
        )
    return row


def summarize_evaluation_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "overall": _metric_summary(rows),
        "by_graph": _grouped_summary(rows, "graph_profile"),
        "by_category": _grouped_summary(rows, "category"),
        "by_difficulty": _grouped_summary(rows, "difficulty"),
    }


def _grouped_summary(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get(key, "unknown"))].append(row)
    return {name: _metric_summary(group_rows) for name, group_rows in sorted(groups.items())}


def _metric_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    if total == 0:
        return {
            "n": 0,
            "parse_valid": 0.0,
            "schema_valid": 0.0,
            "read_only": 0.0,
            "execution_success": 0.0,
            "execution_accuracy": 0.0,
            "answer_f1": 0.0,
        }
    summary = {
        "n": total,
        "parse_valid": _mean_bool(rows, "parse_valid"),
        "schema_valid": _mean_bool(rows, "schema_valid"),
        "read_only": _mean_bool(rows, "read_only"),
        "execution_success": _mean_bool(rows, "execution_success"),
        "execution_accuracy": _mean_bool(rows, "execution_accuracy"),
        "answer_f1": sum(float(row.get("answer_f1", 0.0)) for row in rows) / total,
    }
    for prefix in ("answer_text", "query_text"):
        for key in [*DETERMINISTIC_TEXT_METRIC_KEYS, *OPTIONAL_TEXT_METRIC_KEYS]:
            metric_key = f"{prefix}_{key}"
            mean = _mean_numeric(rows, metric_key)
            if mean is not None:
                summary[metric_key] = mean
    return summary


def _mean_bool(rows: list[dict[str, Any]], key: str) -> float:
    return sum(1 for row in rows if row.get(key)) / len(rows)


def _mean_numeric(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [row.get(key) for row in rows if isinstance(row.get(key), int | float)]
    if not values:
        return None
    return sum(float(value) for value in values) / len(values)
