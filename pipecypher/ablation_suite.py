from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from pipecypher.experiments import summarize_records_path

DEFAULT_GRAPHS = ["finbench", "snb"]
DEFAULT_VARIANTS = [
    "unconstrained_local_llm",
    "reverse_only",
    "validators_repair",
    "ablation_retrieval_topk_0",
    "ablation_rewrite_false",
    "ablation_judge_false",
    "full_pipe_cypher",
]
DEFAULT_PAPER_TARGET_PER_CATEGORY = 50
DEFAULT_REQUIRED_METADATA = (
    "run_prefix",
    "generation_model",
    "judge_model",
    "code_revision",
    "log_file",
)

_VARIANT_LABELS = {
    "unconstrained_local_llm": "Unconstrained LLM",
    "reverse_only": "Reverse-only",
    "validators_repair": "Validators+repair",
    "ablation_retrieval_topk_0": "No retrieval",
    "ablation_rewrite_false": "No rewrite",
    "ablation_judge_false": "No LLM judge",
    "full_pipe_cypher": "Full PIPE-Cypher",
}


def summarize_ablation_suite(
    paths: list[str | Path],
    *,
    target_per_category: int,
    category_count: int = 8,
    expected_graphs: list[str] | None = None,
    expected_variants: list[str] | None = None,
    metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Summarize a live ablation suite without implying paper readiness."""

    graphs = expected_graphs or DEFAULT_GRAPHS
    variants = expected_variants or DEFAULT_VARIANTS
    runs = [
        _enrich_summary(
            summarize_records_path(path),
            target_per_category=target_per_category,
            category_count=category_count,
        )
        for path in paths
    ]
    runs = sorted(runs, key=_suite_sort_key)
    seen = {(run["graph"], run["variant"]) for run in runs}
    missing = [
        {"graph": graph, "variant": variant}
        for graph in graphs
        for variant in variants
        if (graph, variant) not in seen
    ]
    incomplete = [
        {"graph": run["graph"], "variant": run["variant"], "run": run["run"]}
        for run in runs
        if not run["summary_present"]
    ]
    all_runs_finished = not missing and not incomplete
    return {
        "target_per_category": target_per_category,
        "category_count": category_count,
        "expected_graphs": graphs,
        "expected_variants": variants,
        "metadata": dict(sorted((metadata or {}).items())),
        "run_count": len(runs),
        "all_runs_finished": all_runs_finished,
        "research_status": _research_status(
            target_per_category=target_per_category,
            all_runs_finished=all_runs_finished,
        ),
        "runs": runs,
        "missing": missing,
        "incomplete": incomplete,
    }


def format_ablation_suite_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Live Ablation Suite Summary",
        "",
        f"- Target per category: {report['target_per_category']}",
        f"- Expected graph workloads: {', '.join(report['expected_graphs'])}",
        f"- Expected variants: {', '.join(report['expected_variants'])}",
        f"- Runs found: {report['run_count']}",
        f"- All expected runs finished: {str(report['all_runs_finished']).lower()}",
        f"- Research reporting status: {report['research_status']}",
    ]
    if report.get("metadata"):
        lines.append("- Metadata:")
        for key, value in sorted(report["metadata"].items()):
            lines.append(f"  - {key}: `{value}`")
    lines.extend(
        [
            "",
            "| Setting | Graph | Run | Records | Accepted | Acceptance | Categories at target | Finished |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for run in report["runs"]:
        lines.append(
            "| {label} | {graph} | `{run}` | {records} | {accepted} | {rate:.3f} | "
            "{at_target}/{category_count} | {finished} |".format(
                label=run["variant_label"],
                graph=run["graph"],
                run=run["run"],
                records=run["records"],
                accepted=run["accepted"],
                rate=run["accept_rate"],
                at_target=run["categories_at_target"],
                category_count=report["category_count"],
                finished="yes" if run["summary_present"] else "no",
            )
        )

    lines.extend(
        [
            "",
            "## Gate Rates",
            "",
            "| Setting | Graph | Read-only | Syntax | Schema | Execution | Judge |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for run in report["runs"]:
        gate_rates = run.get("gate_rates", {})
        lines.append(
            "| {label} | {graph} | {read_only} | {syntax} | {schema} | {execution} | {judge} |".format(
                label=run["variant_label"],
                graph=run["graph"],
                read_only=_markdown_rate(gate_rates, "read_only"),
                syntax=_markdown_rate(gate_rates, "syntax_valid"),
                schema=_markdown_rate(gate_rates, "schema_valid"),
                execution=_markdown_rate(gate_rates, "execution_success"),
                judge=_markdown_rate(gate_rates, "judge_pass"),
            )
        )

    if report["missing"]:
        lines.extend(["", "## Missing Expected Runs", ""])
        for item in report["missing"]:
            lines.append(f"- {item['graph']} / {item['variant']}")

    if report["incomplete"]:
        lines.extend(["", "## Incomplete Runs", ""])
        for item in report["incomplete"]:
            lines.append(f"- {item['graph']} / {item['variant']}: `{item['run']}`")

    lines.extend(["", "## Reporting Rule", "", _reporting_rule(report), ""])
    return "\n".join(lines)


def format_ablation_suite_csv(report: dict[str, Any]) -> str:
    out = io.StringIO()
    fields = [
        "setting",
        "graph",
        "run",
        "records",
        "accepted",
        "accept_rate",
        "categories_at_target",
        "category_count",
        "finished",
        "read_only_rate",
        "syntax_valid_rate",
        "schema_valid_rate",
        "execution_success_rate",
        "judge_pass_rate",
    ]
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader()
    for run in report["runs"]:
        gate_rates = run.get("gate_rates", {})
        writer.writerow(
            {
                "setting": run["variant_label"],
                "graph": run["graph"],
                "run": run["run"],
                "records": run["records"],
                "accepted": run["accepted"],
                "accept_rate": f"{float(run['accept_rate']):.6f}",
                "categories_at_target": run["categories_at_target"],
                "category_count": report["category_count"],
                "finished": str(bool(run["summary_present"])).lower(),
                "read_only_rate": _csv_rate(gate_rates, "read_only"),
                "syntax_valid_rate": _csv_rate(gate_rates, "syntax_valid"),
                "schema_valid_rate": _csv_rate(gate_rates, "schema_valid"),
                "execution_success_rate": _csv_rate(gate_rates, "execution_success"),
                "judge_pass_rate": _csv_rate(gate_rates, "judge_pass"),
            }
        )
    return out.getvalue()


def write_ablation_suite_json(report: dict[str, Any], path: str | Path) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")


def write_ablation_suite_csv(report: dict[str, Any], path: str | Path) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(format_ablation_suite_csv(report), encoding="utf-8")


def audit_ablation_suite_for_paper(
    report: dict[str, Any],
    *,
    min_target_per_category: int = DEFAULT_PAPER_TARGET_PER_CATEGORY,
    required_metadata: tuple[str, ...] = DEFAULT_REQUIRED_METADATA,
) -> dict[str, Any]:
    """Check whether an ablation suite is ready for reviewer-facing reporting."""

    expected_graphs = list(report.get("expected_graphs", []))
    expected_variants = list(report.get("expected_variants", []))
    runs = list(report.get("runs", []))
    target = int(report.get("target_per_category", 0))
    category_count = int(report.get("category_count", 0))
    metadata = report.get("metadata", {})
    checks = [
        _audit_check(
            "all_expected_runs_finished",
            bool(report.get("all_runs_finished")),
            "all expected graph/variant cells finished"
            if report.get("all_runs_finished")
            else "missing or incomplete graph/variant cells remain",
        ),
        _audit_check(
            "target_is_large_enough",
            target >= min_target_per_category,
            f"target_per_category={target}; required>={min_target_per_category}",
        ),
        _audit_check(
            "no_missing_runs",
            not report.get("missing"),
            _audit_count_detail("missing", len(report.get("missing", []))),
        ),
        _audit_check(
            "no_incomplete_runs",
            not report.get("incomplete"),
            _audit_count_detail("incomplete", len(report.get("incomplete", []))),
        ),
        _audit_check(
            "expected_cell_count",
            len(runs) == len(expected_graphs) * len(expected_variants),
            f"runs={len(runs)} expected={len(expected_graphs) * len(expected_variants)}",
        ),
        _audit_check(
            "known_graphs_and_variants",
            all(run.get("graph") != "unknown" and run.get("variant") != "unknown" for run in runs),
            "all runs have inferred graph and variant labels",
        ),
    ]

    missing_metadata = [
        key
        for key in required_metadata
        if not str(metadata.get(key, "")).strip()
        or str(metadata.get(key, "")).strip().lower() == "unavailable"
    ]
    checks.append(
        _audit_check(
            "required_metadata_present",
            not missing_metadata,
            "all required metadata present"
            if not missing_metadata
            else f"missing/unavailable metadata: {', '.join(missing_metadata)}",
        )
    )

    runs_without_summary = [
        str(run.get("run", "")) for run in runs if not bool(run.get("summary_present"))
    ]
    checks.append(
        _audit_check(
            "run_summaries_present",
            not runs_without_summary,
            "summary.txt present for all run directories"
            if not runs_without_summary
            else f"runs without summary.txt: {len(runs_without_summary)}",
        )
    )

    underfilled = [
        str(run.get("run", ""))
        for run in runs
        if not _is_expected_empty_baseline(run)
        and int(run.get("categories_at_target", 0)) < category_count
    ]
    checks.append(
        _audit_check(
            "non_empty_runs_reach_category_targets",
            not underfilled,
            "all non-empty/non-unconstrained runs reach every category target"
            if not underfilled
            else f"underfilled non-empty runs: {len(underfilled)}",
        )
    )

    missing_gate_rates = [
        str(run.get("run", ""))
        for run in runs
        if int(run.get("records", 0)) > 0 and not _has_core_gate_rates(run)
    ]
    checks.append(
        _audit_check(
            "core_gate_rates_available",
            not missing_gate_rates,
            "all non-empty runs expose read/syntax/schema/execution/judge rates"
            if not missing_gate_rates
            else f"runs missing core gate rates: {len(missing_gate_rates)}",
        )
    )

    paper_ready = all(bool(check["pass"]) for check in checks)
    return {
        "paper_ready": paper_ready,
        "status": "paper_ready" if paper_ready else "not_paper_ready",
        "min_target_per_category": min_target_per_category,
        "target_per_category": target,
        "expected_cells": len(expected_graphs) * len(expected_variants),
        "run_count": len(runs),
        "empty_baseline_runs": [
            str(run.get("run", "")) for run in runs if _is_expected_empty_baseline(run)
        ],
        "failed_checks": [check for check in checks if not bool(check["pass"])],
        "checks": checks,
    }


def format_ablation_suite_audit_markdown(audit: dict[str, Any]) -> str:
    lines = [
        "# Ablation Suite Paper-Readiness Audit",
        "",
        f"- Status: `{audit['status']}`",
        f"- Paper-ready: {str(bool(audit['paper_ready'])).lower()}",
        f"- Target per category: {audit['target_per_category']}",
        f"- Minimum paper target: {audit['min_target_per_category']}",
        f"- Run cells: {audit['run_count']}/{audit['expected_cells']}",
        f"- Expected empty baseline runs: {len(audit.get('empty_baseline_runs', []))}",
        "",
        "| Check | Pass | Detail |",
        "| --- | --- | --- |",
    ]
    for check in audit["checks"]:
        lines.append(
            "| {name} | {passed} | {detail} |".format(
                name=check["name"],
                passed="yes" if check["pass"] else "no",
                detail=str(check["detail"]).replace("|", "\\|"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _enrich_summary(
    summary: dict[str, Any],
    *,
    target_per_category: int,
    category_count: int,
) -> dict[str, Any]:
    run = str(summary.get("run", ""))
    records_path = Path(str(summary.get("records_path", "")))
    accepted_by_category = summary.get("accepted_by_category", {})
    gates = summary.get("gates", {})
    records = int(summary.get("records", 0))
    enriched = dict(summary)
    enriched.update(
        {
            "graph": infer_graph(run),
            "variant": infer_variant(run),
            "variant_label": variant_label(infer_variant(run)),
            "categories_at_target": sum(
                1 for value in accepted_by_category.values() if int(value) >= target_per_category
            ),
            "category_count": category_count,
            "summary_present": (records_path.parent / "summary.txt").exists(),
            "gate_rates": {
                key: (int(value) / records if records else 0.0)
                for key, value in sorted(gates.items())
            },
        }
    )
    return enriched


def infer_graph(run: str) -> str:
    lowered = run.lower()
    if "_snb_" in lowered or lowered.endswith("_snb") or "snb" in lowered.split("_"):
        return "snb"
    if "_finbench_" in lowered or lowered.endswith("_finbench") or "finbench" in lowered.split("_"):
        return "finbench"
    return "unknown"


def infer_variant(run: str) -> str:
    lowered = run.lower()
    for variant in DEFAULT_VARIANTS:
        if variant in lowered:
            return variant
    return "unknown"


def variant_label(variant: str) -> str:
    return _VARIANT_LABELS.get(variant, variant.replace("_", " ").title())


def _suite_sort_key(run: dict[str, Any]) -> tuple[int, int, str]:
    graph_order = {graph: idx for idx, graph in enumerate(DEFAULT_GRAPHS)}
    variant_order = {variant: idx for idx, variant in enumerate(DEFAULT_VARIANTS)}
    return (
        graph_order.get(str(run.get("graph")), len(graph_order)),
        variant_order.get(str(run.get("variant")), len(variant_order)),
        str(run.get("run")),
    )


def _research_status(*, target_per_category: int, all_runs_finished: bool) -> str:
    if not all_runs_finished:
        return "incomplete; do not report as paper evidence"
    if target_per_category < 25:
        return "engineering sanity check only"
    if target_per_category == 25:
        return "interim scaled checkpoint; larger final ablations preferred"
    return "candidate paper evidence after claim/evidence audit"


def _reporting_rule(report: dict[str, Any]) -> str:
    target = int(report["target_per_category"])
    if not report["all_runs_finished"]:
        return (
            "Do not include this suite in the paper or appendix: at least one expected "
            "graph/variant run is missing or still active."
        )
    if target < 25:
        return (
            "Do not include this suite in the paper or appendix as experimental evidence. "
            "It is an engineering sanity check because the target per category is too small."
        )
    if target == 25:
        return (
            "Treat this as an interim scaled checkpoint. It can guide debugging and appendix "
            "planning, but larger target-per-category runs are preferred for final "
            "reviewer-facing ablation claims when compute permits."
        )
    return (
        "This suite is large enough to be considered for paper reporting after a "
        "claim/evidence audit verifies run logs, model IDs, graph workloads, code revision, "
        "and failure analysis."
    )


def _csv_rate(gate_rates: dict[str, Any], key: str) -> str:
    return f"{float(gate_rates.get(key, 0.0)):.6f}"


def _markdown_rate(gate_rates: dict[str, Any], key: str) -> str:
    return f"{float(gate_rates.get(key, 0.0)):.3f}"


def _audit_check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "pass": bool(passed), "detail": detail}


def _audit_count_detail(name: str, count: int) -> str:
    return f"{count} {name} run(s)"


def _is_expected_empty_baseline(run: dict[str, Any]) -> bool:
    return str(run.get("variant")) == "unconstrained_local_llm" and int(run.get("records", 0)) == 0


def _has_core_gate_rates(run: dict[str, Any]) -> bool:
    gate_rates = run.get("gate_rates", {})
    required = {
        "read_only",
        "syntax_valid",
        "schema_valid",
        "execution_success",
        "judge_pass",
    }
    return required.issubset(set(gate_rates))
