from __future__ import annotations

from pathlib import Path


def test_render_downstream_uncertainty_figure_writes_pdf(tmp_path: Path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from pipecypher.paper_style import apply_paper_style
    from scripts.render_paper_figures import render_downstream_uncertainty_figure

    apply_paper_style(plt)
    report = {
        "confidence_level": 0.95,
        "groups": {
            "category": {
                "simple_aggregation": {
                    "execution_accuracy": {
                        "point": 1.0,
                        "lower": 0.9,
                        "upper": 1.0,
                    },
                    "execution_success": {
                        "point": 1.0,
                        "lower": 0.9,
                        "upper": 1.0,
                    },
                },
                "ranking_topk": {
                    "execution_accuracy": {
                        "point": 0.2,
                        "lower": 0.1,
                        "upper": 0.35,
                    },
                    "execution_success": {
                        "point": 0.6,
                        "lower": 0.45,
                        "upper": 0.75,
                    },
                },
            }
        },
    }
    output = tmp_path / "downstream_uncertainty.pdf"

    render_downstream_uncertainty_figure(report, output, plt)

    assert output.exists()
    assert output.stat().st_size > 1000


def test_render_ablation_quality_figure_writes_pdf(tmp_path: Path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from pipecypher.paper_style import apply_paper_style
    from scripts.render_ablation_suite_figure import render_ablation_quality_figure

    apply_paper_style(plt)
    summary = {
        "target_per_category": 50,
        "expected_graphs": ["finbench", "snb"],
        "expected_variants": ["reverse_only", "full_pipe_cypher"],
        "runs": [
            {
                "graph": "finbench",
                "variant": "reverse_only",
                "records": 400,
                "gate_rates": {
                    "read_only": 1.0,
                    "syntax_valid": 1.0,
                    "schema_valid": 1.0,
                    "execution_success": 1.0,
                    "judge_pass": 0.98,
                },
            },
            {
                "graph": "snb",
                "variant": "full_pipe_cypher",
                "records": 405,
                "gate_rates": {
                    "read_only": 1.0,
                    "syntax_valid": 1.0,
                    "schema_valid": 0.995,
                    "execution_success": 0.995,
                    "judge_pass": 0.992,
                },
            },
        ],
    }
    output = tmp_path / "ablation_quality.pdf"

    render_ablation_quality_figure(summary, output, plt)

    assert output.exists()
    assert output.stat().st_size > 1000


def test_paper_style_sets_pdf_font_embedding():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from pipecypher.paper_style import PALETTE, apply_paper_style

    apply_paper_style(plt)

    assert plt.rcParams["pdf.fonttype"] == 42
    assert plt.rcParams["axes.edgecolor"] == PALETTE["slate"]
