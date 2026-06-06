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
                "Used labels / rel. types & {labels} / {rels} \\\\".format(
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
        label="tab:downstream_evaluation",
    )


def render_downstream_error_table(report: dict[str, Any]) -> str:
    labels = report.get("bucket_labels", {})
    incorrect = max(int(report.get("incorrect", 0)), 1)
    rows = [
        r"\begin{tabular}{lrr}",
        r"\toprule",
        r"Downstream outcome & Count & Share of incorrect \\",
        r"\midrule",
    ]
    error_counts = sorted(
        report.get("error_bucket_counts", {}).items(),
        key=lambda item: (-int(item[1]), item[0]),
    )
    for key, count in error_counts:
        if not count:
            continue
        rows.append(
            "{label} & {count} & {share} \\\\".format(
                label=_escape_latex(labels.get(key, key.replace("_", " ").title())),
                count=_fmt_int(count),
                share=_fmt_float(int(count) / incorrect),
            )
        )
    rows.extend([r"\bottomrule", r"\end{tabular}"])
    return _table(
        body="\n".join(rows),
        caption=(
            "Downstream Text2Cypher failure taxonomy for local Qwen3.5-9B on the "
            "full exported test split. Shares exclude exact-answer matches."
        ),
        label="tab:downstream_error_taxonomy",
    )


def render_diversity_table(report: dict[str, Any]) -> str:
    text = report["question_text"]
    templates = report["query_templates"]
    families = report.get("template_families", {})
    coverage = report["schema_coverage"]
    distributions = report["distributions"]
    structural = report["structural_features"]
    substructures = report.get("structural_substructures", {})
    values = report["value_grounding"]
    pipe_index = report.get("pipe_diversity_index", {})
    pairwise = text.get("pairwise_jaccard_sampled", {})
    rows = [
        r"\begin{tabular}{lr}",
        r"\toprule",
        r"Metric & Value \\",
        r"\midrule",
        f"PIPE-Diversity index & {_fmt_float(pipe_index.get('score', 0.0))} \\\\",
        f"Question Distinct-1 & {_fmt_float(text['distinct_1'])} \\\\",
        f"Question Distinct-2 & {_fmt_float(text['distinct_2'])} \\\\",
        f"Question adjusted Distinct-2 & {_fmt_float(text.get('ead_distinct_2', 0.0))} \\\\",
        f"Question self-BLEU-2 (sampled) & {_fmt_float(text['self_bleu_2_sampled'])} \\\\",
        f"Mean nearest-neighbor question Jaccard & "
        f"{_fmt_float(pairwise.get('mean_nearest_neighbor_jaccard', 0.0))} \\\\",
        f"Unique query-signature ratio & {_fmt_float(templates['unique_signature_ratio'])} \\\\",
        f"Top query-signature share & {_fmt_float(templates['top_signature_share'])} \\\\",
        f"Template-family entropy & "
        f"{_fmt_float(families.get('distribution', {}).get('normalized_entropy', 0.0))} \\\\",
        f"Operator-combination entropy & "
        f"{_fmt_float(distributions.get('operator_combinations', {}).get('normalized_entropy', 0.0))} \\\\",
        f"Unique structural substructures & "
        f"{_fmt_int(substructures.get('unique_substructure_count', 0))} \\\\",
        f"Category normalized entropy & {_fmt_float(distributions['category']['normalized_entropy'])} \\\\",
        f"Graph-category normalized entropy & {_fmt_float(distributions['graph_category']['normalized_entropy'])} \\\\",
        f"Difficulty normalized entropy & {_fmt_float(distributions['difficulty']['normalized_entropy'])} \\\\",
        f"Label coverage & {_fmt_float(coverage['labels']['coverage'])} \\\\",
        f"Relationship-type coverage & {_fmt_float(coverage['relationship_types']['coverage'])} \\\\",
        f"Property-name coverage & {_fmt_float(coverage['properties']['coverage'])} \\\\",
        f"Unique grounded-value ratio & "
        f"{_fmt_float(values['unique_entity_value_ratio'])} \\\\",
        f"Grounded values exactly quoted & "
        f"{_fmt_float(values['entity_values_exact_quoted_rate'])} \\\\",
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
            "Diversity diagnostics for the full exported benchmark. PIPE-Diversity is "
            "a geometric mean of lexical, query-template, structural, schema, value, "
            "and balance components; component rows are shown so the composite score "
            "does not hide residual concentration."
        ),
        label="tab:diversity_metrics",
    )


def render_query_signature_concentration_table(report: dict[str, Any]) -> str:
    rows = [
        r"\begin{tabular}{lrrp{0.56\columnwidth}}",
        r"\toprule",
        r"Signature ID & Count & Share & Canonical preview \\",
        r"\midrule",
    ]
    for item in report.get("query_templates", {}).get("top_signatures", []):
        rows.append(
            "{signature_id} & {count} & {share} & {preview} \\\\".format(
                signature_id=_escape_latex(str(item.get("signature_id", ""))),
                count=_fmt_int(item.get("count", 0)),
                share=_fmt_float(item.get("share", 0.0)),
                preview=_escape_latex(str(item.get("preview", ""))),
            )
        )
    rows.extend([r"\bottomrule", r"\end{tabular}"])
    return _table(
        body="\n".join(rows),
        caption=(
            "Top canonical query signatures in the full export. Literals, numbers, "
            "and variables are normalized before counting, so this table measures "
            "template concentration rather than raw value reuse."
        ),
        label="tab:query_signature_concentration",
    )


def render_diversity_improvement_table(comparison: dict[str, Any]) -> str:
    labels = {
        "pipe_diversity_index": "PIPE-Diversity index",
        "query_signature_ratio": "Unique query-signature ratio",
        "top_signature_share": "Top signature share (lower better)",
        "template_family_entropy": "Template-family entropy",
        "operator_combo_entropy": "Operator-combination entropy",
        "structural_substructures": "Unique structural substructures",
        "self_bleu_2": "Question self-BLEU-2 (lower better)",
        "ead_distinct_2": "Adjusted Distinct-2",
        "schema_property_coverage": "Property coverage",
    }
    rows = [
        r"\begin{tabular}{lrrr}",
        r"\toprule",
        r"Metric & Random balanced & Diversity governed & $\Delta$ \\",
        r"\midrule",
    ]
    for row in comparison.get("rows", []):
        rows.append(
            "{metric} & {baseline} & {selected} & {delta} \\\\".format(
                metric=_escape_latex(labels.get(row.get("metric"), str(row.get("metric")))),
                baseline=_fmt_float(row.get("random_balanced", 0.0)),
                selected=_fmt_float(row.get("diversity_governed", 0.0)),
                delta=_fmt_signed_float(row.get("delta", 0.0)),
            )
        )
    rows.extend([r"\bottomrule", r"\end{tabular}"])
    return _table(
        body="\n".join(rows),
        caption=(
            "Balanced subset comparison at the same graph/category target. "
            "The diversity-governed selector applies MMR-style novelty over Cypher "
            "signatures, template families, structural substructures, schema atoms, "
            "values, and question tokens after quality gates have already passed; "
            "structural/schema gains are reported alongside residual template "
            "concentration."
        ),
        label="tab:diversity_improvement",
    )


def render_ablation_table(
    summaries: list[dict[str, Any]],
    *,
    target_per_category: int,
    category_count: int = 8,
) -> str:
    target_label = _target_label(target_per_category)
    rows = [
        r"\begin{tabular}{llrrrrr}",
        r"\toprule",
        r"Setting & Graph & Attempts & Records & Accepted & Acceptance & Categories at target \\",
        r"\midrule",
    ]
    for summary in sorted(summaries, key=_ablation_sort_key):
        accepted_by_category = summary.get("accepted_by_category", {})
        at_target = sum(
            1 for value in accepted_by_category.values() if int(value) >= target_per_category
        )
        rows.append(
            (
                "{name} & {graph} & {attempts} & {records} & {accepted} & {rate} & "
                "{at_target}/{category_count} \\\\"
            ).format(
                name=_escape_latex(_ablation_label(str(summary.get("run", "")))),
                graph=_escape_latex(_graph_label(str(summary.get("run", "")))),
                attempts=_fmt_int(summary.get("candidate_attempts", summary.get("records", 0))),
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
            f"Live {target_label} ablation evidence with local Qwen3.5-9B. "
            f"Governed graph runs target {target_per_category} accepted examples per category; "
            "the unconstrained row is a stress baseline reported with explicit attempt accounting."
        ),
        label="tab:ablation_results",
    )


def render_ablation_quality_table(
    summaries: list[dict[str, Any]],
    *,
    target_per_category: int,
) -> str:
    target_label = _target_label(target_per_category)
    rows = [
        r"\begin{tabular}{llrrrrr}",
        r"\toprule",
        r"Setting & Graph & Read-only & Syntax & Schema & Exec. & Judge/post-hoc \\",
        r"\midrule",
    ]
    for summary in sorted(summaries, key=_ablation_sort_key):
        gate_rates = _gate_rates(summary)
        rows.append(
            "{name} & {graph} & {read_only} & {syntax} & {schema} & {exec_success} & {judge} \\\\".format(
                name=_escape_latex(_ablation_label(str(summary.get("run", "")))),
                graph=_escape_latex(_graph_label(str(summary.get("run", "")))),
                read_only=_fmt_float(gate_rates.get("read_only", 0.0)),
                syntax=_fmt_float(gate_rates.get("syntax_valid", 0.0)),
                schema=_fmt_float(gate_rates.get("schema_valid", 0.0)),
                exec_success=_fmt_float(gate_rates.get("execution_success", 0.0)),
                judge=_fmt_float(gate_rates.get("judge_pass", 0.0)),
            )
        )
    rows.extend([r"\bottomrule", r"\end{tabular}"])
    return _table(
        body="\n".join(rows),
        caption=(
            f"Quality-gate rates for the live {target_label} ablation suite. "
            "Rates are computed over all generated records in each graph/setting; "
            "for no-judge settings, the judge column is a post-hoc scoring diagnostic."
        ),
        label="tab:ablation_quality",
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
    metrics = snapshot.get("metrics", {})
    graph = coverage.get("by_graph", {})
    difficulty = coverage.get("by_difficulty", {})
    label_status = str(snapshot.get("label_status", "unknown")).replace("_", " ")
    rows = [
        r"\begin{tabular}{lr}",
        r"\toprule",
        r"Audit packet property & Value \\",
        r"\midrule",
        f"Rows & {_fmt_int(coverage.get('total_rows', 0))} \\\\",
        "{label} & {value} \\\\".format(
            label="Human annotators",
            value=_escape_latex(str(snapshot.get("human_annotators", "1 external annotator"))),
        ),
        "{label} & {value} \\\\".format(
            label="IRB status",
            value=_escape_latex(str(snapshot.get("irb_status", "exempt determination"))),
        ),
        "{label} & {value} \\\\".format(
            label="Use of human labels",
            value=_escape_latex(str(snapshot.get("human_label_use", "post-hoc calibration only"))),
        ),
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
        f"Calibration status & {_escape_latex(label_status)} \\\\",
    ]
    if int(metrics.get("total_labeled", 0) or 0):
        rows.extend(
            [
                "Judge-human agreement / $\\kappa$ & {agreement} / {kappa} \\\\".format(
                    agreement=_fmt_float(metrics.get("agreement_rate", 0.0)),
                    kappa=_fmt_float(metrics.get("cohen_kappa", 0.0)),
                ),
                "Judge precision (95\\% CI) & {point} ({ci}) \\\\".format(
                    point=_fmt_float(metrics.get("judge_precision", 0.0)),
                    ci=_fmt_ci(
                        metrics.get("judge_precision_ci_low", 0.0),
                        metrics.get("judge_precision_ci_high", 0.0),
                    ),
                ),
                "Judge recall (95\\% CI) & {point} ({ci}) \\\\".format(
                    point=_fmt_float(metrics.get("judge_recall", 0.0)),
                    ci=_fmt_ci(
                        metrics.get("judge_recall_ci_low", 0.0),
                        metrics.get("judge_recall_ci_high", 0.0),
                    ),
                ),
                "False-accept rate (95\\% CI) & {point} ({ci}) \\\\".format(
                    point=_fmt_float(metrics.get("false_accept_rate", 0.0)),
                    ci=_fmt_ci(
                        metrics.get("false_accept_rate_ci_low", 0.0),
                        metrics.get("false_accept_rate_ci_high", 0.0),
                    ),
                ),
                "False-reject rate (95\\% CI) & {point} ({ci}) \\\\".format(
                    point=_fmt_float(metrics.get("false_reject_rate", 0.0)),
                    ci=_fmt_ci(
                        metrics.get("false_reject_rate_ci_low", 0.0),
                        metrics.get("false_reject_rate_ci_high", 0.0),
                    ),
                ),
            ]
        )
    rows.extend([r"\bottomrule", r"\end{tabular}"])
    return _table(
        body="\n".join(rows),
        caption=(
            "Post-hoc judge calibration packet coverage and judge-human agreement. "
            "Human labels calibrate the automated gate after generation and are not "
            "used as a generation gate."
        ),
        label="tab:judge_audit_coverage",
    )


def render_rewrite_audit_table(summary: dict[str, Any]) -> str:
    execution = summary.get("execution_comparison", {})
    rewrite_counts = summary.get("rewrite_type_counts", {})
    accepted_counts = summary.get("accepted_rewrite_type_counts", {})
    rows = [
        r"\begin{tabular}{lr}",
        r"\toprule",
        r"Rewrite audit property & Value \\",
        r"\midrule",
        f"Generation records audited & {_fmt_int(summary.get('records', 0))} \\\\",
        f"Accepted records audited & {_fmt_int(summary.get('accepted_records', 0))} \\\\",
        f"Records changed by normalization & {_fmt_int(summary.get('changed_records', 0))} \\\\",
        f"Accepted records changed & {_fmt_int(summary.get('accepted_changed_records', 0))} \\\\",
        f"RETURN DISTINCT insertions & {_fmt_int(rewrite_counts.get('return_distinct_inserted', 0) + rewrite_counts.get('return_distinct_only', 0))} \\\\",
        f"Accepted RETURN DISTINCT insertions & {_fmt_int(accepted_counts.get('return_distinct_inserted', 0) + accepted_counts.get('return_distinct_only', 0))} \\\\",
        f"Rewrite-skip reasons logged & {_fmt_int(sum(summary.get('rewrite_skip_reasons', {}).values()))} \\\\",
        f"Live comparisons required & {_fmt_int(execution.get('compared', 0))} \\\\",
        f"Answer-set equality in comparisons & {_fmt_int(execution.get('answer_set_equal', 0))} \\\\",
        r"\bottomrule",
        r"\end{tabular}",
    ]
    return _table(
        body="\n".join(rows),
        caption=(
            "Rewrite prevalence and impact audit over reported generation records. "
            "When no generated query differs from its normalized form, no live "
            "original/normalized re-execution is required for semantic drift."
        ),
        label="tab:rewrite_audit",
    )


def render_governance_audit_table(summary: dict[str, Any]) -> str:
    sources = [
        ("Full generation records", summary.get("generation_records", {})),
        ("Target-size ablations", summary.get("ablation", {})),
        ("Downstream predictions", summary.get("downstream", {})),
        ("Combined", summary),
    ]
    rows = [
        r"\begin{tabular}{lrrrr}",
        r"\toprule",
        r"Evidence source & Direction & Schema/value & Syntax/parser & Read-only \\",
        r"\midrule",
    ]
    for label, data in sources:
        groups = data.get("issue_groups") or data.get("combined_issue_groups") or {}
        rows.append(
            "{label} & {direction} & {schema} & {syntax} & {readonly} \\\\".format(
                label=_escape_latex(label),
                direction=_fmt_int(groups.get("direction", 0)),
                schema=_fmt_int(groups.get("schema_or_value", 0)),
                syntax=_fmt_int(groups.get("syntax_or_parser", 0)),
                readonly=_fmt_int(groups.get("read_only_safety", 0)),
            )
        )
    rows.extend([r"\bottomrule", r"\end{tabular}"])
    return _table(
        body="\n".join(rows),
        caption=(
            "Governance failure audit. Direction errors, schema/value errors, "
            "syntax/parser failures, and read-only violations are counted separately "
            "so the appendix shows which Cypher-specific gates do real work."
        ),
        label="tab:governance_audit",
    )


def render_runtime_accounting_table(summary: dict[str, Any]) -> str:
    rows = [
        r"\begin{tabular}{lrrrrr}",
        r"\toprule",
        r"Scope & Records & Accepted & Acceptance & Exec. p50 ms & Exec. p95 ms \\",
        r"\midrule",
    ]
    scopes = [("Overall", summary.get("overall", {}))]
    scopes.extend(
        (_graph_label_from_key(graph), data)
        for graph, data in sorted(summary.get("by_graph", {}).items())
    )
    for label, data in scopes:
        latency = data.get("execution_latency_ms", {})
        rows.append(
            "{label} & {records} & {accepted} & {rate} & {p50} & {p95} \\\\".format(
                label=_escape_latex(label),
                records=_fmt_int(data.get("records", 0)),
                accepted=_fmt_int(data.get("accepted", 0)),
                rate=_fmt_float(data.get("acceptance_rate", 0.0)),
                p50=_fmt_float(latency.get("median", 0.0)),
                p95=_fmt_float(latency.get("p95", 0.0)),
            )
        )
    rows.extend([r"\bottomrule", r"\end{tabular}"])
    return _table(
        body="\n".join(rows),
        caption=(
            "Operational accounting from completed generation records. These are "
            "local-run latency and acceptance diagnostics, not paid-API cost claims."
        ),
        label="tab:runtime_accounting",
    )


def render_gate_impact_table(summary: dict[str, Any]) -> str:
    blocked = summary.get("blocked_by_gate", {})
    gate_order = [
        "accepted",
        "duplicate_or_diversity",
        "empty_result",
        "judge",
        "schema",
        "direction",
        "value",
        "syntax",
        "read_only",
        "execution",
        "other_reject",
    ]
    rows = [
        r"\begin{tabular}{lrr}",
        r"\toprule",
        r"First blocking gate & Candidates & Share \\",
        r"\midrule",
    ]
    total = max(int(summary.get("records", 0)), 1)
    seen = set()
    for gate in gate_order:
        count = int(blocked.get(gate, 0))
        if count == 0:
            continue
        seen.add(gate)
        rows.append(
            "{gate} & {count} & {share} \\\\".format(
                gate=_escape_latex(_gate_label(gate)),
                count=_fmt_int(count),
                share=_fmt_float(count / total),
            )
        )
    for gate, count in sorted(blocked.items()):
        if gate in seen or not count:
            continue
        rows.append(
            "{gate} & {count} & {share} \\\\".format(
                gate=_escape_latex(_gate_label(gate)),
                count=_fmt_int(count),
                share=_fmt_float(int(count) / total),
            )
        )
    rows.extend([r"\bottomrule", r"\end{tabular}"])
    return _table(
        body="\n".join(rows),
        caption=(
            "Counterfactual first-blocking-gate audit over generation records. "
            "The table shows which failure class would enter the benchmark if that "
            "gate were removed or weakened."
        ),
        label="tab:gate_impact",
    )


def render_redaction_audit_table(summary: dict[str, Any]) -> str:
    linkability = summary.get("placeholder_linkability", {})
    rows = [
        r"\begin{tabular}{lr}",
        r"\toprule",
        r"Redaction audit property & Value \\",
        r"\midrule",
        f"Examples audited & {_fmt_int(summary.get('examples', 0))} \\\\",
        f"Sensitive values checked & {_fmt_int(summary.get('sensitive_values', 0))} \\\\",
        f"Examples with sensitive values & {_fmt_int(summary.get('examples_with_sensitive_values', 0))} \\\\",
        f"Examples with residual raw values & {_fmt_int(summary.get('examples_with_residuals', 0))} \\\\",
        f"Residual raw-value matches & {_fmt_int(summary.get('residual_values', 0))} \\\\",
        f"Residual rate per checked value & {_fmt_float(summary.get('residual_rate_per_value', 0.0))} \\\\",
        f"Unique placeholders & {_fmt_int(linkability.get('unique_placeholders', 0))} \\\\",
        f"Reused placeholders & {_fmt_int(linkability.get('reused_placeholders', 0))} \\\\",
        f"Max placeholder frequency & {_fmt_int(linkability.get('max_placeholder_frequency', 0))} \\\\",
        r"\bottomrule",
        r"\end{tabular}",
    ]
    return _table(
        body="\n".join(rows),
        caption=(
            "Exact-match redaction audit over value-bearing benchmark surfaces. "
            "The audit checks entity bindings, quoted Cypher literals, reverse "
            "grounding literals, and string-valued result samples after applying "
            "the configured redaction policy."
        ),
        label="tab:redaction_audit",
    )


def render_graph_statistics_table(rows: list[dict[str, Any]]) -> str:
    body = [
        r"\begin{tabular}{lrrrrl}",
        r"\toprule",
        r"Graph & Nodes & Relationships & Labels & Rel. types & Study status \\",
        r"\midrule",
    ]
    for row in rows:
        body.append(
            "{graph} & {nodes} & {relationships} & {labels} & {rel_types} & {status} \\\\".format(
                graph=_escape_latex(str(row["graph"])),
                nodes=_fmt_count_or_dash(row["nodes"]),
                relationships=_fmt_count_or_dash(row["relationships"]),
                labels=_fmt_int(row["labels"]),
                rel_types=_fmt_int(row["relationship_types"]),
                status=_escape_latex(str(row["status"])),
            )
        )
    body.extend([r"\bottomrule", r"\end{tabular}"])
    return _table(
        body="\n".join(body),
        caption=(
            "Study graph statistics. ICIJ Offshore Leaks is used as a public "
            "third-graph onboarding audit for arbitrary finance/compliance schemas "
            "beyond the two LDBC study workloads."
        ),
        label="tab:graph_statistics",
    )


def render_icij_onboarding_table(summary: dict[str, Any]) -> str:
    metadata = summary.get("metadata", {})
    audit = summary.get("audit", {})
    schema_accepts = summary.get("legacy_inferred_schema_template_accepts_by_category") or summary.get(
        "schema_template_accepts_by_category", {}
    )
    schema_accept_text = ", ".join(
        f"{_short_category(key)} {_fmt_int(value)}"
        for key, value in sorted(schema_accepts.items())
    ) or "--"
    rows = [
        r"\begin{tabular}{lr}",
        r"\toprule",
        r"ICIJ onboarding property & Value \\",
        r"\midrule",
        f"Graph nodes / relationships & {_fmt_int(metadata.get('graph_nodes', 0))} / {_fmt_int(metadata.get('graph_relationships', 0))} \\\\",
        f"Labels / relationship types & {_fmt_int(metadata.get('graph_labels', 0))} / {_fmt_int(metadata.get('graph_relationship_types', 0))} \\\\",
        f"Generated / accepted & {_fmt_int(summary.get('records', 0))} / {_fmt_int(summary.get('accepted', 0))} \\\\",
        f"Acceptance rate & {_fmt_float(summary.get('accept_rate', 0.0))} \\\\",
        f"Categories at target & {_fmt_int(summary.get('categories_at_target', 0))}/{len(summary.get('expected_categories', []))} \\\\",
        f"Study audit & {_escape_latex('ready' if audit.get('ready_for_paper_promotion') else 'not ready')} \\\\",
        f"Sparse schema-derived accepts & {_escape_latex(schema_accept_text)} \\\\",
        r"\bottomrule",
        r"\end{tabular}",
    ]
    return _table(
        body="\n".join(rows),
        caption=(
            "ICIJ Offshore Leaks third-graph onboarding audit. The public "
            "finance/compliance graph tests arbitrary-schema generation beyond the "
            "two LDBC study workloads; raw values remain outside the reported artifacts."
        ),
        label="tab:icij_onboarding",
    )


def render_category_crosswalk_table() -> str:
    rows = [
        ("Simple retrieval", "SR", "Direct node/edge lookup with exact filters."),
        ("Complex retrieval", "CR", "Multi-hop or multi-pattern retrieval."),
        ("Simple aggregation", "SA", "Single aggregation such as count/min/max/average."),
        ("Complex aggregation", "CA", "Grouped or multi-stage aggregation over graph neighborhoods."),
        ("Boolean existence", "EQ", "Precise yes/no or existence answer."),
        ("Negation/difference", "CR", "Absence, anti-join, or difference query."),
        ("Path/temporal transaction", "CR/CA", "Temporal or path-oriented transaction neighborhood."),
        ("Ranking/top-k", "SA/CA", "Ordered top-k query with explicit limit."),
    ]
    body = [
        r"\begin{tabular}{lll}",
        r"\toprule",
        r"PIPE-Cypher category & Closest MTQ category & Added enterprise distinction \\",
        r"\midrule",
    ]
    for category, mtq, note in rows:
        body.append(
            "{category} & {mtq} & {note} \\\\".format(
                category=_escape_latex(category),
                mtq=_escape_latex(mtq),
                note=_escape_latex(note),
            )
        )
    body.extend([r"\bottomrule", r"\end{tabular}"])
    return _table(
        body="\n".join(body),
        caption=(
            "Category crosswalk to Mind the Query. PIPE-Cypher keeps the familiar "
            "retrieval/aggregation/evaluation-query structure while adding enterprise "
            "workloads such as negation, temporal paths, and ranking."
        ),
        label="tab:category_crosswalk",
    )


def render_validator_cascade_table(stats: dict[str, Any], failure_report: dict[str, Any]) -> str:
    total = int(stats.get("total", 0))
    gates = stats.get("gate_counts", {})
    rejected = int(failure_report.get("rejected", 0))
    rows = [
        ("Export accepted", total, total),
        ("Read-only safety", gates.get("read_only", 0), total),
        ("Syntax validity", gates.get("syntax_valid", 0), total),
        ("Schema/value validity", gates.get("schema_valid", 0), total),
        ("Execution success", gates.get("execution_success", 0), total),
        ("LLM judge pass", gates.get("judge_pass", 0), total),
        ("Rejected candidates logged", rejected, rejected + total if rejected else total),
    ]
    body = [
        r"\begin{tabular}{lrr}",
        r"\toprule",
        r"Gate or ledger & Count & Denominator \\",
        r"\midrule",
    ]
    for gate, count, denominator in rows:
        body.append(
            "{gate} & {count} & {denom} \\\\".format(
                gate=_escape_latex(gate),
                count=_fmt_int(count),
                denom=_fmt_int(denominator),
            )
        )
    body.extend([r"\bottomrule", r"\end{tabular}"])
    return _table(
        body="\n".join(body),
        caption=(
            "PIPE-Cypher validation cascade for the full export and its logged "
            "candidate ledger. Unlike Mind the Query, human review is calibration-only."
        ),
        label="tab:validator_cascade",
    )


def render_prompt_refinement_table() -> str:
    rows = [
        ("Schema-only", "Use only visible schema.", "Baseline for schema-grounded prompting."),
        ("Instructions", "Exact values, datatype rules, no nested aggregations.", "Targets MTQ-style prompt refinements."),
        ("Examples", "Placeholderized retrieved NL-Cypher pairs.", "Tests whether examples help without extra governance."),
        ("Examples + instructions", "Few-shot plus explicit rules.", "Closest controlled analogue to MTQ Table 5."),
        ("Full governed", "Production-derived Cypher hints, AST-safe rewrites, judge gate.", "PIPE-Cypher production setting."),
    ]
    body = [
        r"\begin{tabular}{lll}",
        r"\toprule",
        r"Profile & Added constraint & Intended evidence \\",
        r"\midrule",
    ]
    for profile, constraint, evidence in rows:
        body.append(
            "{profile} & {constraint} & {evidence} \\\\".format(
                profile=_escape_latex(profile),
                constraint=_escape_latex(constraint),
                evidence=_escape_latex(evidence),
            )
        )
    body.extend([r"\bottomrule", r"\end{tabular}"])
    return _table(
        body="\n".join(body),
        caption=(
            "Prompt profiles implemented for Mind-the-Query-style prompt-factorial "
            "evaluation. Results are reported only for completed, audited "
            "target-50-or-larger suites."
        ),
        label="tab:prompt_refinement_plan",
    )


def render_effort_automation_table() -> str:
    rows = [
        ("Generation review gate", "Manual logical review", "Deterministic gates + local LLM judge"),
        ("Human effort", "Reported 1,400 person-hours", "80-row post-hoc judge calibration audit"),
        ("Private values", "Public benchmark values", "Configurable sampling and redacted export"),
        ("Refresh", "Static dataset release", "Rerunnable private benchmark factory"),
        ("Model endpoint", "Gemini in their reported pipeline", "Local Qwen3.5-9B endpoint"),
    ]
    body = [
        r"\begin{tabular}{lll}",
        r"\toprule",
        r"Dimension & Mind the Query & PIPE-Cypher \\",
        r"\midrule",
    ]
    for dimension, mtq, pipe in rows:
        body.append(
            "{dimension} & {mtq} & {pipe} \\\\".format(
                dimension=_escape_latex(dimension),
                mtq=_escape_latex(mtq),
                pipe=_escape_latex(pipe),
            )
        )
    body.extend([r"\bottomrule", r"\end{tabular}"])
    return _table(
        body="\n".join(body),
        caption=(
            "Industry deployment contrast with Mind the Query. PIPE-Cypher focuses on "
            "private refreshable benchmark generation rather than a one-time public dataset."
        ),
        label="tab:effort_automation",
    )


_MAIN_BODY_TABLE_LABELS = {
    "tab:downstream_evaluation",
}


def _table(*, body: str, caption: str, label: str) -> str:
    placement = "t" if label in _MAIN_BODY_TABLE_LABELS else "H"
    return "\n".join(
        [
            rf"\begin{{table}}[{placement}]",
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


def _fmt_count_or_dash(value: Any) -> str:
    if value is None or str(value).strip().lower() in {"", "pending", "unknown"}:
        return "--"
    return _fmt_int(value)


def _fmt_float(value: Any) -> str:
    return f"{float(value):.3f}"


def _fmt_signed_float(value: Any) -> str:
    return f"{float(value):+.3f}"


def _fmt_ci(low: Any, high: Any) -> str:
    return f"{_fmt_float(low)}--{_fmt_float(high)}"


def _short_category(label: str) -> str:
    return {
        "boolean_existence": "boolean",
        "complex_aggregation": "complex agg.",
        "complex_retrieval": "complex ret.",
        "negation_difference": "negation",
        "path_temporal": "path/temp.",
        "ranking_topk": "ranking",
        "simple_aggregation": "simple agg.",
        "simple_retrieval": "simple ret.",
    }.get(str(label), str(label).replace("_", " "))


def _gate_rates(summary: dict[str, Any]) -> dict[str, float]:
    if "gate_rates" in summary:
        return {str(key): float(value) for key, value in summary["gate_rates"].items()}
    records = int(summary.get("records", 0))
    gates = summary.get("gates", {})
    return {
        str(key): (int(value) / records if records else 0.0)
        for key, value in gates.items()
    }


def _target_label(target_per_category: int) -> str:
    if target_per_category == 5:
        return "target-five"
    return f"target-{target_per_category}"


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
        ("prompt_profile_schema_only", "Schema only"),
        ("prompt_profile_instructions_only", "Instructions only"),
        ("prompt_profile_examples_only", "Examples only"),
        ("prompt_profile_examples_plus_instructions", "Examples + instructions"),
        ("prompt_profile_full_pipe_cypher_governed", "Full governed PIPE-Cypher"),
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
        "prompt_profile_schema_only",
        "prompt_profile_instructions_only",
        "prompt_profile_examples_only",
        "prompt_profile_examples_plus_instructions",
        "prompt_profile_full_pipe_cypher_governed",
    ]
    for idx, needle in enumerate(order):
        if needle in run:
            return idx * 10 + _graph_sort_key(run)
    return len(order) * 10 + _graph_sort_key(run)


def _graph_label(run: str) -> str:
    if "_snb_" in run or "snb" in run.lower():
        return "SNB"
    return "FinBench"


def _graph_label_from_key(graph: str) -> str:
    return {
        "finbench": "FinBench",
        "snb": "SNB",
        "icij": "ICIJ",
        "icij_offshoreleaks": "ICIJ",
    }.get(str(graph).lower(), str(graph))


def _gate_label(gate: str) -> str:
    return {
        "accepted": "Accepted",
        "duplicate_or_diversity": "Duplicate/diversity",
        "empty_result": "Empty result",
        "judge": "Judge reject",
        "schema": "Schema",
        "direction": "Direction",
        "value": "Value",
        "syntax": "Syntax/parser",
        "read_only": "Read-only",
        "execution": "Execution failure",
        "other_reject": "Other reject",
    }.get(gate, gate.replace("_", " ").title())


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
