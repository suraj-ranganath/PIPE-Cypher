#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.ablation_suite import variant_label
from pipecypher.paper_style import (
    GRAPH_COLORS,
    METRIC_COLORS,
    PALETTE,
    apply_paper_style,
    categorical_colors,
    sequential_cmap,
    style_axis,
)


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
    parser.add_argument(
        "--fewshot-control-summary",
        default="experiments/snapshots/20260603_downstream_model_transfer/fewshot_control_summary.json",
    )
    parser.add_argument(
        "--ablation-comparison",
        default="experiments/snapshots/ablation_suite_comparison.json",
    )
    parser.add_argument(
        "--icij-onboarding",
        default="experiments/snapshots/20260602_icij_target100_schema_templates_v3/onboarding_summary.json",
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
    fewshot_control_summary = json.loads(
        Path(args.fewshot_control_summary).read_text(encoding="utf-8")
    )
    ablation_comparison = json.loads(Path(args.ablation_comparison).read_text(encoding="utf-8"))
    icij_onboarding = json.loads(Path(args.icij_onboarding).read_text(encoding="utf-8"))

    render_diversity_figure(diversity_report, out / "diversity_diagnostics.pdf", plt)
    render_query_signature_concentration_figure(
        diversity_report,
        out / "query_signature_concentration.pdf",
        plt,
    )
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
    render_downstream_fewshot_control_figure(
        fewshot_control_summary,
        out / "downstream_fewshot_controls.pdf",
        plt,
    )
    render_ablation_comparison_figure(
        ablation_comparison,
        out / "ablation_suite_comparison.pdf",
        plt,
    )
    render_icij_onboarding_figure(
        icij_onboarding,
        out / "icij_onboarding_audit.pdf",
        plt,
    )
    print(f"wrote {out / 'diversity_diagnostics.pdf'}")
    print(f"wrote {out / 'query_signature_concentration.pdf'}")
    print(f"wrote {out / 'full_export_distribution.pdf'}")
    print(f"wrote {out / 'downstream_breakdown.pdf'}")
    print(f"wrote {out / 'downstream_uncertainty.pdf'}")
    print(f"wrote {out / 'failure_taxonomy.pdf'}")
    if failure_taxonomy.get("empty_result_diagnostic_counts"):
        print(f"wrote {out / 'empty_result_diagnostics.pdf'}")
    print(f"wrote {out / 'downstream_error_taxonomy.pdf'}")
    print(f"wrote {out / 'downstream_fewshot_controls.pdf'}")
    print(f"wrote {out / 'ablation_suite_comparison.pdf'}")
    print(f"wrote {out / 'icij_onboarding_audit.pdf'}")


def render_diversity_figure(report: dict, output: Path, plt) -> None:
    index = report.get("pipe_diversity_index", {})
    components = index.get("components", {})
    values = {
        "PIPE-Diversity\nindex": index.get("score", 0.0),
        "Lexical\nvariety": components.get("lexical", 0.0),
        "Query-template\nvariety": components.get("query_template", 0.0),
        "Structural\ncoverage": components.get("structural", 0.0),
        "Schema\ncoverage": components.get("schema", 0.0),
        "Value\nvariety": components.get("value", 0.0),
        "Balance\ncoverage": components.get("balance", 0.0),
    }
    fig, ax = plt.subplots(figsize=(7.4, 3.2))
    bars = ax.bar(
        range(len(values)),
        list(values.values()),
        color=categorical_colors(len(values)),
    )
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Normalized score")
    ax.set_title("Full benchmark diversity components")
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


def render_query_signature_concentration_figure(report: dict, output: Path, plt) -> None:
    rows = report.get("query_templates", {}).get("top_signatures", [])[:8]
    labels = [str(row.get("signature_id", "")) for row in rows]
    shares = [float(row.get("share", 0.0)) for row in rows]
    fig, ax = plt.subplots(figsize=(6.8, 3.0))
    positions = list(range(len(labels)))
    bars = ax.barh(positions, shares, color=PALETTE["gold"])
    ax.set_yticks(positions)
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlim(0, max(shares) * 1.18 if shares else 1)
    ax.set_xlabel("Share of full export")
    ax.set_title("Top canonical query-template concentration")
    style_axis(ax, grid_axis="x")
    for bar, share in zip(bars, shares, strict=True):
        ax.text(
            bar.get_width() + 0.002,
            bar.get_y() + bar.get_height() / 2,
            f"{share:.3f}",
            va="center",
            fontsize=8,
        )
    fig.tight_layout()
    fig.savefig(output)
    plt.close(fig)


def render_downstream_fewshot_control_figure(report: dict, output: Path, plt) -> None:
    models = report.get("models", [])
    mode_labels = ["Zero", "Ordered", "No-sig", "Random mean"]
    matrix = []
    y_labels = []
    for model in models:
        y_labels.append(_short_model_label(str(model.get("model", ""))))
        matrix.append(
            [
                float(model.get("zero_shot", {}).get("execution_accuracy", 0.0)),
                float(
                    model.get("controls", {})
                    .get("ordered", {})
                    .get("execution_accuracy", 0.0)
                ),
                float(
                    model.get("controls", {})
                    .get("scored_no_signature", {})
                    .get("execution_accuracy", 0.0)
                ),
                float(
                    model.get("random", {})
                    .get("mean", {})
                    .get("execution_accuracy", 0.0)
                ),
            ]
        )

    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    image = ax.imshow(matrix, cmap=sequential_cmap(), vmin=0.0, vmax=1.0, aspect="auto")
    ax.set_title("Downstream execution accuracy under few-shot controls")
    ax.set_xticks(range(len(mode_labels)))
    ax.set_xticklabels(mode_labels)
    ax.set_yticks(range(len(y_labels)))
    ax.set_yticklabels(y_labels, fontsize=7)
    ax.tick_params(axis="both", length=0)
    for row_idx, row in enumerate(matrix):
        for col_idx, value in enumerate(row):
            ax.text(
                col_idx,
                row_idx,
                f"{value:.2f}",
                ha="center",
                va="center",
                fontsize=6.5,
                color=PALETTE["paper"] if value >= 0.55 else PALETTE["ink"],
            )
    colorbar = fig.colorbar(image, ax=ax, fraction=0.026, pad=0.02)
    colorbar.set_label("Execution accuracy")
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
        color=[PALETTE["teal"], PALETTE["purple"], PALETTE["red"]][: len(diff_labels)],
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
    colors = categorical_colors(len(names))

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
    colors = categorical_colors(len(values))

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
    colors = categorical_colors(len(names), offset=1)

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


def render_ablation_comparison_figure(report: dict, output: Path, plt) -> None:
    cells = [
        cell
        for cell in report.get("cells", [])
        if str(cell.get("variant")) != "unconstrained_local_llm"
    ]
    graphs = ["finbench", "snb"]
    variants = [
        "reverse_only",
        "validators_repair",
        "ablation_retrieval_topk_0",
        "ablation_rewrite_false",
        "ablation_judge_false",
        "full_pipe_cypher",
    ]
    by_cell = {(cell.get("graph"), cell.get("variant")): cell for cell in cells}
    x_positions = list(range(len(variants)))
    width = 0.34

    fig, axes = plt.subplots(2, 1, figsize=(9.2, 5.3), sharex=True)
    for graph_idx, graph in enumerate(graphs):
        offsets = [x + (graph_idx - 0.5) * width for x in x_positions]
        acceptance = [
            float(by_cell.get((graph, variant), {}).get("accept_rate", {}).get("mean", 0.0))
            for variant in variants
        ]
        target_coverage = [
            float(by_cell.get((graph, variant), {}).get("target_coverage", {}).get("mean", 0.0))
            for variant in variants
        ]
        axes[0].bar(
            offsets,
            acceptance,
            width,
            color=GRAPH_COLORS.get(graph, PALETTE["slate"]),
            label=_graph_name(graph),
        )
        axes[1].bar(
            offsets,
            target_coverage,
            width,
            color=GRAPH_COLORS.get(graph, PALETTE["slate"]),
            label=_graph_name(graph),
        )

    axes[0].set_ylim(0.9, 1.01)
    axes[0].set_ylabel("Acceptance mean")
    axes[0].set_title("Three-suite ablation stability")
    axes[0].legend(frameon=False, ncols=2, loc="lower right")
    style_axis(axes[0], grid_axis="y")
    axes[1].set_ylim(0.9, 1.01)
    axes[1].set_ylabel("Target coverage mean")
    axes[1].set_xticks(x_positions)
    axes[1].set_xticklabels([variant_label(variant) for variant in variants], rotation=25, ha="right")
    style_axis(axes[1], grid_axis="y")
    fig.text(
        0.01,
        0.01,
        "Unconstrained LLM omitted: reported separately as a stress baseline with attempt accounting.",
        fontsize=7.5,
        color=PALETTE["slate"],
    )
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(output)
    plt.close(fig)


def render_icij_onboarding_figure(summary: dict, output: Path, plt) -> None:
    coverage = summary.get("category_coverage", {})
    categories = list(summary.get("expected_categories", []))
    accepted = [int(coverage.get(category, {}).get("accepted", 0)) for category in categories]
    target = int(summary.get("target_per_category", 0))
    failure_counts: dict[str, int] = {}
    for counts in summary.get("failure_by_category", {}).values():
        for reason, count in counts.items():
            failure_counts[str(reason)] = failure_counts.get(str(reason), 0) + int(count)
    failure_items = sorted(failure_counts.items(), key=lambda item: (-item[1], item[0]))

    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.4), gridspec_kw={"width_ratios": [2.1, 1]})
    x_positions = list(range(len(categories)))
    axes[0].bar(x_positions, accepted, color=PALETTE["blue"])
    axes[0].axhline(target, color=PALETTE["red"], linestyle="--", linewidth=1.0, label="Target")
    axes[0].set_title("ICIJ accepted examples by category")
    axes[0].set_ylabel("Accepted examples")
    axes[0].set_ylim(0, max(target * 1.18, max(accepted) * 1.12 if accepted else 1))
    axes[0].set_xticks(x_positions)
    axes[0].set_xticklabels([_short_category(label) for label in categories], rotation=32, ha="right", fontsize=8)
    axes[0].legend(frameon=False, loc="upper left")
    style_axis(axes[0], grid_axis="y")
    for idx, value in enumerate(accepted):
        axes[0].text(idx, value + max(target * 0.025, 1), str(value), ha="center", va="bottom", fontsize=7)

    names = [name.replace("slot bindings ", "bindings\n") for name, _ in failure_items]
    values = [value for _, value in failure_items]
    failure_palette = categorical_colors(max(len(values), 1), offset=1)
    axes[1].barh(
        range(len(values)),
        values,
        color=[failure_palette[idx % len(failure_palette)] for idx in range(len(values))],
    )
    axes[1].set_yticks(range(len(values)))
    axes[1].set_yticklabels(names, fontsize=8)
    axes[1].invert_yaxis()
    axes[1].set_xlabel("Rejected")
    axes[1].set_title("Remaining sparse-binding failures")
    style_axis(axes[1], grid_axis="x")
    for idx, value in enumerate(values):
        axes[1].text(value + max(values) * 0.03, idx, str(value), va="center", fontsize=8)
    axes[1].set_xlim(0, max(values) * 1.22 if values else 1)
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


def _short_model_label(label: str) -> str:
    replacements = {
        "aigentx/Llama-3.1-8B Cypher LoRA": "aigentx Cypher LoRA",
        "aigentx/Llama-3.1-8B Cypher mixed LoRA": "aigentx mixed LoRA",
        "Azzedde/llama3.1-8b-text2cypher": "Azzedde T2C",
        "Gemma-2-9B-IT": "Gemma-2-9B-IT",
        "neo4j/Gemma-2-9B Text2Cypher LoRA": "Gemma-2 T2C LoRA",
        "neo4j/Gemma-3-4B Text2Cypher": "Gemma-3 T2C",
        "projectwilsen/Llama-3.1-8B Text2Cypher LoRA": "projectwilsen LoRA",
        "Qwen2.5-Coder-7B-Instruct": "Qwen2.5-Coder",
        "Qwen3.5-9B": "Qwen3.5-9B",
        "Saiprasanth15/Llama-3.1-8B Text2Cypher LoRA": "Saiprasanth LoRA",
        "ragraph-ai/stable-cypher-instruct-3b": "stable-cypher-3B",
        "tomasonjo/text2cypher-demo-16bit": "tomasonjo T2C",
    }
    return replacements.get(label, label[:34])


def _graph_name(graph: str) -> str:
    return {"finbench": "FinBench", "snb": "SNB"}.get(graph, graph)


if __name__ == "__main__":
    main()
