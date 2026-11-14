from __future__ import annotations

from pipecypher.evaluation_uncertainty import (
    analyze_evaluation_uncertainty,
    bootstrap_metric_interval,
    format_evaluation_uncertainty_markdown,
    render_downstream_uncertainty_table,
)


def _rows():
    return [
        {
            "graph_profile": "finbench",
            "category": "simple_retrieval",
            "difficulty": "easy",
            "parse_valid": True,
            "schema_valid": True,
            "execution_success": True,
            "execution_accuracy": True,
            "answer_f1": 1.0,
        },
        {
            "graph_profile": "finbench",
            "category": "ranking_topk",
            "difficulty": "medium",
            "parse_valid": True,
            "schema_valid": True,
            "execution_success": True,
            "execution_accuracy": False,
            "answer_f1": 0.0,
        },
        {
            "graph_profile": "snb",
            "category": "ranking_topk",
            "difficulty": "medium",
            "parse_valid": False,
            "schema_valid": False,
            "execution_success": False,
            "execution_accuracy": False,
            "answer_f1": 0.0,
        },
        {
            "graph_profile": "snb",
            "category": "simple_retrieval",
            "difficulty": "easy",
            "parse_valid": True,
            "schema_valid": True,
            "execution_success": True,
            "execution_accuracy": True,
            "answer_f1": 0.5,
        },
    ]


def test_bootstrap_metric_interval_is_deterministic_and_contains_point():
    first = bootstrap_metric_interval(
        _rows(),
        "execution_accuracy",
        iterations=200,
        seed=7,
    )
    second = bootstrap_metric_interval(
        _rows(),
        "execution_accuracy",
        iterations=200,
        seed=7,
    )

    assert first == second
    assert first["n"] == 4
    assert first["point"] == 0.5
    assert first["lower"] <= first["point"] <= first["upper"]
    assert first["standard_error"] > 0.0


def test_analyze_evaluation_uncertainty_groups_by_graph_category_and_difficulty():
    report = analyze_evaluation_uncertainty(
        _rows(),
        iterations=100,
        seed=11,
    )

    assert report["overall"]["answer_f1"]["point"] == 0.375
    assert report["groups"]["graph_profile"]["finbench"]["execution_success"]["point"] == 1.0
    assert report["groups"]["graph_profile"]["snb"]["parse_valid"]["point"] == 0.5
    assert report["groups"]["category"]["ranking_topk"]["execution_accuracy"]["point"] == 0.0
    assert report["groups"]["difficulty"]["easy"]["execution_accuracy"]["point"] == 1.0


def test_uncertainty_markdown_and_tex_are_appendix_ready():
    report = analyze_evaluation_uncertainty(
        _rows(),
        iterations=100,
        seed=11,
    )

    markdown = format_evaluation_uncertainty_markdown(report)
    tex = render_downstream_uncertainty_table(report)

    assert "nonparametric bootstrap" in markdown
    assert "| execution_accuracy | 4 | 0.500" in markdown
    assert r"\label{tab:downstream_uncertainty}" in tex
    assert "Execution accuracy & 0.500" in tex
