#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.ablation_suite import (
    DEFAULT_GRAPHS,
    DEFAULT_PAPER_TARGET_PER_CATEGORY,
    DEFAULT_VARIANTS,
    audit_ablation_suite_for_paper,
    variant_label,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render an appendix-ready figure from a completed ablation suite summary."
    )
    parser.add_argument("--suite-summary", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--min-paper-target", type=int, default=DEFAULT_PAPER_TARGET_PER_CATEGORY)
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="Render non-paper-ready summaries for internal diagnostics only.",
    )
    args = parser.parse_args()

    summary = json.loads(Path(args.suite_summary).read_text(encoding="utf-8"))
    audit = audit_ablation_suite_for_paper(
        summary,
        min_target_per_category=args.min_paper_target,
    )
    if not audit["paper_ready"] and not args.allow_incomplete:
        failed = ", ".join(check["name"] for check in audit["failed_checks"])
        raise SystemExit(
            "refusing to render a paper-style ablation figure from a suite that is "
            f"not paper-ready; failed checks: {failed}. Use --allow-incomplete only "
            "for internal diagnostics"
        )

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    render_ablation_suite_figure(summary, output, plt)
    print(f"wrote {output}")


def render_ablation_suite_figure(summary: dict, output: Path, plt) -> None:
    graphs = [graph for graph in DEFAULT_GRAPHS if graph in summary.get("expected_graphs", [])]
    variants = [
        variant for variant in DEFAULT_VARIANTS if variant in summary.get("expected_variants", [])
    ]
    by_cell = {(run["graph"], run["variant"]): run for run in summary.get("runs", [])}
    x_positions = list(range(len(variants)))
    width = 0.34 if len(graphs) > 1 else 0.55
    palette = {"finbench": "#2563eb", "snb": "#f97316"}

    fig, axes = plt.subplots(2, 1, figsize=(9.2, 5.2), sharex=True)
    for graph_idx, graph in enumerate(graphs):
        offsets = [x + (graph_idx - (len(graphs) - 1) / 2) * width for x in x_positions]
        acceptance = [
            float(by_cell.get((graph, variant), {}).get("accept_rate", 0.0))
            for variant in variants
        ]
        target_share = [
            _target_share(by_cell.get((graph, variant), {}), summary)
            for variant in variants
        ]
        axes[0].bar(
            offsets,
            acceptance,
            width,
            label=_graph_label(graph),
            color=palette.get(graph, "#64748b"),
        )
        axes[1].bar(
            offsets,
            target_share,
            width,
            label=_graph_label(graph),
            color=palette.get(graph, "#64748b"),
        )

    axes[0].set_ylim(0, 1.05)
    axes[0].set_ylabel("Acceptance rate")
    axes[0].set_title(
        f"Target-{summary.get('target_per_category')} ablation yield by graph"
    )
    axes[0].grid(axis="y", linestyle=":", linewidth=0.6, alpha=0.7)
    axes[0].legend(frameon=False, ncols=max(1, len(graphs)), loc="upper right")

    axes[1].set_ylim(0, 1.05)
    axes[1].set_ylabel("Categories at target")
    axes[1].grid(axis="y", linestyle=":", linewidth=0.6, alpha=0.7)
    axes[1].set_xticks(x_positions)
    axes[1].set_xticklabels([variant_label(variant) for variant in variants], rotation=25, ha="right")

    for axis in axes:
        for container in axis.containers:
            axis.bar_label(container, fmt="%.2f", fontsize=7, padding=2)

    fig.tight_layout()
    fig.savefig(output)
    plt.close(fig)


def _target_share(run: dict, summary: dict) -> float:
    category_count = max(int(summary.get("category_count", 0)), 1)
    return int(run.get("categories_at_target", 0)) / category_count


def _graph_label(graph: str) -> str:
    return {"finbench": "FinBench", "snb": "SNB"}.get(graph, graph)


if __name__ == "__main__":
    main()
