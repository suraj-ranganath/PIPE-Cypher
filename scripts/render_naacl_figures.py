#!/usr/bin/env python3
"""Data figures for the NAACL 2027 paper (vector PDFs, one shared style).

Reads completed v3 artifacts only:
  - artifacts/naacl_results/v3_results.json (downstream per model and tier,
    curated-benchmark rank agreement)
  - artifacts/refresh_v3/m1_rename_transfer_to/misestimate/*/misestimate_summary.json
    (accuracy against stale vs. refreshed references after the rename)

Writes to paper_naacl2027_industry/figures/:
  curated_agreement.pdf   generated vs. curated accuracy, three public graphs
  tier_accuracy.pdf       zero-shot projected EX by calibrated tier, all items
  refresh_inflation.pdf   stale vs. refreshed accuracy after renaming TRANSFER_TO
and a CSV of every plotted number next to each PDF.

Example:
  python scripts/render_naacl_figures.py
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

MODELS = {
    "glm53_flash": "GLM-5.3-Flash",
    "gpt6_luna": "gpt-6-luna",
    "gemma4_26b_a4b": "Gemma-4-26B",
    "gpt_oss_20b": "gpt-oss-20b",
    "mistral_small32_24b": "Mistral-Small-24B",
    "qwen3_coder_30b_a3b": "Qwen3-Coder-30B",
    "phi4": "Phi-4",
    "qwen35_9b": "Qwen3.5-9B",
    "llama31_8b": "Llama-3.1-8B",
    "gemma3_12b": "Gemma-3-12B",
    "gemma3_4b": "Gemma-3-4B",
}
GENERATOR, FRONTIER = "glm53_flash", "gpt6_luna"

# Okabe-Ito hues; neutrals biased slightly cool to match the pipeline figure.
BLUE, ORANGE, VERMILION = "#0072B2", "#E69F00", "#D55E00"
INK, MUTED, FAINT, GRID = "#1D2633", "#9AA3AE", "#C9CFD6", "#E7EAEE"

COLUMN_IN = 3.03  # ACL two-column width


def style() -> None:
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Helvetica", "Arial", "TeX Gyre Heros", "DejaVu Sans"],
        "font.size": 7,
        "axes.titlesize": 7,
        "axes.labelsize": 7,
        "xtick.labelsize": 6.5,
        "ytick.labelsize": 6.5,
        "legend.fontsize": 6.5,
        "axes.linewidth": 0.5,
        "axes.edgecolor": INK,
        "axes.labelcolor": INK,
        "xtick.color": INK,
        "ytick.color": INK,
        "xtick.major.width": 0.5,
        "ytick.major.width": 0.5,
        "xtick.major.size": 2.5,
        "ytick.major.size": 2.5,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "pdf.fonttype": 42,
        "savefig.dpi": 300,
    })


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with path.with_suffix(".csv").open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def curated_agreement(results: dict, out: Path) -> None:
    graphs = [("recommendations", "Recommendations"), ("northwind", "Northwind"), ("fincen", "FinCEN")]
    tau = {
        g: results["rank_agreement"][g]["analysis"]["metrics"]["projected_execution_accuracy"]
        for g, _ in graphs
    }
    fig, axes = plt.subplots(1, 3, figsize=(COLUMN_IN, 1.24))
    rows = []
    for ax, (g, title) in zip(axes, graphs):
        pipe, anchor = results["rank_agreement"][g]["pipe"], results["rank_agreement"][g]["anchor"]
        for slug in MODELS:
            x, y = anchor[slug]["projected"], pipe[slug]["projected"]
            rows.append([g, slug, round(x, 4), round(y, 4)])
            if slug == GENERATOR:
                ax.scatter(x, y, s=16, marker="s", color=BLUE, edgecolor="white", linewidth=0.5, zorder=3)
            elif slug == FRONTIER:
                ax.scatter(x, y, s=18, marker="D", color=ORANGE, edgecolor="white", linewidth=0.5, zorder=3)
            else:
                ax.scatter(x, y, s=11, color=MUTED, edgecolor="white", linewidth=0.4, zorder=2)
        t = tau[g].get("kendall_tau_b", tau[g].get("kendall_tau"))
        ax.set_title(title, pad=2, color=INK)
        ax.text(0.04, 0.97, rf"$\tau$ = {t:.2f}", transform=ax.transAxes, ha="left", va="top", fontsize=6.5, color=INK)
        ax.set_xlim(0, 0.65)
        ax.set_ylim(0, 1.0)
        ax.set_xticks([0, 0.3, 0.6])
        ax.set_yticks([0, 0.5, 1.0])
        ax.grid(True, color=GRID, linewidth=0.4)
        ax.set_axisbelow(True)
        if ax is not axes[0]:
            ax.set_yticklabels([])
    axes[0].set_ylabel("Generated items")
    axes[1].set_xlabel("Curated Text2Cypher-2024 rows (projected EX)", labelpad=1.5)
    handles = [
        Line2D([], [], marker="s", linestyle="", color=BLUE, markersize=3.6, label="GLM (generator)"),
        Line2D([], [], marker="D", linestyle="", color=ORANGE, markersize=3.4, label="gpt-6-luna"),
        Line2D([], [], marker="o", linestyle="", color=MUTED, markersize=3.2, label="9 other models"),
    ]
    fig.legend(handles=handles, loc="lower center", ncol=3, frameon=False, bbox_to_anchor=(0.54, -0.07),
               handletextpad=0.2, columnspacing=1.0)
    fig.subplots_adjust(left=0.13, right=0.99, top=0.88, bottom=0.36, wspace=0.12)
    fig.savefig(out)
    write_csv(out, ["graph", "model", "curated_projected_ex", "generated_projected_ex"], rows)
    plt.close(fig)


def tier_accuracy(results: dict, out: Path) -> None:
    per_model = results["downstream"]["zero_all"]["per_model"]
    tiers = ["easy", "medium", "hard"]
    xs = [0, 1, 2]
    fig, ax = plt.subplots(figsize=(COLUMN_IN, 1.38))
    rows = []
    series = {slug: [per_model[slug]["by_tier"][t]["projected"] for t in tiers] for slug in MODELS}
    for slug, ys in series.items():
        rows.append([slug] + [round(y, 4) for y in ys])
        if slug in (GENERATOR, FRONTIER):
            continue
        ax.plot(xs, ys, color=FAINT, linewidth=0.8, zorder=1, solid_capstyle="round")
    med = [statistics.median(series[s][i] for s in series) for i in range(3)]
    rows.append(["median"] + [round(y, 4) for y in med])
    ax.plot(xs, series[GENERATOR], color=BLUE, linewidth=1.4, marker="s", markersize=3, zorder=3)
    ax.plot(xs, series[FRONTIER], color=ORANGE, linewidth=1.4, marker="D", markersize=3, zorder=3)
    ax.plot(xs, med, color=INK, linewidth=2.0, marker="o", markersize=3.4, zorder=4)
    for i, v in enumerate(med[:2]):
        ax.annotate(f"{v:.2f}", (xs[i], v), xytext=(0, -5), textcoords="offset points", fontsize=6.3,
                    color=INK, va="top", ha="center", fontweight="bold",
                    bbox=dict(boxstyle="square,pad=0.08", facecolor="white", edgecolor="none"))
    ax.set_xticks(xs)
    ax.set_xticklabels(["easy (1,065)", "medium (1,104)", "hard (869)"])
    ax.set_xlim(-0.15, 2.95)
    ax.set_ylim(0, 1.0)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_ylabel("Projected EX (zero-shot)")
    ax.grid(True, axis="y", color=GRID, linewidth=0.4)
    ax.set_axisbelow(True)
    # Right-edge labels for the highlighted series.
    ax.text(2.08, series[GENERATOR][2] - 0.035, "GLM (generator)", color=BLUE, fontsize=6.3, va="center")
    ax.text(2.08, series[FRONTIER][2] + 0.04, "gpt-6-luna", color=ORANGE, fontsize=6.3, va="center")
    ax.text(2.08, med[2] + 0.005, f"median of 11 ({med[2]:.2f})", color=INK, fontsize=6.3, va="center",
            fontweight="bold")
    ax.text(2.08, 0.06, "9 other models", color=MUTED, fontsize=6.3, va="center")
    fig.subplots_adjust(left=0.14, right=0.99, top=0.97, bottom=0.2)
    fig.savefig(out)
    write_csv(out, ["model", "easy", "medium", "hard"], rows)
    plt.close(fig)


def refresh_inflation(refresh_dir: Path, out: Path) -> None:
    data = {}
    for slug in MODELS:
        summary = json.loads((refresh_dir / slug / "misestimate_summary.json").read_text())
        paired = summary["paired"]
        data[slug] = (paired["refreshed_accuracy"], paired["stale_accuracy"], paired["n"])
    order = sorted(data, key=lambda s: data[s][1])
    fig, ax = plt.subplots(figsize=(COLUMN_IN, 1.55))
    rows = []
    for i, slug in enumerate(order):
        fresh, stale, n = data[slug]
        rows.append([slug, round(fresh, 4), round(stale, 4), round(100 * (stale - fresh), 1), n])
        ax.plot([fresh, stale], [i, i], color=FAINT, linewidth=2.2, solid_capstyle="round", zorder=1)
        ax.scatter(fresh, i, s=14, color=INK, zorder=3)
        ax.scatter(stale, i, s=14, facecolor="white", edgecolor=VERMILION, linewidth=1.0, zorder=3)
        ax.text(stale + 0.012, i, f"+{int(100 * (stale - fresh) + 0.5)}", va="center", fontsize=6.2, color=VERMILION)
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels([MODELS[s] for s in order])
    for label, slug in zip(ax.get_yticklabels(), order):
        if slug == GENERATOR:
            label.set_color(BLUE)
        elif slug == FRONTIER:
            label.set_color(ORANGE)
    ax.set_xlim(0, 0.66)
    ax.set_ylim(-0.6, len(order) - 0.4)
    ax.set_xticks([0, 0.2, 0.4, 0.6])
    ax.set_xlabel("Projected EX on FinBench after the rename", labelpad=1.5)
    ax.grid(True, axis="x", color=GRID, linewidth=0.4)
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", length=0, pad=2)
    ax.spines["left"].set_visible(False)
    handles = [
        Line2D([], [], marker="o", linestyle="", color=INK, markersize=3.6, label="refreshed references"),
        Line2D([], [], marker="o", linestyle="", markerfacecolor="white", markeredgecolor=VERMILION,
               markeredgewidth=1.0, markersize=3.8, label="stale references (+pts)"),
    ]
    fig.legend(handles=handles, loc="upper center", ncol=2, frameon=False, bbox_to_anchor=(0.6, 1.0),
               handletextpad=0.2, columnspacing=1.2)
    fig.subplots_adjust(left=0.27, right=0.98, top=0.88, bottom=0.2)
    fig.savefig(out)
    write_csv(out, ["model", "refreshed_accuracy", "stale_accuracy", "inflation_pp", "n_items"], rows)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default="artifacts/naacl_results/v3_results.json")
    ap.add_argument("--refresh-dir", default="artifacts/refresh_v3/m1_rename_transfer_to/misestimate")
    ap.add_argument("--out-dir", default="paper_naacl2027_industry/figures")
    args = ap.parse_args()
    style()
    results = json.loads(Path(args.results).read_text())
    out = Path(args.out_dir)
    curated_agreement(results, out / "curated_agreement.pdf")
    tier_accuracy(results, out / "tier_accuracy.pdf")
    refresh_inflation(Path(args.refresh_dir), out / "refresh_inflation.pdf")
    print("wrote", ", ".join(str(out / n) for n in ("curated_agreement.pdf", "tier_accuracy.pdf", "refresh_inflation.pdf")))


if __name__ == "__main__":
    main()
