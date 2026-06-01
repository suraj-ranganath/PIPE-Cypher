from __future__ import annotations

from pipecypher.paper_tables import (
    render_ablation_table,
    render_benchmark_export_table,
    render_downstream_table,
    render_full_artifact_distribution_table,
    render_judge_audit_coverage_table,
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
                "records": 0,
                "accepted": 0,
                "accept_rate": 0.0,
                "accepted_by_category": {},
            },
        ],
        target_per_category=5,
        category_count=8,
    )

    assert "Unconstrained LLM & FinBench & 0 & 0 & 0.000 & 0/8" in text
    assert "Full PIPE-Cypher & FinBench & 41 & 40 & 0.976 & 2/8" in text
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
    assert "Full PIPE-Cypher & SNB & 201 & 200 & 0.995 & 1/8" in text


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
