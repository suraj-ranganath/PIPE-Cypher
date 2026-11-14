from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


STRATEGY_ORDER = [
    "node_scan",
    "single_hop",
    "join_heavy",
    "aggregation",
    "order_rank",
    "negation",
    "path",
    "optional",
    "bounded_result",
]

ERROR_BUCKET_ORDER = [
    "exact",
    "answer_mismatch",
    "execution_failed",
    "schema_invalid",
    "parse_invalid",
]

ERROR_BUCKET_LABELS = {
    "exact": "Exact answer",
    "answer_mismatch": "Answer mismatch",
    "execution_failed": "Execution failed",
    "schema_invalid": "Schema invalid",
    "parse_invalid": "Parse invalid",
}


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def strategy_report(
    benchmark_rows: Iterable[dict[str, Any]],
    evaluation_rows: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    benchmark = list(benchmark_rows)
    evaluation = list(evaluation_rows or [])
    categories = sorted({str(row.get("category", "unknown")) for row in benchmark})
    strategies = [strategy for strategy in STRATEGY_ORDER if _strategy_count(benchmark, strategy) > 0]

    category_counts = Counter(str(row.get("category", "unknown")) for row in benchmark)
    category_strategy_counts: dict[str, dict[str, int]] = {
        category: {strategy: 0 for strategy in strategies} for category in categories
    }
    category_strategy_rates: dict[str, dict[str, float]] = {
        category: {strategy: 0.0 for strategy in strategies} for category in categories
    }
    primary_counts: Counter[str] = Counter()
    by_primary: dict[str, dict[str, Any]] = {}
    accumulators: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for row in benchmark:
        category = str(row.get("category", "unknown"))
        features = _features(row)
        tags = _strategy_tags(features)
        for strategy in strategies:
            if strategy in tags:
                category_strategy_counts[category][strategy] += 1
        primary = str(features.get("primary_strategy") or _infer_primary(tags))
        primary_counts[primary] += 1
        accumulators[primary]["relationship_patterns"] += float(
            features.get("relationship_pattern_count", 0) or 0
        )
        accumulators[primary]["return_arity"] += float(features.get("return_arity", 0) or 0)
        accumulators[primary]["result_rows_observed"] += float(
            row.get("result_row_count_observed", 0) or 0
        )

    total = max(len(benchmark), 1)
    for category in categories:
        denominator = max(category_counts[category], 1)
        for strategy in strategies:
            category_strategy_rates[category][strategy] = (
                category_strategy_counts[category][strategy] / denominator
            )

    for strategy, count in sorted(primary_counts.items()):
        denominator = max(count, 1)
        by_primary[strategy] = {
            "examples": count,
            "share": count / total,
            "avg_relationship_patterns": accumulators[strategy]["relationship_patterns"]
            / denominator,
            "avg_return_arity": accumulators[strategy]["return_arity"] / denominator,
            "avg_result_rows_observed": accumulators[strategy]["result_rows_observed"]
            / denominator,
        }

    downstream = _downstream_by_strategy(benchmark, evaluation)
    for strategy, metrics in downstream.items():
        by_primary.setdefault(strategy, {"examples": primary_counts.get(strategy, 0), "share": 0.0})
        by_primary[strategy]["downstream"] = metrics

    return {
        "total_examples": len(benchmark),
        "categories": categories,
        "strategies": strategies,
        "category_counts": dict(sorted(category_counts.items())),
        "category_strategy_counts": category_strategy_counts,
        "category_strategy_rates": category_strategy_rates,
        "primary_strategy_counts": dict(sorted(primary_counts.items())),
        "by_primary_strategy": dict(sorted(by_primary.items())),
        "downstream_by_strategy": downstream,
        "error_bucket_labels": ERROR_BUCKET_LABELS,
    }


def render_strategy_table(report: dict[str, Any]) -> str:
    rows = [
        r"\begin{table}[H]",
        r"\centering",
        r"\small",
        r"\resizebox{\columnwidth}{!}{%",
        r"\begin{tabular}{lrrrrr}",
        r"\toprule",
        r"Primary strategy & Examples & Share & Rel. patterns & Return arity & Downstream exec. acc. \\",
        r"\midrule",
    ]
    for strategy, data in sorted(
        report.get("by_primary_strategy", {}).items(),
        key=lambda item: (-int(item[1].get("examples", 0)), item[0]),
    ):
        downstream = data.get("downstream", {})
        exec_acc = downstream.get("execution_accuracy")
        exec_acc_text = "--" if exec_acc is None else f"{float(exec_acc):.3f}"
        rows.append(
            " & ".join(
                [
                    _strategy_label(strategy),
                    str(int(data.get("examples", 0))),
                    f"{float(data.get('share', 0.0)):.3f}",
                    f"{float(data.get('avg_relationship_patterns', 0.0)):.2f}",
                    f"{float(data.get('avg_return_arity', 0.0)):.2f}",
                    exec_acc_text,
                ]
            )
            + r" \\"
        )
    rows.extend(
        [
            r"\bottomrule",
            r"\end{tabular}",
            r"}",
            (
                r"\caption{Cypher strategy diagnostics over the full "
                r"3,000-example export. Strategy tags are derived from generated Cypher "
                r"structure rather than from category labels; downstream execution accuracy "
                r"is reported on the full held-out test split when a strategy appears there.}"
            ),
            r"\label{tab:strategy_diagnostics}",
            r"\end{table}",
            "",
        ]
    )
    return "\n".join(rows)


def _downstream_by_strategy(
    benchmark: list[dict[str, Any]], evaluation: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    by_id = {str(row.get("id")): row for row in benchmark if row.get("id")}
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    totals: Counter[str] = Counter()
    success: Counter[str] = Counter()
    exact: Counter[str] = Counter()

    for row in evaluation:
        benchmark_row = by_id.get(str(row.get("id")))
        if not benchmark_row:
            continue
        strategy = str(_features(benchmark_row).get("primary_strategy") or "unknown")
        bucket = _evaluation_bucket(row)
        counts[strategy][bucket] += 1
        totals[strategy] += 1
        if bool(row.get("execution_success")):
            success[strategy] += 1
        if bool(row.get("execution_accuracy")):
            exact[strategy] += 1

    report: dict[str, dict[str, Any]] = {}
    for strategy in sorted(totals):
        denominator = max(totals[strategy], 1)
        report[strategy] = {
            "examples": totals[strategy],
            "execution_success": success[strategy] / denominator,
            "execution_accuracy": exact[strategy] / denominator,
            "error_bucket_counts": {
                bucket: counts[strategy].get(bucket, 0) for bucket in ERROR_BUCKET_ORDER
            },
        }
    return report


def _evaluation_bucket(row: dict[str, Any]) -> str:
    if bool(row.get("execution_accuracy")):
        return "exact"
    if not bool(row.get("parse_valid")):
        return "parse_invalid"
    if not bool(row.get("schema_valid")):
        return "schema_invalid"
    if not bool(row.get("execution_success")):
        return "execution_failed"
    return "answer_mismatch"


def _features(row: dict[str, Any]) -> dict[str, Any]:
    if isinstance(row.get("structural_features"), dict):
        return row["structural_features"]
    validation = row.get("validation")
    if isinstance(validation, dict) and isinstance(validation.get("structural_features"), dict):
        return validation["structural_features"]
    return {}


def _strategy_tags(features: dict[str, Any]) -> list[str]:
    tags = features.get("strategy_tags")
    if isinstance(tags, list):
        return [str(tag) for tag in tags]
    primary = features.get("primary_strategy")
    return [str(primary)] if primary else []


def _strategy_count(rows: list[dict[str, Any]], strategy: str) -> int:
    return sum(1 for row in rows if strategy in _strategy_tags(_features(row)))


def _infer_primary(tags: list[str]) -> str:
    for candidate in ["path", "negation", "order_rank", "aggregation", "join_heavy", "single_hop", "node_scan"]:
        if candidate in tags:
            return candidate
    return tags[0] if tags else "unknown"


def _strategy_label(strategy: str) -> str:
    return {
        "node_scan": "Node scan",
        "single_hop": "Single hop",
        "join_heavy": "Join-heavy",
        "aggregation": "Aggregation",
        "order_rank": "Order/rank",
        "negation": "Negation",
        "path": "Path",
        "optional": "Optional",
        "bounded_result": "Bounded result",
    }.get(strategy, strategy.replace("_", " ").title())
