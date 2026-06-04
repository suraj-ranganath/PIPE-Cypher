#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.paper_style import (
    ERROR_COLORS,
    PALETTE,
    apply_paper_style,
    categorical_colors,
    sequential_cmap,
    style_axis,
)
from pipecypher.strategy_analysis import (
    ERROR_BUCKET_ORDER,
    load_jsonl,
    render_strategy_table,
    strategy_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render PIPE-RDF-inspired strategy diagnostics for PIPE-Cypher."
    )
    parser.add_argument(
        "--benchmark",
        default="artifacts/benchmarks/20260604_live_full_qwen9b_reviewfix/all.jsonl",
    )
    parser.add_argument(
        "--evaluation",
        default=(
            "artifacts/evaluations/20260604_clean_downstream_qwen35_9b_zero_fewshot/"
            "zero_shot_evaluation.jsonl"
        ),
    )
    parser.add_argument(
        "--output-json",
        default=(
            "experiments/snapshots/20260604_clean_downstream_model_transfer/"
            "strategy_diagnostics.json"
        ),
    )
    parser.add_argument(
        "--output-tex",
        default="paper_emnlp2026_industry/tables_strategy_diagnostics.tex",
    )
    parser.add_argument(
        "--coverage-figure",
        default="paper_emnlp2026_industry/figures/strategy_coverage.pdf",
    )
    parser.add_argument(
        "--downstream-figure",
        default="paper_emnlp2026_industry/figures/strategy_downstream_errors.pdf",
    )
    args = parser.parse_args()

    report = strategy_report(load_jsonl(args.benchmark), load_jsonl(args.evaluation))

    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {output_json}")

    output_tex = Path(args.output_tex)
    output_tex.parent.mkdir(parents=True, exist_ok=True)
    output_tex.write_text(render_strategy_table(report), encoding="utf-8")
    print(f"wrote {output_tex}")

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    apply_paper_style(plt)
    render_strategy_coverage_figure(report, Path(args.coverage_figure), plt)
    print(f"wrote {args.coverage_figure}")
    render_strategy_downstream_error_figure(report, Path(args.downstream_figure), plt)
    print(f"wrote {args.downstream_figure}")


def render_strategy_coverage_figure(report: dict, output: Path, plt) -> None:
    categories = list(report.get("categories", []))
    strategies = list(report.get("strategies", []))
    rates = report.get("category_strategy_rates", {})
    matrix = [
        [float(rates.get(category, {}).get(strategy, 0.0)) for strategy in strategies]
        for category in categories
    ]

    fig, ax = plt.subplots(figsize=(9.2, 4.2))
    image = ax.imshow(matrix, vmin=0.0, vmax=1.0, cmap=sequential_cmap(), aspect="auto")
    ax.set_xticks(range(len(strategies)))
    ax.set_xticklabels([_strategy_label(strategy) for strategy in strategies], rotation=35, ha="right")
    ax.set_yticks(range(len(categories)))
    ax.set_yticklabels([_short_category(category) for category in categories])
    ax.set_title("Cypher strategy coverage by workload category")
    for row_idx, row in enumerate(matrix):
        for col_idx, value in enumerate(row):
            text_color = "white" if value >= 0.62 else PALETTE["ink"]
            ax.text(col_idx, row_idx, f"{value:.2f}", ha="center", va="center", fontsize=7, color=text_color)
    cbar = fig.colorbar(image, ax=ax, fraction=0.035, pad=0.02)
    cbar.set_label("Share of category examples")
    fig.tight_layout()
    fig.savefig(output)
    plt.close(fig)


def render_strategy_downstream_error_figure(report: dict, output: Path, plt) -> None:
    downstream = report.get("downstream_by_strategy", {})
    strategies = [
        strategy
        for strategy, data in sorted(
            downstream.items(),
            key=lambda item: (-int(item[1].get("examples", 0)), item[0]),
        )
    ]
    buckets = [bucket for bucket in ERROR_BUCKET_ORDER if any(downstream[s]["error_bucket_counts"].get(bucket, 0) for s in strategies)]
    fallback_colors = categorical_colors(len(buckets))

    fig, ax = plt.subplots(figsize=(8.8, 3.8))
    x_positions = list(range(len(strategies)))
    bottoms = [0] * len(strategies)
    for bucket in buckets:
        values = [int(downstream[strategy]["error_bucket_counts"].get(bucket, 0)) for strategy in strategies]
        ax.bar(
            x_positions,
            values,
            bottom=bottoms,
            color=ERROR_COLORS.get(bucket, fallback_colors[buckets.index(bucket)]),
            label=_bucket_label(bucket),
        )
        bottoms = [bottom + value for bottom, value in zip(bottoms, values, strict=True)]
    ax.set_ylabel("Held-out examples")
    ax.set_title("Downstream outcomes by gold Cypher strategy")
    ax.set_xticks(x_positions)
    ax.set_xticklabels([_strategy_label(strategy) for strategy in strategies], rotation=25, ha="right")
    ax.legend(frameon=False, ncols=3, loc="upper right")
    style_axis(ax, grid_axis="y")
    for idx, total in enumerate(bottoms):
        ax.text(idx, total + max(bottoms) * 0.02, str(total), ha="center", va="bottom", fontsize=7)
    ax.set_ylim(0, max(bottoms) * 1.18 if bottoms else 1)
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


def _strategy_label(strategy: str) -> str:
    return {
        "node_scan": "Node scan",
        "single_hop": "Single hop",
        "join_heavy": "Join-heavy",
        "aggregation": "Aggregation",
        "order_rank": "Order/rank",
        "negation": "Negation",
        "path": "Path",
        "optional": "Optional",
        "bounded_result": "Bounded",
    }.get(strategy, strategy.replace("_", " ").title())


def _bucket_label(bucket: str) -> str:
    return {
        "exact": "Exact",
        "answer_mismatch": "Answer mismatch",
        "execution_failed": "Exec. failed",
        "schema_invalid": "Schema invalid",
        "parse_invalid": "Parse invalid",
    }.get(bucket, bucket.replace("_", " ").title())


if __name__ == "__main__":
    main()
