from __future__ import annotations

from pathlib import Path

from pipecypher.strategy_analysis import render_strategy_table, strategy_report


def _benchmark_row(example_id: str, category: str, primary: str, tags: list[str]) -> dict:
    return {
        "id": example_id,
        "category": category,
        "structural_features": {
            "primary_strategy": primary,
            "strategy_tags": tags,
            "relationship_pattern_count": 2 if "join_heavy" in tags else 1,
            "return_arity": 2,
        },
        "result_row_count_observed": 3,
    }


def test_strategy_report_computes_category_coverage_and_downstream_errors():
    benchmark = [
        _benchmark_row("a", "complex_retrieval", "join_heavy", ["join_heavy"]),
        _benchmark_row("b", "simple_aggregation", "aggregation", ["single_hop", "aggregation"]),
    ]
    evaluation = [
        {"id": "a", "parse_valid": True, "schema_valid": True, "execution_success": True, "execution_accuracy": False},
        {"id": "b", "parse_valid": True, "schema_valid": True, "execution_success": True, "execution_accuracy": True},
    ]

    report = strategy_report(benchmark, evaluation)

    assert report["total_examples"] == 2
    assert report["category_strategy_counts"]["complex_retrieval"]["join_heavy"] == 1
    assert report["category_strategy_rates"]["simple_aggregation"]["aggregation"] == 1.0
    assert report["downstream_by_strategy"]["join_heavy"]["error_bucket_counts"]["answer_mismatch"] == 1
    assert report["downstream_by_strategy"]["aggregation"]["execution_accuracy"] == 1.0


def test_render_strategy_table_includes_label_and_downstream_metric():
    report = strategy_report(
        [_benchmark_row("a", "simple_aggregation", "aggregation", ["single_hop", "aggregation"])],
        [{"id": "a", "parse_valid": True, "schema_valid": True, "execution_success": True, "execution_accuracy": True}],
    )

    text = render_strategy_table(report)

    assert r"\label{tab:strategy_diagnostics}" in text
    assert "Aggregation" in text
    assert "1.000" in text


def test_strategy_figures_write_pdfs(tmp_path: Path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from pipecypher.paper_style import apply_paper_style
    from scripts.analyze_strategy_diagnostics import (
        render_strategy_coverage_figure,
        render_strategy_downstream_error_figure,
    )

    apply_paper_style(plt)
    report = strategy_report(
        [
            _benchmark_row("a", "complex_retrieval", "join_heavy", ["join_heavy"]),
            _benchmark_row("b", "simple_aggregation", "aggregation", ["single_hop", "aggregation"]),
        ],
        [
            {"id": "a", "parse_valid": True, "schema_valid": True, "execution_success": False, "execution_accuracy": False},
            {"id": "b", "parse_valid": True, "schema_valid": True, "execution_success": True, "execution_accuracy": True},
        ],
    )

    coverage = tmp_path / "coverage.pdf"
    downstream = tmp_path / "downstream.pdf"
    render_strategy_coverage_figure(report, coverage, plt)
    render_strategy_downstream_error_figure(report, downstream, plt)

    assert coverage.exists()
    assert coverage.stat().st_size > 1000
    assert downstream.exists()
    assert downstream.stat().st_size > 1000
