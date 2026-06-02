from __future__ import annotations

from typing import Any


PALETTE = {
    "blue": "#2563eb",
    "orange": "#f97316",
    "green": "#10b981",
    "violet": "#8b5cf6",
    "red": "#ef4444",
    "ink": "#0f172a",
    "slate": "#64748b",
    "light_slate": "#cbd5e1",
    "paper": "#ffffff",
}

GRAPH_COLORS = {
    "finbench": PALETTE["blue"],
    "snb": PALETTE["orange"],
}

METRIC_COLORS = {
    "execution_accuracy": PALETTE["blue"],
    "execution_success": PALETTE["orange"],
    "schema_valid": PALETTE["green"],
    "judge_pass": PALETTE["violet"],
}


def apply_paper_style(plt: Any) -> None:
    """Apply a consistent, compact style to appendix figures."""

    plt.rcParams.update(
        {
            "figure.facecolor": PALETTE["paper"],
            "axes.facecolor": PALETTE["paper"],
            "axes.edgecolor": PALETTE["slate"],
            "axes.linewidth": 0.7,
            "axes.titlesize": 10,
            "axes.labelsize": 9,
            "font.size": 9,
            "legend.fontsize": 8,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "grid.color": PALETTE["light_slate"],
            "grid.linewidth": 0.55,
            "grid.linestyle": ":",
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "savefig.bbox": "tight",
            "savefig.pad_inches": 0.04,
        }
    )


def style_axis(axis: Any, *, grid_axis: str = "y") -> None:
    axis.grid(axis=grid_axis, alpha=0.75)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
