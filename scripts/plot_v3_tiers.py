#!/usr/bin/env python3
"""Figure: zero-shot projected EX by difficulty tier on all v3 items, per graph.

Reads the export (tiers) and each model's zero-shot evaluation on all items, and
draws one slope chart per graph: thin gray lines for every model, the generator
(GLM) and the closed reference (gpt-6-luna) highlighted, and the median across
models in ink. Writes a vector PDF and the plotted numbers as CSV.

Example:
  python scripts/plot_v3_tiers.py --export artifacts/benchmarks/naacl_v3_full \
      --eval-prefix naacl_v3_all --output paper_naacl2027_industry/figures/tier_accuracy.pdf
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

MODELS = [
    "glm53_flash", "qwen35_9b", "llama31_8b", "gemma3_4b", "gemma3_12b", "gemma4_26b_a4b",
    "phi4", "mistral_small32_24b", "gpt_oss_20b", "qwen3_coder_30b_a3b", "gpt6_luna",
]
TIERS = ["easy", "medium", "hard"]
HIGHLIGHT = {"glm53_flash": ("GLM-5.3-Flash (generator)", "#2a78d6"), "gpt6_luna": ("gpt-6-luna", "#eb6834")}
INK, MUTED, GRID = "#0b0b0b", "#b9b8b2", "#e6e5e0"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export", required=True)
    ap.add_argument("--eval-prefix", required=True)
    ap.add_argument("--evaluations-root", default="artifacts/evaluations")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    items = {}
    for line in (Path(args.export) / "all.jsonl").open():
        row = json.loads(line)
        items[row["id"]] = (row["graph_profile"], row["difficulty"])
    graphs = ["finbench", "snb"]
    scores: dict[str, dict[tuple[str, str], float]] = {}
    for slug in MODELS:
        path = Path(args.evaluations_root) / f"{args.eval_prefix}_downstream_{slug}" / "zero_shot_evaluation.jsonl"
        if not path.exists():
            continue
        acc: dict[tuple[str, str], list[float]] = {}
        for line in path.open():
            row = json.loads(line)
            key = items.get(str(row["id"]))
            if key:
                acc.setdefault(key, []).append(float(row.get("projected_execution_accuracy") or 0.0))
        scores[slug] = {k: sum(v) / len(v) for k, v in acc.items()}
    missing = [m for m in MODELS if m not in scores]
    if missing:
        print("missing evaluations:", missing)

    plt.rcParams.update({"font.family": "serif", "font.size": 7.5, "axes.linewidth": 0.6})
    fig, axes = plt.subplots(1, 2, figsize=(3.3, 1.85), sharey=True)
    out_rows = []
    for ax, graph in zip(axes, graphs):
        xs = list(range(len(TIERS)))
        for slug, s in scores.items():
            ys = [s.get((graph, t)) for t in TIERS]
            if slug in HIGHLIGHT:
                continue
            ax.plot(xs, ys, color=MUTED, linewidth=0.8, zorder=1)
        med = [statistics.median(s[(graph, t)] for s in scores.values() if (graph, t) in s) for t in TIERS]
        ax.plot(xs, med, color=INK, linewidth=2.0, marker="o", markersize=3.2, zorder=3)
        for slug, (label, color) in HIGHLIGHT.items():
            if slug in scores:
                ys = [scores[slug].get((graph, t)) for t in TIERS]
                ax.plot(xs, ys, color=color, linewidth=1.6, marker="o", markersize=3.0, zorder=2,
                        markeredgecolor="white", markeredgewidth=0.6)
        for slug, s in scores.items():
            for t in TIERS:
                out_rows.append({"graph": graph, "model": slug, "tier": t, "projected_ex": round(s.get((graph, t), float("nan")), 4)})
        for t, m in zip(TIERS, med):
            out_rows.append({"graph": graph, "model": "median", "tier": t, "projected_ex": round(m, 4)})
        ax.set_xticks(xs, ["easy", "med.", "hard"])
        ax.set_title("FinBench" if graph == "finbench" else "SNB", fontsize=8, pad=3)
        ax.set_ylim(0, 1)
        ax.set_xlim(-0.25, 2.25)
        ax.yaxis.grid(True, color=GRID, linewidth=0.5)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.tick_params(length=2, width=0.5)
    axes[0].set_ylabel("Projected EX (zero-shot)")
    handles = [plt.Line2D([], [], color=c, linewidth=1.6, marker="o", markersize=3) for _, c in HIGHLIGHT.values()]
    handles += [plt.Line2D([], [], color=INK, linewidth=2.0, marker="o", markersize=3), plt.Line2D([], [], color=MUTED, linewidth=0.8)]
    labels = [l for l, _ in HIGHLIGHT.values()] + ["median of 11 models", "other models"]
    fig.legend(handles, labels, loc="lower center", ncol=2, frameon=False, fontsize=6.5, bbox_to_anchor=(0.5, -0.02), handlelength=1.6, columnspacing=1.0)
    fig.tight_layout(rect=(0, 0.17, 1, 1), w_pad=0.6)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, bbox_inches="tight")
    fig.savefig(out.with_suffix(".png"), dpi=220, bbox_inches="tight")
    with out.with_suffix(".csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["graph", "model", "tier", "projected_ex"])
        writer.writeheader()
        writer.writerows(out_rows)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
