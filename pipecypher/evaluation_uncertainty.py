from __future__ import annotations

import hashlib
import math
import random
from collections import defaultdict
from typing import Any, Sequence

DEFAULT_METRICS = (
    "parse_valid",
    "schema_valid",
    "execution_success",
    "execution_accuracy",
    "answer_f1",
)
DEFAULT_GROUP_KEYS = ("graph_profile", "category", "difficulty")


def analyze_evaluation_uncertainty(
    rows: Sequence[dict[str, Any]],
    *,
    metrics: Sequence[str] = DEFAULT_METRICS,
    group_keys: Sequence[str] = DEFAULT_GROUP_KEYS,
    iterations: int = 1000,
    confidence_level: float = 0.95,
    seed: int = 13,
) -> dict[str, Any]:
    if iterations <= 0:
        raise ValueError("iterations must be positive")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence_level must be between 0 and 1")

    row_list = list(rows)
    report: dict[str, Any] = {
        "method": "nonparametric_bootstrap",
        "iterations": iterations,
        "confidence_level": confidence_level,
        "seed": seed,
        "metrics": list(metrics),
        "overall": {
            metric: bootstrap_metric_interval(
                row_list,
                metric,
                iterations=iterations,
                confidence_level=confidence_level,
                seed=_derived_seed(seed, "overall", metric),
            )
            for metric in metrics
        },
        "groups": {},
    }
    for group_key in group_keys:
        grouped = _group_rows(row_list, group_key)
        report["groups"][group_key] = {
            group_name: {
                metric: bootstrap_metric_interval(
                    group_rows,
                    metric,
                    iterations=iterations,
                    confidence_level=confidence_level,
                    seed=_derived_seed(seed, group_key, group_name, metric),
                )
                for metric in metrics
            }
            for group_name, group_rows in sorted(grouped.items())
        }
    return report


def bootstrap_metric_interval(
    rows: Sequence[dict[str, Any]],
    metric: str,
    *,
    iterations: int = 1000,
    confidence_level: float = 0.95,
    seed: int = 13,
) -> dict[str, Any]:
    if iterations <= 0:
        raise ValueError("iterations must be positive")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence_level must be between 0 and 1")
    values = [_metric_value(row, metric) for row in rows]
    n = len(values)
    if n == 0:
        return {
            "n": 0,
            "point": 0.0,
            "lower": 0.0,
            "upper": 0.0,
            "standard_error": 0.0,
        }

    point = sum(values) / n
    rng = random.Random(seed)
    estimates: list[float] = []
    for _ in range(iterations):
        total = 0.0
        for _ in range(n):
            total += values[rng.randrange(n)]
        estimates.append(total / n)
    estimates.sort()
    alpha = 1.0 - confidence_level
    lower = _quantile(estimates, alpha / 2.0)
    upper = _quantile(estimates, 1.0 - alpha / 2.0)
    return {
        "n": n,
        "point": point,
        "lower": lower,
        "upper": upper,
        "standard_error": _standard_deviation(estimates),
    }


def format_evaluation_uncertainty_markdown(report: dict[str, Any]) -> str:
    confidence = int(round(float(report["confidence_level"]) * 100))
    lines = [
        "# Downstream Evaluation Uncertainty",
        "",
        (
            f"Method: nonparametric bootstrap with {report['iterations']:,} "
            f"resamples and {confidence}% percentile intervals."
        ),
        "",
        "| Metric | N | Point | CI lower | CI upper | SE |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for metric, interval in report["overall"].items():
        lines.append(
            "| {metric} | {n} | {point:.3f} | {lower:.3f} | {upper:.3f} | {se:.3f} |".format(
                metric=metric,
                n=int(interval["n"]),
                point=float(interval["point"]),
                lower=float(interval["lower"]),
                upper=float(interval["upper"]),
                se=float(interval["standard_error"]),
            )
        )
    lines.append("")
    lines.append("## Grouped Intervals")
    for group_key, groups in report.get("groups", {}).items():
        lines.extend(["", f"### {group_key}", ""])
        lines.append("| Group | Metric | N | Point | CI lower | CI upper |")
        lines.append("| --- | --- | ---: | ---: | ---: | ---: |")
        for group_name, metrics in groups.items():
            for metric, interval in metrics.items():
                lines.append(
                    "| {group} | {metric} | {n} | {point:.3f} | {lower:.3f} | {upper:.3f} |".format(
                        group=group_name,
                        metric=metric,
                        n=int(interval["n"]),
                        point=float(interval["point"]),
                        lower=float(interval["lower"]),
                        upper=float(interval["upper"]),
                    )
                )
    return "\n".join(lines) + "\n"


def render_downstream_uncertainty_table(report: dict[str, Any]) -> str:
    confidence = int(round(float(report.get("confidence_level", 0.95)) * 100))
    rows = [
        r"\begin{tabular}{lrrrr}",
        r"\toprule",
        f"Metric & Point & {confidence}\\% CI & SE & N \\\\",
        r"\midrule",
    ]
    for metric in DEFAULT_METRICS:
        if metric not in report["overall"]:
            continue
        interval = report["overall"][metric]
        rows.append(
            "{metric} & {point:.3f} & [{lower:.3f}, {upper:.3f}] & {se:.3f} & {n} \\\\".format(
                metric=_metric_label(metric),
                point=float(interval["point"]),
                lower=float(interval["lower"]),
                upper=float(interval["upper"]),
                se=float(interval["standard_error"]),
                n=f"{int(interval['n']):,}",
            )
        )
    rows.extend([r"\bottomrule", r"\end{tabular}"])
    return "\n".join(
        [
            r"\begin{table}[t]",
            r"\centering",
            r"\small",
            r"\resizebox{\columnwidth}{!}{%",
            "\n".join(rows),
            "}",
            (
                "\\caption{Bootstrap uncertainty for downstream Text2Cypher evaluation "
                "on the full exported test split. Intervals use row-level resampling "
                "with a fixed seed and are intended for appendix reporting.}"
            ),
            r"\label{tab:downstream_uncertainty}",
            r"\end{table}",
            "",
        ]
    )


def _group_rows(rows: Sequence[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key, "unknown"))].append(row)
    return dict(grouped)


def _metric_value(row: dict[str, Any], metric: str) -> float:
    value = row.get(metric, 0.0)
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    return float(value or 0.0)


def _quantile(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    if q <= 0:
        return float(values[0])
    if q >= 1:
        return float(values[-1])
    position = q * (len(values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(values[lower])
    fraction = position - lower
    return float(values[lower] * (1.0 - fraction) + values[upper] * fraction)


def _standard_deviation(values: Sequence[float]) -> float:
    if len(values) <= 1:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def _derived_seed(seed: int, *parts: str) -> int:
    digest = hashlib.sha256("|".join([str(seed), *parts]).encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


def _metric_label(metric: str) -> str:
    labels = {
        "parse_valid": "Parse valid",
        "schema_valid": "Schema valid",
        "execution_success": "Execution success",
        "execution_accuracy": "Execution accuracy",
        "answer_f1": "Answer F1",
    }
    return labels.get(metric, metric.replace("_", " ").title())
