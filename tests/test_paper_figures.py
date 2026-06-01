from __future__ import annotations

from pathlib import Path


def test_render_downstream_uncertainty_figure_writes_pdf(tmp_path: Path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from scripts.render_paper_figures import render_downstream_uncertainty_figure

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
