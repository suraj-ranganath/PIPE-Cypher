#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.experiments import compare_runs


DEFAULT_ABLATION_RUNS = [
    "artifacts/runs/20260601_182730_20260601_ablation5_finbench_unconstrained_local_llm_strict",
    "artifacts/runs/20260601_182553_20260601_ablation5_finbench_reverse_only",
    "artifacts/runs/20260601_182551_20260601_ablation5_finbench_validators_repair",
    "artifacts/runs/20260601_182245_20260601_ablation5_finbench_ablation_retrieval_topk_0",
    "artifacts/runs/20260601_182417_20260601_ablation5_finbench_ablation_rewrite_false",
    "artifacts/runs/20260601_182549_20260601_ablation5_finbench_ablation_judge_false",
    "artifacts/runs/20260601_182058_20260601_ablation5_finbench_full_pipe_cypher",
    "artifacts/runs/20260601_183657_20260601_ablation5_snb_unconstrained_local_llm",
    "artifacts/runs/20260601_183656_20260601_ablation5_snb_reverse_only",
    "artifacts/runs/20260601_183655_20260601_ablation5_snb_validators_repair",
    "artifacts/runs/20260601_183401_20260601_ablation5_snb_ablation_retrieval_topk_0",
    "artifacts/runs/20260601_183527_20260601_ablation5_snb_ablation_rewrite_false",
    "artifacts/runs/20260601_183653_20260601_ablation5_snb_ablation_judge_false",
    "artifacts/runs/20260601_183236_20260601_ablation5_snb_full_pipe_cypher",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Render appendix-ready PIPE-Cypher paper figures.")
    parser.add_argument("--diversity-report", required=True)
    parser.add_argument("--ablation-runs", nargs="*", default=DEFAULT_ABLATION_RUNS)
    parser.add_argument("--output-dir", default="paper_emnlp2026_industry/figures")
    args = parser.parse_args()

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    diversity_report = json.loads(Path(args.diversity_report).read_text(encoding="utf-8"))

    render_diversity_figure(diversity_report, out / "diversity_diagnostics.pdf", plt)
    render_ablation_figure(args.ablation_runs, out / "ablation_acceptance.pdf", plt)
    print(f"wrote {out / 'diversity_diagnostics.pdf'}")
    print(f"wrote {out / 'ablation_acceptance.pdf'}")


def render_diversity_figure(report: dict, output: Path, plt) -> None:
    values = {
        "Category\nbalance": report["distributions"]["category"]["normalized_entropy"],
        "Graph-category\nbalance": report["distributions"]["graph_category"]["normalized_entropy"],
        "Difficulty\nbalance": report["distributions"]["difficulty"]["normalized_entropy"],
        "Distinct-2\nquestions": report["question_text"]["distinct_2"],
        "Query-signature\nratio": report["query_templates"]["unique_signature_ratio"],
        "Label\ncoverage": report["schema_coverage"]["labels"]["coverage"],
        "Rel-type\ncoverage": report["schema_coverage"]["relationship_types"]["coverage"],
        "Property\ncoverage": report["schema_coverage"]["properties"]["coverage"],
    }
    fig, ax = plt.subplots(figsize=(8.2, 3.2))
    bars = ax.bar(range(len(values)), list(values.values()), color="#3b82f6")
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Normalized score")
    ax.set_title("Full benchmark diversity diagnostics")
    ax.set_xticks(range(len(values)))
    ax.set_xticklabels(list(values.keys()), rotation=0, ha="center", fontsize=8)
    ax.grid(axis="y", linestyle=":", linewidth=0.6, alpha=0.7)
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


def render_ablation_figure(run_paths: list[str], output: Path, plt) -> None:
    summaries = compare_runs(run_paths)
    variants = [
        "Unconstrained LLM",
        "Reverse-only",
        "Validators+repair",
        "No retrieval",
        "No rewrite",
        "No LLM judge",
        "Full PIPE-Cypher",
    ]
    graphs = ["FinBench", "SNB"]
    matrix = {variant: {graph: 0.0 for graph in graphs} for variant in variants}
    for summary in summaries:
        variant = _variant_label(str(summary.get("run", "")))
        graph = _graph_label(str(summary.get("run", "")))
        if variant in matrix and graph in matrix[variant]:
            matrix[variant][graph] = float(summary.get("accept_rate", 0.0))

    x_positions = range(len(variants))
    width = 0.36
    fig, ax = plt.subplots(figsize=(8.8, 3.4))
    finbench = [matrix[variant]["FinBench"] for variant in variants]
    snb = [matrix[variant]["SNB"] for variant in variants]
    ax.bar([x - width / 2 for x in x_positions], finbench, width, label="FinBench", color="#2563eb")
    ax.bar([x + width / 2 for x in x_positions], snb, width, label="SNB", color="#f97316")
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Acceptance rate")
    ax.set_title("Target-five ablation acceptance rates")
    ax.set_xticks(list(x_positions))
    ax.set_xticklabels(variants, rotation=24, ha="right", fontsize=8)
    ax.legend(frameon=False, ncols=2, loc="upper left")
    ax.grid(axis="y", linestyle=":", linewidth=0.6, alpha=0.7)
    fig.tight_layout()
    fig.savefig(output)
    plt.close(fig)


def _variant_label(run: str) -> str:
    labels = [
        ("unconstrained_local_llm", "Unconstrained LLM"),
        ("reverse_only", "Reverse-only"),
        ("validators_repair", "Validators+repair"),
        ("ablation_retrieval_topk_0", "No retrieval"),
        ("ablation_rewrite_false", "No rewrite"),
        ("ablation_judge_false", "No LLM judge"),
        ("full_pipe_cypher", "Full PIPE-Cypher"),
    ]
    for needle, label in labels:
        if needle in run:
            return label
    return run


def _graph_label(run: str) -> str:
    return "SNB" if "snb" in run.lower() else "FinBench"


if __name__ == "__main__":
    main()
