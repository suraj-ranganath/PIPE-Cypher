#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.paper_style import GRAPH_COLORS, METRIC_COLORS, PALETTE, apply_paper_style, style_axis


def main() -> None:
    parser = argparse.ArgumentParser(description="Render appendix-ready PIPE-Cypher paper figures.")
    parser.add_argument("--diversity-report", required=True)
    parser.add_argument(
        "--benchmark-stats",
        default="artifacts/benchmarks/20260601_live_full_qwen9b/stats.json",
    )
    parser.add_argument(
        "--downstream-summary",
        default="artifacts/evaluations/20260601_full_qwen9b_test_summary.json",
    )
    parser.add_argument(
        "--downstream-uncertainty",
        default="experiments/snapshots/20260601_live_full_qwen9b/downstream_uncertainty.json",
    )
    parser.add_argument(
        "--failure-taxonomy",
        default="experiments/snapshots/20260601_live_full_qwen9b/failure_taxonomy.json",
    )
    parser.add_argument(
        "--downstream-errors",
        default="experiments/snapshots/20260601_live_full_qwen9b/downstream_error_report.json",
    )
    parser.add_argument("--output-dir", default="paper_emnlp2026_industry/figures")
    args = parser.parse_args()

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    apply_paper_style(plt)

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    diversity_report = json.loads(Path(args.diversity_report).read_text(encoding="utf-8"))
    benchmark_stats = json.loads(Path(args.benchmark_stats).read_text(encoding="utf-8"))
    downstream_summary = json.loads(Path(args.downstream_summary).read_text(encoding="utf-8"))
    downstream_uncertainty = json.loads(
        Path(args.downstream_uncertainty).read_text(encoding="utf-8")
    )
    failure_taxonomy = json.loads(Path(args.failure_taxonomy).read_text(encoding="utf-8"))
    downstream_errors = json.loads(Path(args.downstream_errors).read_text(encoding="utf-8"))

    render_pipeline_overview_figure(out / "pipeline_overview.pdf", plt)
    render_diversity_figure(diversity_report, out / "diversity_diagnostics.pdf", plt)
    render_full_distribution_figure(benchmark_stats, out / "full_export_distribution.pdf", plt)
    render_downstream_figure(downstream_summary, out / "downstream_breakdown.pdf", plt)
    render_downstream_uncertainty_figure(
        downstream_uncertainty,
        out / "downstream_uncertainty.pdf",
        plt,
    )
    render_failure_taxonomy_figure(failure_taxonomy, out / "failure_taxonomy.pdf", plt)
    if failure_taxonomy.get("empty_result_diagnostic_counts"):
        render_empty_result_diagnostic_figure(
            failure_taxonomy,
            out / "empty_result_diagnostics.pdf",
            plt,
        )
    render_downstream_error_figure(
        downstream_errors,
        out / "downstream_error_taxonomy.pdf",
        plt,
    )
    print(f"wrote {out / 'pipeline_overview.pdf'}")
    print(f"wrote {out / 'diversity_diagnostics.pdf'}")
    print(f"wrote {out / 'full_export_distribution.pdf'}")
    print(f"wrote {out / 'downstream_breakdown.pdf'}")
    print(f"wrote {out / 'downstream_uncertainty.pdf'}")
    print(f"wrote {out / 'failure_taxonomy.pdf'}")
    if failure_taxonomy.get("empty_result_diagnostic_counts"):
        print(f"wrote {out / 'empty_result_diagnostics.pdf'}")
    print(f"wrote {out / 'downstream_error_taxonomy.pdf'}")


def render_pipeline_overview_figure(output: Path, plt) -> None:
    stages = [
        ("Schema +\nprivacy policy", "introspect, sample,\nredact values"),
        ("Reverse\n grounding", "bind slots with\nlive Cypher"),
        ("Constrained\n generation", "local Qwen,\nprofiled prompts"),
        ("AST governance\n+ rewrite", "read-only, schema,\ndirection, DISTINCT"),
        ("Execution\n diagnostics", "run, repair,\nempty-result audit"),
        ("LLM judge\n+ calibration", "local judge,\nhuman audit sample"),
        ("Benchmark\n export/refresh", "splits, card,\nredacted artifacts"),
    ]
    fig, ax = plt.subplots(figsize=(9.4, 2.7))
    ax.axis("off")
    colors = [
        PALETTE["blue"],
        PALETTE["green"],
        PALETTE["orange"],
        PALETTE["violet"],
        PALETTE["red"],
        PALETTE["slate"],
        PALETTE["ink"],
    ]
    x_positions = [idx / (len(stages) - 1) for idx in range(len(stages))]
    for idx, ((title, subtitle), x_pos) in enumerate(zip(stages, x_positions, strict=True)):
        ax.text(
            x_pos,
            0.62,
            title,
            ha="center",
            va="center",
            fontsize=9,
            fontweight="bold",
            color="white",
            bbox={
                "boxstyle": "round,pad=0.35,rounding_size=0.04",
                "facecolor": colors[idx],
                "edgecolor": "none",
            },
            transform=ax.transAxes,
        )
        ax.text(
            x_pos,
            0.22,
            subtitle,
            ha="center",
            va="center",
            fontsize=7.5,
            color=PALETTE["slate"],
            transform=ax.transAxes,
        )
        if idx + 1 < len(stages):
            ax.annotate(
                "",
                xy=(x_positions[idx + 1] - 0.07, 0.62),
                xytext=(x_pos + 0.07, 0.62),
                arrowprops={"arrowstyle": "->", "color": PALETTE["slate"], "lw": 1.1},
                xycoords=ax.transAxes,
                textcoords=ax.transAxes,
            )
    ax.text(
        0.5,
        0.94,
        "PIPE-Cypher generates private, executable NL-to-Cypher benchmarks as graphs evolve",
        ha="center",
        va="center",
        fontsize=10,
        fontweight="bold",
        color=PALETTE["slate"],
        transform=ax.transAxes,
    )
    fig.tight_layout()
    fig.savefig(output)
    plt.close(fig)


def render_diversity_figure(report: dict, output: Path, plt) -> None:
    value_grounding = report["value_grounding"]
    values = {
        "Category\nbalance": report["distributions"]["category"]["normalized_entropy"],
        "Graph-category\nbalance": report["distributions"]["graph_category"]["normalized_entropy"],
        "Difficulty\nbalance": report["distributions"]["difficulty"]["normalized_entropy"],
        "Distinct-2\nquestions": report["question_text"]["distinct_2"],
        "Query-signature\nratio": report["query_templates"]["unique_signature_ratio"],
        "Grounded-value\nratio": value_grounding["unique_entity_value_ratio"],
        "Exact quoted\nvalues": value_grounding["entity_values_exact_quoted_rate"],
        "Label\ncoverage": report["schema_coverage"]["labels"]["coverage"],
        "Rel-type\ncoverage": report["schema_coverage"]["relationship_types"]["coverage"],
        "Property\ncoverage": report["schema_coverage"]["properties"]["coverage"],
    }
    fig, ax = plt.subplots(figsize=(9.2, 3.2))
    bars = ax.bar(range(len(values)), list(values.values()), color=PALETTE["blue"])
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Normalized score")
    ax.set_title("Full benchmark diversity diagnostics")
    ax.set_xticks(range(len(values)))
    ax.set_xticklabels(list(values.keys()), rotation=0, ha="center", fontsize=8)
    style_axis(ax, grid_axis="y")
    for bar in bars:
        height = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            height + 0.02,
            f"{height:.2f}",
            ha="center",
            va="bottom",
            fontsize=7,
        )
    fig.tight_layout()
    fig.savefig(output)
    plt.close(fig)


def render_full_distribution_figure(stats: dict, output: Path, plt) -> None:
    category_counts = dict(sorted(stats["by_category"].items()))
    graph_category_counts = stats["by_graph_category"]
    difficulties = dict(sorted(stats["by_difficulty"].items()))

    categories = list(category_counts)
    finbench = [graph_category_counts.get(f"finbench::{category}", 0) for category in categories]
    snb = [graph_category_counts.get(f"snb::{category}", 0) for category in categories]

    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.4), gridspec_kw={"width_ratios": [3, 1]})
    x_positions = range(len(categories))
    axes[0].bar(x_positions, finbench, label="FinBench", color=GRAPH_COLORS["finbench"])
    axes[0].bar(x_positions, snb, bottom=finbench, label="SNB", color=GRAPH_COLORS["snb"])
    axes[0].set_title("Full export category balance")
    axes[0].set_ylabel("Accepted examples")
    axes[0].set_xticks(list(x_positions))
    axes[0].set_xticklabels([_short_category(label) for label in categories], rotation=28, ha="right", fontsize=8)
    axes[0].legend(frameon=False, ncols=2, loc="upper left")
    style_axis(axes[0], grid_axis="y")

    diff_labels = list(difficulties)
    diff_values = [difficulties[label] for label in diff_labels]
    axes[1].bar(
        diff_labels,
        diff_values,
        color=[PALETTE["green"], PALETTE["violet"], PALETTE["red"]][: len(diff_labels)],
    )
    axes[1].set_title("Difficulty")
    axes[1].set_ylim(0, max(diff_values) * 1.2 if diff_values else 1)
    style_axis(axes[1], grid_axis="y")
    for idx, value in enumerate(diff_values):
        axes[1].text(idx, value + 20, str(value), ha="center", va="bottom", fontsize=8)

    fig.tight_layout()
    fig.savefig(output)
    plt.close(fig)


def render_downstream_figure(summary: dict, output: Path, plt) -> None:
    categories = list(sorted(summary["by_category"]))
    metrics = [
        ("execution_accuracy", "Exec. accuracy", METRIC_COLORS["execution_accuracy"]),
        ("execution_success", "Exec. success", METRIC_COLORS["execution_success"]),
        ("schema_valid", "Schema valid", METRIC_COLORS["schema_valid"]),
    ]
    x_positions = list(range(len(categories)))
    width = 0.25

    fig, ax = plt.subplots(figsize=(9.2, 3.5))
    for idx, (metric, label, color) in enumerate(metrics):
        values = [summary["by_category"][category][metric] for category in categories]
        offsets = [x + (idx - 1) * width for x in x_positions]
        ax.bar(offsets, values, width, label=label, color=color)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Rate")
    ax.set_title("Downstream Qwen3.5-9B zero-shot Text2Cypher breakdown")
    ax.set_xticks(x_positions)
    ax.set_xticklabels([_short_category(label) for label in categories], rotation=28, ha="right", fontsize=8)
    ax.legend(frameon=False, ncols=3, loc="upper left")
    style_axis(ax, grid_axis="y")
    fig.tight_layout()
    fig.savefig(output)
    plt.close(fig)


def render_downstream_uncertainty_figure(report: dict, output: Path, plt) -> None:
    category_groups = report["groups"]["category"]
    categories = list(sorted(category_groups))
    metrics = [
        ("execution_accuracy", "Execution accuracy", METRIC_COLORS["execution_accuracy"]),
        ("execution_success", "Execution success", METRIC_COLORS["execution_success"]),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(9.4, 3.6), sharey=True)
    x_positions = list(range(len(categories)))
    confidence = int(round(float(report.get("confidence_level", 0.95)) * 100))

    for ax, (metric, title, color) in zip(axes, metrics, strict=True):
        points = [category_groups[category][metric]["point"] for category in categories]
        lowers = [category_groups[category][metric]["lower"] for category in categories]
        uppers = [category_groups[category][metric]["upper"] for category in categories]
        yerr = [
            [point - lower for point, lower in zip(points, lowers, strict=True)],
            [upper - point for point, upper in zip(points, uppers, strict=True)],
        ]
        ax.errorbar(
            x_positions,
            points,
            yerr=yerr,
            fmt="o",
            color=color,
            ecolor=color,
            elinewidth=1.2,
            capsize=3,
            markersize=4.5,
        )
        ax.set_title(title)
        ax.set_ylim(-0.04, 1.05)
        ax.set_xticks(x_positions)
        ax.set_xticklabels(
            [_short_category(label) for label in categories],
            rotation=35,
            ha="right",
            fontsize=8,
        )
        style_axis(ax, grid_axis="y")
        ax.axhline(0.0, color=PALETTE["slate"], linewidth=0.7)
    axes[0].set_ylabel(f"Rate with {confidence}% bootstrap CI")
    fig.suptitle("Downstream Qwen3.5-9B uncertainty by workload category", y=1.02)
    fig.tight_layout()
    fig.savefig(output)
    plt.close(fig)


def render_failure_taxonomy_figure(report: dict, output: Path, plt) -> None:
    labels = report.get("bucket_labels", {})
    counts = sorted(
        report.get("rejection_bucket_counts", {}).items(),
        key=lambda item: (-int(item[1]), item[0]),
    )
    names = [labels.get(key, key.replace("_", " ").title()) for key, _ in counts]
    values = [int(value) for _, value in counts]
    total_rejected = max(int(report.get("rejected", 0)), 1)
    palette = [
        PALETTE["blue"],
        PALETTE["orange"],
        PALETTE["green"],
        PALETTE["violet"],
        PALETTE["red"],
        PALETTE["slate"],
    ]
    colors = [palette[idx % len(palette)] for idx in range(len(names))]

    fig, ax = plt.subplots(figsize=(7.4, 3.0))
    bars = ax.barh(range(len(names)), values, color=colors)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Rejected candidates")
    ax.set_title("Full-run rejection taxonomy before export")
    style_axis(ax, grid_axis="x")
    for bar, value in zip(bars, values, strict=True):
        ax.text(
            bar.get_width() + max(values) * 0.015,
            bar.get_y() + bar.get_height() / 2,
            f"{value} ({value / total_rejected:.1%})",
            va="center",
            fontsize=8,
        )
    ax.set_xlim(0, max(values) * 1.22 if values else 1)
    fig.tight_layout()
    fig.savefig(output)
    plt.close(fig)


def render_empty_result_diagnostic_figure(report: dict, output: Path, plt) -> None:
    counts = sorted(
        report.get("empty_result_diagnostic_counts", {}).items(),
        key=lambda item: (-int(item[1]), item[0]),
    )
    names = [key.replace("_", " ").title() for key, _ in counts]
    values = [int(value) for _, value in counts]
    total = max(sum(values), 1)
    colors = [
        PALETTE["blue"],
        PALETTE["orange"],
        PALETTE["green"],
        PALETTE["violet"],
        PALETTE["red"],
        PALETTE["slate"],
    ][: len(values)]

    fig, ax = plt.subplots(figsize=(7.4, 2.8))
    bars = ax.barh(range(len(names)), values, color=colors)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Execution-empty rejected candidates")
    ax.set_title("Empty-result diagnostic breakdown")
    style_axis(ax, grid_axis="x")
    for bar, value in zip(bars, values, strict=True):
        ax.text(
            bar.get_width() + max(values) * 0.015,
            bar.get_y() + bar.get_height() / 2,
            f"{value} ({value / total:.1%})",
            va="center",
            fontsize=8,
        )
    ax.set_xlim(0, max(values) * 1.22 if values else 1)
    fig.tight_layout()
    fig.savefig(output)
    plt.close(fig)


def render_downstream_error_figure(report: dict, output: Path, plt) -> None:
    labels = report.get("bucket_labels", {})
    counts = sorted(
        report.get("error_bucket_counts", {}).items(),
        key=lambda item: (-int(item[1]), item[0]),
    )
    names = [labels.get(key, key.replace("_", " ").title()) for key, _ in counts]
    values = [int(value) for _, value in counts]
    incorrect = max(int(report.get("incorrect", 0)), 1)
    palette = [
        PALETTE["orange"],
        PALETTE["blue"],
        PALETTE["violet"],
        PALETTE["green"],
        PALETTE["red"],
        PALETTE["slate"],
    ]
    colors = [palette[idx % len(palette)] for idx in range(len(names))]

    fig, ax = plt.subplots(figsize=(7.4, 3.0))
    bars = ax.barh(range(len(names)), values, color=colors)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Rows")
    ax.set_title("Downstream Text2Cypher failure taxonomy")
    style_axis(ax, grid_axis="x")
    for bar, value in zip(bars, values, strict=True):
        ax.text(
            bar.get_width() + max(values) * 0.015,
            bar.get_y() + bar.get_height() / 2,
            f"{value} ({value / incorrect:.1%})",
            va="center",
            fontsize=8,
        )
    ax.set_xlim(0, max(values) * 1.22 if values else 1)
    fig.tight_layout()
    fig.savefig(output)
    plt.close(fig)


def _short_category(label: str) -> str:
    return {
        "boolean_existence": "Boolean",
        "complex_aggregation": "Complex agg.",
        "complex_retrieval": "Complex ret.",
        "negation_difference": "Negation",
        "path_temporal": "Path/temp.",
        "ranking_topk": "Ranking",
        "simple_aggregation": "Simple agg.",
        "simple_retrieval": "Simple ret.",
    }.get(label, label.replace("_", " "))


if __name__ == "__main__":
    main()
