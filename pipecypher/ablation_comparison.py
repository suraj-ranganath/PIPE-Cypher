from __future__ import annotations

import csv
import io
import json
import math
from pathlib import Path
from typing import Any


CORE_GATE_RATE_KEYS = [
    "read_only",
    "syntax_valid",
    "schema_valid",
    "execution_success",
    "judge_pass",
]


def load_ablation_suite_summary(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def compare_ablation_suites(paths: list[str | Path]) -> dict[str, Any]:
    """Compare completed ablation suite summaries across target sizes or seeds."""

    summaries = [load_ablation_suite_summary(path) for path in paths]
    suites = [_suite_inventory(path, summary) for path, summary in zip(paths, summaries)]
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    labels: dict[tuple[str, str], str] = {}
    for suite, summary in zip(suites, summaries):
        for run in summary.get("runs", []):
            key = (str(run.get("graph", "")), str(run.get("variant", "")))
            row = dict(run)
            row["_suite"] = suite
            grouped.setdefault(key, []).append(row)
            labels[key] = str(run.get("variant_label", run.get("variant", "")))

    cells = [
        _cell_summary(graph=graph, variant=variant, variant_label=labels[key], runs=runs)
        for key, runs in sorted(grouped.items())
        for graph, variant in [key]
    ]
    complete_suites = [suite for suite in suites if suite["all_runs_finished"]]
    return {
        "suite_count": len(suites),
        "complete_suite_count": len(complete_suites),
        "suites": suites,
        "cells": cells,
        "reporting_note": (
            "Use this comparison only after each contributing suite has its own "
            "collection manifest and paper-readiness audit. Partial or target-25 "
            "suites are diagnostic inputs, not paper evidence."
        ),
    }


def format_ablation_suite_comparison_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Ablation Suite Comparison",
        "",
        f"- Suites compared: {report['suite_count']}",
        f"- Complete suites: {report['complete_suite_count']}",
        f"- Reporting note: {report['reporting_note']}",
        "",
        "## Suite Inventory",
        "",
        "| Run prefix | Target/category | Seed | Complete | Model | Revision |",
        "| --- | ---: | --- | --- | --- | --- |",
    ]
    for suite in report["suites"]:
        lines.append(
            "| {prefix} | {target} | {seed} | {complete} | {model} | {revision} |".format(
                prefix=suite["run_prefix"],
                target=suite["target_per_category"],
                seed=suite["run_seed"] or "",
                complete="yes" if suite["all_runs_finished"] else "no",
                model=suite["generation_model"],
                revision=suite["code_revision"],
            )
        )

    lines.extend(
        [
            "",
            "## Cell Variation",
            "",
            "| Graph | Setting | Suites | Accepted mean | Accepted range | Acceptance mean | Acceptance SD | Exec. mean | Judge mean |",
            "| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for cell in report["cells"]:
        lines.append(
            "| {graph} | {label} | {n} | {accepted_mean:.1f} | {accepted_min}-{accepted_max} | "
            "{accept_rate_mean:.3f} | {accept_rate_stdev:.3f} | {execution_success_mean:.3f} | "
            "{judge_pass_mean:.3f} |".format(
                graph=cell["graph"],
                label=cell["variant_label"],
                n=cell["suite_count"],
                accepted_mean=cell["accepted"]["mean"],
                accepted_min=int(cell["accepted"]["min"]),
                accepted_max=int(cell["accepted"]["max"]),
                accept_rate_mean=cell["accept_rate"]["mean"],
                accept_rate_stdev=cell["accept_rate"]["stdev"],
                execution_success_mean=cell["gate_rates"]["execution_success"]["mean"],
                judge_pass_mean=cell["gate_rates"]["judge_pass"]["mean"],
            )
        )
    lines.append("")
    return "\n".join(lines)


def format_ablation_suite_comparison_csv(report: dict[str, Any]) -> str:
    fields = [
        "graph",
        "variant",
        "variant_label",
        "suite_count",
        "accepted_mean",
        "accepted_min",
        "accepted_max",
        "accepted_stdev",
        "accept_rate_mean",
        "accept_rate_min",
        "accept_rate_max",
        "accept_rate_stdev",
        "execution_success_mean",
        "judge_pass_mean",
    ]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader()
    for cell in report["cells"]:
        writer.writerow(
            {
                "graph": cell["graph"],
                "variant": cell["variant"],
                "variant_label": cell["variant_label"],
                "suite_count": cell["suite_count"],
                "accepted_mean": f"{cell['accepted']['mean']:.6f}",
                "accepted_min": f"{cell['accepted']['min']:.6f}",
                "accepted_max": f"{cell['accepted']['max']:.6f}",
                "accepted_stdev": f"{cell['accepted']['stdev']:.6f}",
                "accept_rate_mean": f"{cell['accept_rate']['mean']:.6f}",
                "accept_rate_min": f"{cell['accept_rate']['min']:.6f}",
                "accept_rate_max": f"{cell['accept_rate']['max']:.6f}",
                "accept_rate_stdev": f"{cell['accept_rate']['stdev']:.6f}",
                "execution_success_mean": f"{cell['gate_rates']['execution_success']['mean']:.6f}",
                "judge_pass_mean": f"{cell['gate_rates']['judge_pass']['mean']:.6f}",
            }
        )
    return out.getvalue()


def write_ablation_suite_comparison_json(report: dict[str, Any], path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _suite_inventory(path: str | Path, summary: dict[str, Any]) -> dict[str, Any]:
    metadata = summary.get("metadata", {})
    return {
        "path": str(path),
        "run_prefix": str(metadata.get("run_prefix", "")),
        "target_per_category": int(summary.get("target_per_category", 0)),
        "run_seed": str(metadata.get("run_seed", "")),
        "generation_model": str(metadata.get("generation_model", "")),
        "judge_model": str(metadata.get("judge_model", "")),
        "code_revision": str(metadata.get("code_revision", "")),
        "all_runs_finished": bool(summary.get("all_runs_finished")),
        "research_status": str(summary.get("research_status", "")),
    }


def _cell_summary(
    *,
    graph: str,
    variant: str,
    variant_label: str,
    runs: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "graph": graph,
        "variant": variant,
        "variant_label": variant_label,
        "suite_count": len(runs),
        "targets": sorted({int(run["_suite"]["target_per_category"]) for run in runs}),
        "run_prefixes": [str(run["_suite"]["run_prefix"]) for run in runs],
        "accepted": _summary_stats([float(run.get("accepted", 0)) for run in runs]),
        "records": _summary_stats([float(run.get("records", 0)) for run in runs]),
        "accept_rate": _summary_stats([float(run.get("accept_rate", 0.0)) for run in runs]),
        "categories_at_target": _summary_stats(
            [float(run.get("categories_at_target", 0)) for run in runs]
        ),
        "gate_rates": {
            key: _summary_stats(
                [float(run.get("gate_rates", {}).get(key, 0.0)) for run in runs]
            )
            for key in CORE_GATE_RATE_KEYS
        },
    }


def _summary_stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "min": 0.0, "max": 0.0, "stdev": 0.0}
    mean = sum(values) / len(values)
    if len(values) == 1:
        stdev = 0.0
    else:
        variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
        stdev = math.sqrt(variance)
    return {
        "mean": mean,
        "min": min(values),
        "max": max(values),
        "stdev": stdev,
    }
