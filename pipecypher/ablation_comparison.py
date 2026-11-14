from __future__ import annotations

import csv
import io
import json
import math
from pathlib import Path
from typing import Any

from pipecypher.ablation_suite import variant_label


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
    expected_cells: set[tuple[str, str]] = set()
    for suite, summary in zip(suites, summaries):
        for graph in summary.get("expected_graphs", []):
            for variant in summary.get("expected_variants", []):
                expected_cells.add((str(graph), str(variant)))
        for run in summary.get("runs", []):
            key = (str(run.get("graph", "")), str(run.get("variant", "")))
            expected_cells.add(key)
            row = dict(run)
            row["_suite"] = suite
            grouped.setdefault(key, []).append(row)
            labels[key] = str(run.get("variant_label", run.get("variant", "")))

    cells = [
        _cell_summary(
            graph=graph,
            variant=variant,
            variant_label=labels.get(key, variant_label(variant)),
            runs=grouped.get(key, []),
            suites=suites,
        )
        for key in sorted(expected_cells)
        for graph, variant in [key]
    ]
    complete_suites = [suite for suite in suites if suite["all_runs_finished"]]
    evidence_ready_suites = [suite for suite in suites if suite["evidence_ready"]]
    return {
        "suite_count": len(suites),
        "complete_suite_count": len(complete_suites),
        "evidence_ready_suite_count": len(evidence_ready_suites),
        "suites": suites,
        "cells": cells,
        "reporting_note": (
            "Use this comparison only after each contributing suite has its own "
            "collection manifest and paper-readiness audit. Target-normalized "
            "coverage is the primary scale-comparison metric; raw accepted counts "
            "are expected to grow when target_per_category grows. Partial or "
            "target-25 suites are diagnostic inputs, not paper evidence."
        ),
    }


def format_ablation_suite_comparison_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Ablation Suite Comparison",
        "",
        f"- Suites compared: {report['suite_count']}",
        f"- Complete suites: {report['complete_suite_count']}",
        f"- Evidence-ready suites: {report['evidence_ready_suite_count']}",
        f"- Reporting note: {report['reporting_note']}",
        "",
        "## Suite Inventory",
        "",
        "| Run prefix | Target/category | Target records | Seed | Complete | Evidence-ready | Model | Revision |",
        "| --- | ---: | ---: | --- | --- | --- | --- | --- |",
    ]
    for suite in report["suites"]:
        lines.append(
            "| {prefix} | {target} | {target_records} | {seed} | {complete} | {evidence} | {model} | {revision} |".format(
                prefix=suite["run_prefix"],
                target=suite["target_per_category"],
                target_records=suite["target_records"],
                seed=suite["run_seed"] or "",
                complete="yes" if suite["all_runs_finished"] else "no",
                evidence="yes" if suite["evidence_ready"] else "no",
                model=suite["generation_model"],
                revision=suite["code_revision"],
            )
        )

    lines.extend(
        [
            "",
            "## Cell Variation",
            "",
            "| Graph | Setting | Suites | Target cov. mean | Target cov. range | Acceptance mean | Acceptance SD | Cat. target mean | Exec. mean | Judge mean | Missing suites |",
            "| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for cell in report["cells"]:
        lines.append(
            "| {graph} | {label} | {n} | {target_cov_mean:.3f} | {target_cov_min:.3f}-{target_cov_max:.3f} | "
            "{accept_rate_mean:.3f} | {accept_rate_stdev:.3f} | {cat_target_mean:.3f} | "
            "{execution_success_mean:.3f} | {judge_pass_mean:.3f} | {missing} |".format(
                graph=cell["graph"],
                label=cell["variant_label"],
                n=cell["suite_count"],
                target_cov_mean=cell["target_coverage"]["mean"],
                target_cov_min=cell["target_coverage"]["min"],
                target_cov_max=cell["target_coverage"]["max"],
                accept_rate_mean=cell["accept_rate"]["mean"],
                accept_rate_stdev=cell["accept_rate"]["stdev"],
                cat_target_mean=cell["category_target_share"]["mean"],
                execution_success_mean=cell["gate_rates"]["execution_success"]["mean"],
                judge_pass_mean=cell["gate_rates"]["judge_pass"]["mean"],
                missing=", ".join(cell["missing_suite_prefixes"]) or "",
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
        "compared_suite_count",
        "missing_suite_count",
        "accepted_mean",
        "accepted_min",
        "accepted_max",
        "accepted_stdev",
        "target_coverage_mean",
        "target_coverage_min",
        "target_coverage_max",
        "target_coverage_stdev",
        "category_target_share_mean",
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
                "compared_suite_count": cell["compared_suite_count"],
                "missing_suite_count": cell["missing_suite_count"],
                "accepted_mean": f"{cell['accepted']['mean']:.6f}",
                "accepted_min": f"{cell['accepted']['min']:.6f}",
                "accepted_max": f"{cell['accepted']['max']:.6f}",
                "accepted_stdev": f"{cell['accepted']['stdev']:.6f}",
                "target_coverage_mean": f"{cell['target_coverage']['mean']:.6f}",
                "target_coverage_min": f"{cell['target_coverage']['min']:.6f}",
                "target_coverage_max": f"{cell['target_coverage']['max']:.6f}",
                "target_coverage_stdev": f"{cell['target_coverage']['stdev']:.6f}",
                "category_target_share_mean": f"{cell['category_target_share']['mean']:.6f}",
                "accept_rate_mean": f"{cell['accept_rate']['mean']:.6f}",
                "accept_rate_min": f"{cell['accept_rate']['min']:.6f}",
                "accept_rate_max": f"{cell['accept_rate']['max']:.6f}",
                "accept_rate_stdev": f"{cell['accept_rate']['stdev']:.6f}",
                "execution_success_mean": f"{cell['gate_rates']['execution_success']['mean']:.6f}",
                "judge_pass_mean": f"{cell['gate_rates']['judge_pass']['mean']:.6f}",
            }
        )
    return out.getvalue()


def format_ablation_suite_comparison_tex(report: dict[str, Any]) -> str:
    rows = [
        r"\begin{table}[H]",
        r"\centering",
        r"\small",
        r"\resizebox{\columnwidth}{!}{%",
        r"\begin{tabular}{llrrrrrr}",
        r"\toprule",
        r"Setting & Graph & Suites & Target cov. & Acceptance & Cat. target & Exec. & Judge \\",
        r"\midrule",
    ]
    for cell in report["cells"]:
        if cell["suite_count"] == 0:
            continue
        if cell["variant"] == "unconstrained_local_llm":
            continue
        rows.append(
            "{label} & {graph} & {suite_count}/{compared} & {target_cov} & {acceptance} & {cat_target} & {exec_success} & {judge} \\\\".format(
                label=_escape_latex(cell["variant_label"]),
                graph=_escape_latex(_graph_label(cell["graph"])),
                suite_count=cell["suite_count"],
                compared=cell["compared_suite_count"],
                target_cov=_fmt_mean_pm(cell["target_coverage"]),
                acceptance=_fmt_mean_pm(cell["accept_rate"]),
                cat_target=_fmt_mean_pm(cell["category_target_share"]),
                exec_success=f"{cell['gate_rates']['execution_success']['mean']:.3f}",
                judge=f"{cell['gate_rates']['judge_pass']['mean']:.3f}",
            )
        )
    rows.extend(
        [
            r"\bottomrule",
            r"\end{tabular}",
            r"}",
            (
                r"\caption{Target-size and repeated-seed ablation sensitivity. "
                r"Target coverage normalizes accepted examples by each suite's "
                r"planned graph/category target, so target-50 and target-100 suites "
                r"can be compared without treating larger raw counts as quality gains. "
                r"Unconstrained local generation is excluded from this stability table "
                r"and reported separately as the attempt-logged stress baseline in "
                r"Table~\ref{tab:ablation_results}.}"
            ),
            r"\label{tab:ablation_suite_comparison}",
            r"\end{table}",
        ]
    )
    return "\n".join(rows) + "\n"


def write_ablation_suite_comparison_json(report: dict[str, Any], path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _suite_inventory(path: str | Path, summary: dict[str, Any]) -> dict[str, Any]:
    summary_path = Path(path)
    audit = _load_optional_json(summary_path.with_name("ablation_suite_audit.json"))
    manifest = _load_optional_json(summary_path.with_name("collection_manifest.json"))
    metadata = summary.get("metadata", {})
    target = int(summary.get("target_per_category", 0))
    category_count = int(summary.get("category_count", 0))
    all_runs_finished = bool(summary.get("all_runs_finished"))
    paper_ready = bool(audit.get("paper_ready")) if audit else False
    collection_manifest_present = bool(manifest)
    return {
        "path": str(summary_path),
        "run_prefix": str(metadata.get("run_prefix", "")),
        "target_per_category": target,
        "category_count": category_count,
        "target_records": target * category_count,
        "run_seed": str(metadata.get("run_seed", "")),
        "generation_model": str(metadata.get("generation_model", "")),
        "judge_model": str(metadata.get("judge_model", "")),
        "code_revision": str(metadata.get("code_revision", "")),
        "all_runs_finished": all_runs_finished,
        "research_status": str(summary.get("research_status", "")),
        "audit_path": str(summary_path.with_name("ablation_suite_audit.json")),
        "paper_ready_audit": paper_ready,
        "collection_manifest_path": str(summary_path.with_name("collection_manifest.json")),
        "collection_manifest_present": collection_manifest_present,
        "evidence_ready": all_runs_finished and paper_ready and collection_manifest_present,
    }


def _cell_summary(
    *,
    graph: str,
    variant: str,
    variant_label: str,
    runs: list[dict[str, Any]],
    suites: list[dict[str, Any]],
) -> dict[str, Any]:
    present_prefixes = {str(run["_suite"]["run_prefix"]) for run in runs}
    missing_prefixes = [
        str(suite["run_prefix"]) for suite in suites if str(suite["run_prefix"]) not in present_prefixes
    ]
    return {
        "graph": graph,
        "variant": variant,
        "variant_label": variant_label,
        "suite_count": len(runs),
        "compared_suite_count": len(suites),
        "missing_suite_count": len(missing_prefixes),
        "missing_suite_prefixes": missing_prefixes,
        "targets": sorted({int(run["_suite"]["target_per_category"]) for run in runs}),
        "run_prefixes": [str(run["_suite"]["run_prefix"]) for run in runs],
        "accepted": _summary_stats([float(run.get("accepted", 0)) for run in runs]),
        "records": _summary_stats([float(run.get("records", 0)) for run in runs]),
        "target_coverage": _summary_stats([_target_coverage(run) for run in runs]),
        "records_per_target": _summary_stats([_records_per_target(run) for run in runs]),
        "accept_rate": _summary_stats([float(run.get("accept_rate", 0.0)) for run in runs]),
        "category_target_share": _summary_stats(
            [_category_target_share(run) for run in runs]
        ),
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


def _target_coverage(run: dict[str, Any]) -> float:
    target_records = int(run.get("_suite", {}).get("target_records", 0))
    if target_records <= 0:
        return 0.0
    return float(run.get("accepted", 0)) / target_records


def _records_per_target(run: dict[str, Any]) -> float:
    target_records = int(run.get("_suite", {}).get("target_records", 0))
    if target_records <= 0:
        return 0.0
    return float(run.get("records", 0)) / target_records


def _category_target_share(run: dict[str, Any]) -> float:
    category_count = int(run.get("_suite", {}).get("category_count", 0))
    if category_count <= 0:
        return 0.0
    return float(run.get("categories_at_target", 0)) / category_count


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


def _load_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _fmt_mean_pm(stats: dict[str, float]) -> str:
    mean = float(stats.get("mean", 0.0))
    stdev = float(stats.get("stdev", 0.0))
    if stdev == 0.0:
        return f"{mean:.3f}"
    return f"{mean:.3f}$\\pm${stdev:.3f}"


def _graph_label(graph: str) -> str:
    return {"finbench": "FinBench", "snb": "SNB"}.get(graph, graph)


def _escape_latex(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in value)
