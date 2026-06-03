from __future__ import annotations

from typing import Any


PALETTE = {
    "blue": "#2F5F98",
    "teal": "#00856F",
    "gold": "#B87A00",
    "red": "#B5524A",
    "purple": "#6B5CA5",
    "ink": "#243040",
    "slate": "#5A6778",
    "light_slate": "#AAB4C0",
    "pale_blue": "#EAF1F8",
    "pale_teal": "#E8F5F1",
    "pale_gold": "#FBF2DA",
    "pale_red": "#F8EAE8",
    "pale_purple": "#F0EDF8",
    "pale_gray": "#F3F5F7",
    "paper": "#FFFFFF",
}

# Backward-compatible aliases used by older render scripts.
PALETTE["orange"] = PALETTE["gold"]
PALETTE["green"] = PALETTE["teal"]
PALETTE["violet"] = PALETTE["purple"]

QUALITATIVE_COLORS = [
    PALETTE["blue"],
    PALETTE["gold"],
    PALETTE["teal"],
    PALETTE["purple"],
    PALETTE["red"],
    PALETTE["slate"],
]

GRAPH_COLORS = {
    "finbench": PALETTE["blue"],
    "snb": PALETTE["gold"],
}

METRIC_COLORS = {
    "execution_accuracy": PALETTE["blue"],
    "execution_success": PALETTE["gold"],
    "schema_valid": PALETTE["teal"],
    "judge_pass": PALETTE["purple"],
}


def apply_paper_style(plt: Any) -> None:
    """Apply the PIPE-Cypher publication style to matplotlib figures."""

    plt.rcParams.update(
        {
            "figure.facecolor": PALETTE["paper"],
            "axes.facecolor": PALETTE["paper"],
            "axes.edgecolor": PALETTE["slate"],
            "axes.linewidth": 0.7,
            "axes.titlesize": 10,
            "axes.titleweight": "semibold",
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
            "legend.frameon": False,
        }
    )


def style_axis(axis: Any, *, grid_axis: str = "y") -> None:
    axis.grid(axis=grid_axis, alpha=0.75)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.spines["left"].set_color(PALETTE["slate"])
    axis.spines["bottom"].set_color(PALETTE["slate"])
    axis.tick_params(colors=PALETTE["ink"], labelcolor=PALETTE["ink"])
    axis.xaxis.label.set_color(PALETTE["ink"])
    axis.yaxis.label.set_color(PALETTE["ink"])
    axis.title.set_color(PALETTE["ink"])


def categorical_colors(count: int, *, offset: int = 0) -> list[str]:
    """Return a stable color cycle for categorical bars and stacks."""

    if count <= 0:
        return []
    return [QUALITATIVE_COLORS[(idx + offset) % len(QUALITATIVE_COLORS)] for idx in range(count)]


def sequential_cmap(name: str = "pipecypher_sequential") -> Any:
    """Return the shared blue-green sequential map for heatmaps."""

    from matplotlib.colors import LinearSegmentedColormap

    return LinearSegmentedColormap.from_list(
        name,
        [
            PALETTE["pale_gray"],
            PALETTE["pale_blue"],
            "#B7D1E4",
            PALETTE["teal"],
            PALETTE["blue"],
        ],
    )


def quality_cmap(name: str = "pipecypher_quality") -> Any:
    """Return a red-gold-teal-blue map for validation quality rates."""

    from matplotlib.colors import LinearSegmentedColormap

    return LinearSegmentedColormap.from_list(
        name,
        [
            PALETTE["pale_red"],
            PALETTE["pale_gold"],
            PALETTE["pale_teal"],
            PALETTE["blue"],
        ],
    )
