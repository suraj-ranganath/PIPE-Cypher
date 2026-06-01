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
