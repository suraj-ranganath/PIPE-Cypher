from __future__ import annotations

from typing import Any


def render_benchmark_export_table(stats: dict[str, Any], manifest: dict[str, Any]) -> str:
    split = stats["by_split"]
    by_graph = stats["by_graph"]
    sha = str(manifest.get("sha256", ""))[:16]
    return _table(
        body="\n".join(
            [
                r"\begin{tabular}{lrrrrrr}",
                r"\toprule",
                r"Export artifact & Examples & FinBench & SNB & Train & Dev & Test \\",
                r"\midrule",
                "Live full benchmark & {total} & {finbench} & {snb} & {train} & {dev} & {test} \\\\".format(
                    total=_fmt_int(stats["total"]),
                    finbench=_fmt_int(by_graph.get("finbench", 0)),
                    snb=_fmt_int(by_graph.get("snb", 0)),
                    train=_fmt_int(split.get("train", 0)),
                    dev=_fmt_int(split.get("dev", 0)),
                    test=_fmt_int(split.get("test", 0)),
                ),
                r"\bottomrule",
                r"\end{tabular}",
            ]
        ),
        caption=(
            "Accepted live full benchmark package with stable IDs, gate metadata, "
            f"result samples, statistics, and manifest hash \\texttt{{{sha}}}."
        ),
        label="tab:benchmark_export",
    )


def render_full_artifact_distribution_table(stats: dict[str, Any]) -> str:
    difficulty = stats["by_difficulty"]
    gates = stats["gate_counts"]
    by_graph_category = stats["by_graph_category"]
    finbench_per_category = _uniform_count(by_graph_category, prefix="finbench::")
    snb_per_category = _uniform_count(by_graph_category, prefix="snb::")
    gate_value = min(
        int(gates.get(name, 0))
        for name in ("read_only", "syntax_valid", "schema_valid", "execution_success", "judge_pass")
    )
    return _table(
        body="\n".join(
            [
                r"\begin{tabular}{lr}",
                r"\toprule",
                r"Artifact property & Value \\",
                r"\midrule",
                f"Categories & {len(stats['by_category'])} balanced categories \\\\",
                f"FinBench/category & {_fmt_int(finbench_per_category)} \\\\",
                f"SNB/category & {_fmt_int(snb_per_category)} \\\\",
                "Difficulty split & {easy} easy / {medium} medium \\\\".format(
                    easy=_fmt_int(difficulty.get("easy", 0)),
                    medium=_fmt_int(difficulty.get("medium", 0)),
                ),
                "Unique labels / rel. types & {labels} / {rels} \\\\".format(
                    labels=len(stats.get("unique_labels", [])),
                    rels=len(stats.get("unique_relationship_types", [])),
                ),
                f"Read/syntax/schema/exec/judge gates & {_fmt_int(gate_value)}/3,000 \\\\",
                r"\bottomrule",
                r"\end{tabular}",
            ]
        ),
        caption="Distribution and gate summary for the exported full benchmark artifact.",
        label="tab:full_artifact_distribution",
    )


def render_downstream_table(summary: dict[str, Any]) -> str:
    overall = summary["overall"]
    return _table(
        body="\n".join(
            [
                r"\begin{tabular}{lrrrrrr}",
                r"\toprule",
                r"Split & Examples & Parse & Schema & Exec. success & Exec. acc. & Answer F1 \\",
                r"\midrule",
                "Live full test & {n} & {parse} & {schema} & {exec_success} & {exec_acc} & {f1} \\\\".format(
                    n=_fmt_int(overall["n"]),
                    parse=_fmt_float(overall["parse_valid"]),
                    schema=_fmt_float(overall["schema_valid"]),
                    exec_success=_fmt_float(overall["execution_success"]),
                    exec_acc=_fmt_float(overall["execution_accuracy"]),
                    f1=_fmt_float(overall["answer_f1"]),
                ),
                r"\bottomrule",
                r"\end{tabular}",
            ]
        ),
        caption="Downstream Text2Cypher evaluation for local Qwen3.5-9B on the exported full benchmark test split.",
        label="tab:downstream_smoke",
    )


def render_diversity_table(report: dict[str, Any]) -> str:
    text = report["question_text"]
    templates = report["query_templates"]
    coverage = report["schema_coverage"]
    distributions = report["distributions"]
    structural = report["structural_features"]
    rows = [
        r"\begin{tabular}{lr}",
        r"\toprule",
        r"Metric & Value \\",
        r"\midrule",
        f"Question Distinct-1 & {_fmt_float(text['distinct_1'])} \\\\",
        f"Question Distinct-2 & {_fmt_float(text['distinct_2'])} \\\\",
        f"Question self-BLEU-2 (sampled) & {_fmt_float(text['self_bleu_2_sampled'])} \\\\",
        f"Unique query-signature ratio & {_fmt_float(templates['unique_signature_ratio'])} \\\\",
        f"Top query-signature share & {_fmt_float(templates['top_signature_share'])} \\\\",
        f"Category normalized entropy & {_fmt_float(distributions['category']['normalized_entropy'])} \\\\",
        f"Graph-category normalized entropy & {_fmt_float(distributions['graph_category']['normalized_entropy'])} \\\\",
        f"Difficulty normalized entropy & {_fmt_float(distributions['difficulty']['normalized_entropy'])} \\\\",
        f"Label coverage & {_fmt_float(coverage['labels']['coverage'])} \\\\",
        f"Relationship-type coverage & {_fmt_float(coverage['relationship_types']['coverage'])} \\\\",
        f"Property-name coverage & {_fmt_float(coverage['properties']['coverage'])} \\\\",
        f"Aggregation / negation / ordering rates & "
        f"{_fmt_float(structural['aggregation_rate'])} / "
        f"{_fmt_float(structural['negation_rate'])} / "
        f"{_fmt_float(structural['ordering_rate'])} \\\\",
        r"\bottomrule",
        r"\end{tabular}",
    ]
    return _table(
        body="\n".join(rows),
        caption=(
            "Diversity diagnostics for the full exported benchmark. Distinct-n follows "
            "text-generation usage; self-BLEU is lower when questions are less redundant."
        ),
        label="tab:diversity_metrics",
    )


def render_ablation_table(
    summaries: list[dict[str, Any]],
    *,
    target_per_category: int,
    category_count: int = 8,
) -> str:
    rows = [
        r"\begin{tabular}{llrrrr}",
        r"\toprule",
        r"Setting & Graph & Records & Accepted & Acceptance & Categories at target \\",
        r"\midrule",
    ]
    for summary in sorted(summaries, key=_ablation_sort_key):
        accepted_by_category = summary.get("accepted_by_category", {})
        at_target = sum(1 for value in accepted_by_category.values() if int(value) >= target_per_category)
        rows.append(
            "{name} & {graph} & {records} & {accepted} & {rate} & {at_target}/{category_count} \\\\".format(
                name=_escape_latex(_ablation_label(str(summary.get("run", "")))),
                graph=_escape_latex(_graph_label(str(summary.get("run", "")))),
                records=_fmt_int(summary.get("records", 0)),
                accepted=_fmt_int(summary.get("accepted", 0)),
                rate=_fmt_float(summary.get("accept_rate", 0.0)),
                at_target=at_target,
                category_count=category_count,
            )
        )
    rows.extend([r"\bottomrule", r"\end{tabular}"])
    return _table(
        body="\n".join(rows),
        caption=(
            "Live target-five ablation evidence with local Qwen3.5-9B. "
            f"Each graph run targets {target_per_category} accepted examples per category."
        ),
        label="tab:ablation5_results",
    )


def render_failure_taxonomy_table(report: dict[str, Any]) -> str:
    labels = report.get("bucket_labels", {})
    rejection_counts = report.get("rejection_bucket_counts", {})
    rejected = max(int(report.get("rejected", 0)), 1)
    rows = [
        r"\begin{tabular}{lrr}",
        r"\toprule",
        r"Failure bucket & Count & Share of rejected \\",
        r"\midrule",
    ]
    sorted_counts = sorted(
        rejection_counts.items(),
        key=lambda item: (-int(item[1]), item[0]),
    )
    for key, count in sorted_counts:
        if not count:
            continue
        label = labels.get(key, key.replace("_", " ").title())
        rows.append(
            "{label} & {count} & {share} \\\\".format(
                label=_escape_latex(label),
                count=_fmt_int(count),
                share=_fmt_float(count / rejected),
            )
        )
    rows.extend([r"\bottomrule", r"\end{tabular}"])
    return _table(
        body="\n".join(rows),
        caption=(
            "Failure taxonomy over full-run generation candidates before benchmark export. "
            "Accepted examples are excluded from the bucket shares."
        ),
        label="tab:failure_taxonomy",
    )


def render_judge_audit_coverage_table(snapshot: dict[str, Any]) -> str:
    coverage = snapshot["coverage"]
    graph = coverage.get("by_graph", {})
    difficulty = coverage.get("by_difficulty", {})
    rows = [
        r"\begin{tabular}{lr}",
        r"\toprule",
        r"Audit packet property & Value \\",
        r"\midrule",
        f"Rows & {_fmt_int(coverage.get('total_rows', 0))} \\\\",
        "Judge accept / reject & {accepts} / {rejects} \\\\".format(
            accepts=_fmt_int(coverage.get("judge_accepts", 0)),
            rejects=_fmt_int(coverage.get("judge_rejects", 0)),
        ),
        "FinBench / SNB rows & {finbench} / {snb} \\\\".format(
            finbench=_fmt_int(graph.get("finbench", 0)),
            snb=_fmt_int(graph.get("snb", 0)),
        ),
        "Easy / medium rows & {easy} / {medium} \\\\".format(
            easy=_fmt_int(difficulty.get("easy", 0)),
            medium=_fmt_int(difficulty.get("medium", 0)),
        ),
        "Labeled rows & {labeled} \\\\".format(
            labeled=_fmt_int(coverage.get("labeled_rows", 0)),
        ),
        r"\bottomrule",
        r"\end{tabular}",
    ]
    return _table(
        body="\n".join(rows),
        caption=(
            "Post-hoc judge calibration packet coverage. Human labels are pending "
            "and are not used as a generation gate."
        ),
        label="tab:judge_audit_coverage",
    )


def _table(*, body: str, caption: str, label: str) -> str:
    return "\n".join(
        [
            r"\begin{table}[t]",
            r"\centering",
            r"\small",
            r"\resizebox{\columnwidth}{!}{%",
            body,
            "}",
            f"\\caption{{{caption}}}",
            f"\\label{{{label}}}",
            r"\end{table}",
            "",
        ]
    )


def _uniform_count(counts: dict[str, Any], *, prefix: str) -> int:
    values = {int(value) for key, value in counts.items() if str(key).startswith(prefix)}
    if len(values) != 1:
        raise ValueError(f"expected uniform counts for prefix {prefix!r}, got {sorted(values)}")
    return next(iter(values))


def _fmt_int(value: Any) -> str:
    return f"{int(value):,}"


def _fmt_float(value: Any) -> str:
    return f"{float(value):.3f}"


def _ablation_label(run: str) -> str:
    labels = [
        ("unconstrained_local_llm_strict", "Unconstrained LLM"),
        ("unconstrained_local_llm", "Unconstrained LLM"),
        ("reverse_only", "Reverse-only"),
        ("validators_repair", "Validators+repair"),
        ("ablation_retrieval_topk_0", "No retrieval"),
        ("ablation_rewrite_false", "No rewrite"),
        ("ablation_judge_false", "No LLM judge"),
        ("full_pipe_cypher", "Full PIPE-Cypher"),
    ]
    for needle, label in labels:
        if needle in run:
            return label
    return run.replace("_", " ")


def _ablation_sort_key(summary: dict[str, Any]) -> int:
    run = str(summary.get("run", ""))
    order = [
        "unconstrained_local_llm_strict",
        "unconstrained_local_llm",
        "reverse_only",
        "validators_repair",
        "ablation_retrieval_topk_0",
        "ablation_rewrite_false",
        "ablation_judge_false",
        "full_pipe_cypher",
    ]
    for idx, needle in enumerate(order):
        if needle in run:
            return idx * 10 + _graph_sort_key(run)
    return len(order) * 10 + _graph_sort_key(run)


def _graph_label(run: str) -> str:
    if "_snb_" in run or "snb" in run.lower():
        return "SNB"
    return "FinBench"


def _graph_sort_key(run: str) -> int:
    return 1 if _graph_label(run) == "SNB" else 0


def _escape_latex(value: str) -> str:
    return (
        value.replace("\\", r"\textbackslash{}")
        .replace("&", r"\&")
        .replace("%", r"\%")
        .replace("$", r"\$")
        .replace("#", r"\#")
        .replace("_", r"\_")
        .replace("{", r"\{")
        .replace("}", r"\}")
    )
