from __future__ import annotations

from pipecypher.paper_tables import (
    render_category_crosswalk_table,
    render_ablation_quality_table,
    render_ablation_table,
    render_benchmark_export_table,
    render_downstream_error_table,
    render_downstream_table,
    render_effort_automation_table,
    render_full_artifact_distribution_table,
    render_graph_statistics_table,
    render_icij_onboarding_table,
    render_judge_audit_coverage_table,
    render_prompt_refinement_table,
    render_validator_cascade_table,
)


def _stats():
    return {
        "total": 3000,
        "by_split": {"train": 2408, "dev": 296, "test": 296},
        "by_graph": {"finbench": 2000, "snb": 1000},
        "by_category": {"simple_retrieval": 375, "ranking_topk": 375},
        "by_graph_category": {
            "finbench::simple_retrieval": 250,
            "finbench::ranking_topk": 250,
            "snb::simple_retrieval": 125,
            "snb::ranking_topk": 125,
        },
        "by_difficulty": {"easy": 1521, "medium": 1479},
        "gate_counts": {
            "read_only": 3000,
            "syntax_valid": 3000,
            "schema_valid": 3000,
            "execution_success": 3000,
            "judge_pass": 3000,
        },
        "unique_labels": ["Account", "Person"],
        "unique_relationship_types": ["OWN_ACCOUNT"],
    }


def test_render_benchmark_export_table_uses_manifest_and_stats():
    text = render_benchmark_export_table(_stats(), {"sha256": "abcdef0123456789ffff"})

    assert "Live full benchmark & 3,000 & 2,000 & 1,000 & 2,408 & 296 & 296" in text
    assert r"\texttt{abcdef0123456789}" in text


def test_render_full_artifact_distribution_table_summarizes_gates():
    text = render_full_artifact_distribution_table(_stats())

    assert "2 balanced categories" in text
    assert "1,521 easy / 1,479 medium" in text
    assert "Used labels / rel. types" in text
    assert "3,000/3,000" in text


def test_render_downstream_table_uses_overall_metrics():
    text = render_downstream_table(
        {
            "overall": {
                "n": 296,
                "parse_valid": 0.959459,
                "schema_valid": 0.905405,
                "execution_success": 0.621621,
                "execution_accuracy": 0.189189,
                "answer_f1": 0.189189,
            }
        }
    )

    assert "Live full test & 296 & 0.959 & 0.905 & 0.622 & 0.189 & 0.189" in text


def test_render_downstream_error_table_reports_incorrect_shares():
    text = render_downstream_error_table(
        {
            "incorrect": 10,
            "bucket_labels": {
                "answer_mismatch": "Answer mismatch",
                "execution_failed": "Execution failed",
            },
            "error_bucket_counts": {
                "answer_mismatch": 7,
                "execution_failed": 3,
            },
        }
    )

    assert "Answer mismatch & 7 & 0.700" in text
    assert "Execution failed & 3 & 0.300" in text
    assert r"\label{tab:downstream_error_taxonomy}" in text


def test_render_ablation_table_orders_and_counts_targets():
    text = render_ablation_table(
        [
            {
                "run": "20260601_full_pipe_cypher",
                "records": 41,
                "accepted": 40,
                "accept_rate": 40 / 41,
                "accepted_by_category": {"simple_retrieval": 5, "ranking_topk": 5},
            },
            {
                "run": "20260601_unconstrained_local_llm_strict",
                "candidate_attempts": 3200,
                "records": 0,
                "accepted": 0,
                "accept_rate": 0.0,
                "accepted_by_category": {},
            },
        ],
        target_per_category=5,
        category_count=8,
    )

    assert "Unconstrained LLM & FinBench & 3,200 & 0 & 0 & 0.000 & 0/8" in text
    assert "Full PIPE-Cypher & FinBench & 41 & 41 & 40 & 0.976 & 2/8" in text
    assert text.index("Unconstrained LLM") < text.index("Full PIPE-Cypher")


def test_render_ablation_table_uses_requested_target_label():
    text = render_ablation_table(
        [
            {
                "run": "20260601_ablation25_snb_full_pipe_cypher",
                "records": 201,
                "accepted": 200,
                "accept_rate": 200 / 201,
                "accepted_by_category": {"simple_retrieval": 25, "ranking_topk": 24},
            }
        ],
        target_per_category=25,
        category_count=8,
    )

    assert "Live target-25 ablation evidence" in text
    assert "unconstrained row is a stress baseline" in text
    assert "Full PIPE-Cypher & SNB & 201 & 201 & 200 & 0.995 & 1/8" in text


def test_render_ablation_quality_table_reports_gate_rates():
    text = render_ablation_quality_table(
        [
            {
                "run": "20260601_ablation25_snb_full_pipe_cypher",
                "records": 200,
                "gate_rates": {
                    "read_only": 1.0,
                    "syntax_valid": 1.0,
                    "schema_valid": 0.995,
                    "execution_success": 0.985,
                    "judge_pass": 0.975,
                },
            }
        ],
        target_per_category=25,
    )

    assert "Judge/post-hoc" in text
    assert "Quality-gate rates for the live target-25 ablation suite" in text
    assert "Full PIPE-Cypher & SNB & 1.000 & 1.000 & 0.995 & 0.985 & 0.975" in text


def test_render_judge_audit_coverage_table_reports_packet_balance():
    text = render_judge_audit_coverage_table(
        {
            "coverage": {
                "total_rows": 80,
                "judge_accepts": 40,
                "judge_rejects": 40,
                "labeled_rows": 0,
                "by_graph": {"finbench": 48, "snb": 32},
                "by_difficulty": {"easy": 26, "medium": 54},
            }
        }
    )

    assert "Rows & 80" in text
    assert "Judge accept / reject & 40 / 40" in text
    assert "FinBench / SNB rows & 48 / 32" in text
    assert "Labeled rows & 0" in text

    labeled_text = render_judge_audit_coverage_table(
        {
            "coverage": {
                "total_rows": 80,
                "judge_accepts": 40,
                "judge_rejects": 40,
                "labeled_rows": 80,
                "by_graph": {"finbench": 48, "snb": 32},
                "by_difficulty": {"easy": 26, "medium": 54},
            },
            "metrics": {
                "total_labeled": 80,
                "agreement_rate": 0.8,
                "cohen_kappa": 0.6,
                "judge_precision": 1.0,
                "judge_precision_ci_low": 0.91,
                "judge_precision_ci_high": 1.0,
                "judge_recall": 0.714,
                "judge_recall_ci_low": 0.58,
                "judge_recall_ci_high": 0.82,
                "false_accept_rate": 0.0,
                "false_accept_rate_ci_low": 0.0,
                "false_accept_rate_ci_high": 0.09,
                "false_reject_rate": 0.286,
                "false_reject_rate_ci_low": 0.18,
                "false_reject_rate_ci_high": 0.42,
            },
        }
    )

    assert "Judge precision (95\\% CI) & 1.000 (0.910--1.000)" in labeled_text
    assert "False-accept rate (95\\% CI) & 0.000 (0.000--0.090)" in labeled_text


def test_render_graph_statistics_table_marks_pending_counts_with_dash():
    text = render_graph_statistics_table(
        [
            {
                "graph": "FinBench",
                "nodes": 10006,
                "relationships": 57622,
                "labels": 5,
                "relationship_types": 9,
                "status": "reported",
            },
            {
                "graph": "ICIJ",
                "nodes": None,
                "relationships": None,
                "labels": 5,
                "relationship_types": 14,
                "status": "onboarding only",
            },
        ]
    )

    assert "FinBench & 10,006 & 57,622 & 5 & 9 & reported" in text
    assert "ICIJ & -- & -- & 5 & 14 & onboarding only" in text


def test_render_icij_onboarding_table_reports_sanitized_audit_summary():
    text = render_icij_onboarding_table(
        {
            "metadata": {
                "graph_nodes": "2016523",
                "graph_relationships": "3339267",
                "graph_labels": "5",
                "graph_relationship_types": "14",
            },
            "records": 983,
            "accepted": 800,
            "accept_rate": 800 / 983,
            "categories_at_target": 8,
            "expected_categories": ["simple_retrieval"] * 8,
            "audit": {"ready_for_paper_promotion": True},
            "legacy_inferred_schema_template_accepts_by_category": {
                "complex_aggregation": 97,
                "ranking_topk": 98,
            },
        }
    )

    assert "2,016,523 / 3,339,267" in text
    assert "983 / 800" in text
    assert "ready" in text
    assert "complex agg. 97" in text
    assert r"\label{tab:icij_onboarding}" in text


def test_render_validator_cascade_table_reports_full_run_gates():
    text = render_validator_cascade_table(
        _stats(),
        {"rejected": 1777},
    )

    assert "Read-only safety & 3,000 & 3,000" in text
    assert "Rejected candidates logged & 1,777 & 4,777" in text
    assert r"\label{tab:validator_cascade}" in text


def test_render_category_crosswalk_prompt_and_effort_tables():
    assert "Boolean existence" in render_category_crosswalk_table()
    assert "Prompt profiles implemented" in render_prompt_refinement_table()
    assert "80-row post-hoc judge calibration audit" in render_effort_automation_table()
    assert "Gemini in their reported pipeline" in render_effort_automation_table()
