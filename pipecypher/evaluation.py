from __future__ import annotations

import itertools
import re
from collections.abc import Mapping
from dataclasses import dataclass
from collections import defaultdict
from typing import Any

from .cypher_client import Neo4jCypherClient
from .cypher_parser import analyze_cypher
from .models import SchemaSummary
from .text_metrics import (
    DETERMINISTIC_TEXT_METRIC_KEYS,
    OPTIONAL_TEXT_METRIC_KEYS,
    compute_text_pair_metrics,
    prefix_metrics,
)
from .validator import CONTEXTUAL_RETURN_PROPERTIES, clean_cypher, validate_cypher

# Projection-tolerant scoring brute-forces column mappings; keep it bounded.
_MAX_PROJECTION_COLUMNS = 12
_PROPERTY_EXPR = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\s*$")


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


def policy_context_columns(
    gold_cypher: str,
    gold_columns: list[str],
    context_policy: Mapping[str, Mapping[str, tuple[str, ...]]] | None = None,
) -> list[str]:
    """Return gold result columns injected by the contextual-return policy.

    PIPE-Cypher's governance layer asks reference queries to co-return context
    (for example ``Account.accountType`` next to ``Account.accountId``). The
    natural-language question does not ask for those columns, so a prediction
    that omits them should not be scored as a wrong answer. Only columns that
    the policy itself would require are treated as context; every other gold
    column remains required.
    """

    policy = CONTEXTUAL_RETURN_PROPERTIES if context_policy is None else context_policy
    analysis = analyze_cypher(gold_cypher)
    items = list(analysis.projection_items)
    if not items or len(items) != len(gold_columns):
        return []
    props_by_var: dict[str, set[str]] = defaultdict(set)
    parsed: list[tuple[str, str] | None] = []
    for item in items:
        match = _PROPERTY_EXPR.match(item.expression)
        if match:
            props_by_var[match.group(1)].add(match.group(2))
            parsed.append((match.group(1), match.group(2)))
        else:
            parsed.append(None)
    context: list[str] = []
    for column, item_ref in zip(gold_columns, parsed):
        if item_ref is None:
            continue
        var, prop = item_ref
        label = analysis.variable_labels.get(var)
        rules = policy.get(label or "", {})
        for trigger, required in rules.items():
            if trigger != prop and trigger in props_by_var[var] and prop in required:
                context.append(column)
                break
    return context


def projected_answer_scores(
    pred_rows: list[dict[str, Any]],
    gold_rows: list[dict[str, Any]],
    *,
    required_gold_columns: list[str] | None = None,
) -> tuple[AnswerSetScores, dict[str, Any]]:
    """Projection-tolerant answer comparison.

    The prediction is correct when some injective mapping from the required gold
    columns to prediction columns yields identical projected row sets. Extra
    predicted columns are ignored (as in relaxed text-to-SQL execution metrics),
    and returned graph entities are expanded to ``column.property`` values so
    ``RETURN a`` can match a reference that returns ``a.accountId``. Column
    names never matter; values and row membership do.
    """

    strict = answer_set_scores(pred_rows, gold_rows)
    detail: dict[str, Any] = {"mapping": None, "node_expansion": False}
    if strict.exact:
        return strict, detail
    if not pred_rows or not gold_rows:
        return strict, detail
    gold_columns = list(gold_rows[0].keys())
    required = [c for c in (required_gold_columns or gold_columns) if c in gold_columns]
    if not required:
        required = gold_columns
    expanded_pred, expanded = _expand_entity_columns(pred_rows)
    pred_columns = list(expanded_pred[0].keys())
    if len(pred_columns) > _MAX_PROJECTION_COLUMNS or len(required) > len(pred_columns):
        return strict, detail
    gold_projected = {_project(row, required) for row in gold_rows}
    best = strict
    for mapping in itertools.permutations(pred_columns, len(required)):
        pred_projected = {_project(row, list(mapping)) for row in expanded_pred}
        scores = _set_scores(pred_projected, gold_projected)
        if scores.f1 > best.f1 or (scores.exact and not best.exact):
            best = scores
            detail = {
                "mapping": dict(zip(required, mapping)),
                "node_expansion": expanded and any("." in col for col in mapping),
            }
            if scores.exact:
                break
    return best, detail


def _project(row: dict[str, Any], columns: list[str]) -> tuple[str, ...]:
    return tuple(str(row.get(column)) for column in columns)


def _set_scores(pred: set[tuple[str, ...]], gold: set[tuple[str, ...]]) -> AnswerSetScores:
    if not pred or not gold:
        return AnswerSetScores(precision=0.0, recall=0.0, f1=0.0, exact=False)
    overlap = len(pred & gold)
    precision = overlap / len(pred)
    recall = overlap / len(gold)
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return AnswerSetScores(precision=precision, recall=recall, f1=f1, exact=pred == gold)


def _expand_entity_columns(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    """Expand node/map values into ``column.property`` pseudo-columns."""

    expanded_any = False
    out: list[dict[str, Any]] = []
    for row in rows:
        new_row: dict[str, Any] = {}
        for key, value in row.items():
            new_row[key] = value
            props = _entity_properties(value)
            if props:
                expanded_any = True
                for prop, prop_value in props.items():
                    new_row[f"{key}.{prop}"] = prop_value
        out.append(new_row)
    if expanded_any:
        # Ensure every row exposes the same column set so projections align.
        all_columns: list[str] = []
        for row in out:
            for key in row:
                if key not in all_columns:
                    all_columns.append(key)
        out = [{key: row.get(key) for key in all_columns} for row in out]
    return out, expanded_any


def _entity_properties(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(k): v for k, v in value.items() if not isinstance(v, (Mapping, list))}
    # neo4j.graph.Node / Relationship expose ``items()`` and ``labels``/``type``.
    if hasattr(value, "items") and (hasattr(value, "labels") or hasattr(value, "type")):
        try:
            return {str(k): v for k, v in value.items()}
        except Exception:  # pragma: no cover - defensive for driver objects
            return {}
    return {}


def evaluate_prediction(
    *,
    question: str,
    gold_cypher: str,
    predicted_cypher: str,
    schema: SchemaSummary,
    client: Neo4jCypherClient,
    include_text_metrics: bool = True,
    include_optional_text_metrics: bool = False,
    prediction_error: str | None = None,
    governed_execution_only: bool = False,
) -> dict[str, Any]:
    """Score one prediction by live execution against the reference query.

    Benchmark *construction* uses PIPE-Cypher's governance rules as hard gates.
    Downstream *scoring* must not: a model's read-only query is executed as
    written, and governance violations (undirected patterns, missing RETURN
    DISTINCT, context columns, ...) are reported as diagnostics. Set
    ``governed_execution_only`` to reproduce the legacy gated behaviour.
    """

    gold_validation = validate_cypher(gold_cypher, schema)
    pred_validation = validate_cypher(predicted_cypher, schema)
    # References are executed exactly as written (read-only), like predictions.
    # PIPE-Cypher references are already normalized, so this is a no-op for
    # them; for external references (e.g. Text2Cypher-2024) normalization would
    # add RETURN DISTINCT and change LIMITed answers.
    if governed_execution_only and gold_validation.ok:
        gold_exec = client.run(gold_validation.normalized_cypher)
    elif gold_validation.read_only and gold_cypher.strip():
        gold_exec = client.run(clean_cypher(gold_cypher))
    else:
        gold_exec = None
    prediction_failed = bool(prediction_error) and not predicted_cypher.strip()
    executable = bool(predicted_cypher.strip()) and pred_validation.read_only
    if governed_execution_only:
        executable = executable and pred_validation.ok
        pred_query = pred_validation.normalized_cypher
    else:
        pred_query = clean_cypher(predicted_cypher)
    pred_exec = client.run(pred_query) if executable else None
    gold_columns: list[str] = []
    required_columns: list[str] = []
    projection_detail: dict[str, Any] = {"mapping": None, "node_expansion": False}
    if gold_exec and pred_exec and gold_exec.success and pred_exec.success:
        answer_scores = answer_set_scores(pred_exec.rows, gold_exec.rows)
        gold_columns = list(gold_exec.rows[0].keys()) if gold_exec.rows else []
        context_columns = policy_context_columns(gold_validation.normalized_cypher, gold_columns)
        required_columns = [c for c in gold_columns if c not in context_columns]
        projected_scores, projection_detail = projected_answer_scores(
            pred_exec.rows,
            gold_exec.rows,
            required_gold_columns=required_columns,
        )
    else:
        answer_scores = AnswerSetScores(precision=0.0, recall=0.0, f1=0.0, exact=False)
        projected_scores = answer_scores
    row = {
        "gold_execution_success": bool(gold_exec and gold_exec.success),
        "gold_governance_valid": gold_validation.ok,
        "question": question,
        "prediction_failed": prediction_failed,
        "parse_valid": pred_validation.syntax_valid,
        "schema_valid": pred_validation.schema_valid,
        "read_only": pred_validation.read_only,
        "governance_valid": pred_validation.ok,
        "governance_error_codes": sorted({issue.code for issue in pred_validation.errors}),
        "execution_success": bool(pred_exec and pred_exec.success),
        "execution_error": (pred_exec.error if pred_exec and not pred_exec.success else None),
        "execution_accuracy": answer_scores.exact,
        "governed_execution_accuracy": bool(answer_scores.exact and pred_validation.ok),
        "answer_precision": answer_scores.precision,
        "answer_recall": answer_scores.recall,
        "answer_f1": answer_scores.f1,
        "projected_execution_accuracy": projected_scores.exact,
        "projected_answer_f1": projected_scores.f1,
        "gold_result_columns": gold_columns,
        "required_gold_columns": required_columns,
        "projection_mapping": projection_detail.get("mapping"),
        "projection_node_expansion": bool(projection_detail.get("node_expansion")),
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
    failed = sum(1 for row in rows if row.get("prediction_failed"))
    return {
        "run_validity": {
            "n": len(rows),
            "prediction_failures": failed,
            "prediction_failure_rate": (failed / len(rows)) if rows else 0.0,
        },
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
    for key in (
        "prediction_failed",
        "governance_valid",
        "governed_execution_accuracy",
        "projected_execution_accuracy",
    ):
        if any(key in row for row in rows):
            summary[key] = _mean_bool(rows, key)
    if any("projected_answer_f1" in row for row in rows):
        summary["projected_answer_f1"] = (
            sum(float(row.get("projected_answer_f1", 0.0)) for row in rows) / total
        )
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
