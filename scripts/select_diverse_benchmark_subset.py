#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.benchmark_export import export_stats
from pipecypher.diversity_metrics import (
    benchmark_diversity_report,
    load_benchmark_examples,
    load_schema_inventory,
)
from pipecypher.diversity_selection import (
    assign_diversity_splits,
    report_sha256,
    select_diverse_examples,
    selection_report_markdown,
    split_disjointness_audit,
)
from pipecypher.io import write_jsonl
from pipecypher.paper_tables import render_diversity_improvement_table


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Select a diversity-governed balanced subset from benchmark examples."
    )
    parser.add_argument(
        "--benchmark",
        default="artifacts/benchmarks/20260601_live_full_qwen9b/all.jsonl",
        help="Input benchmark JSONL, usually an accepted all.jsonl export.",
    )
    parser.add_argument("--schema", action="append", default=[], help="Schema JSON path.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--target-per-graph-category", type=int, required=True)
    parser.add_argument(
        "--split-mode",
        choices=["iid", "signature_disjoint", "template_family_disjoint"],
        default="signature_disjoint",
    )
    parser.add_argument("--seed", default="13")
    parser.add_argument("--self-bleu-sample-size", type=int, default=200)
    parser.add_argument("--max-signature-share", type=float, default=0.20)
    parser.add_argument("--max-template-family-share", type=float, default=0.25)
    args = parser.parse_args()

    examples = load_benchmark_examples(args.benchmark)
    schema_inventory = load_schema_inventory(args.schema) if args.schema else None
    selected = select_diverse_examples(
        examples,
        target_per_group=args.target_per_graph_category,
        seed=args.seed,
        max_signature_share=args.max_signature_share,
        max_template_family_share=args.max_template_family_share,
    )
    selected_examples = selected["examples"]
    random_baseline = _balanced_hash_baseline(
        examples,
        target_per_group=args.target_per_graph_category,
        seed=args.seed,
    )

    selected_splits = assign_diversity_splits(
        selected_examples,
        mode=args.split_mode,
        seed=args.seed,
    )
    selected_stats = export_stats(selected_examples, selected_splits)
    selected_report = benchmark_diversity_report(
        selected_examples,
        schema_inventory=schema_inventory,
        self_bleu_sample_size=args.self_bleu_sample_size,
    )
    baseline_report = benchmark_diversity_report(
        random_baseline,
        schema_inventory=schema_inventory,
        self_bleu_sample_size=args.self_bleu_sample_size,
    )
    comparison = _comparison_payload(
        baseline_report=baseline_report,
        selected_report=selected_report,
        selection_report=selected["report"],
        split_audit=split_disjointness_audit(selected_splits, mode=args.split_mode),
        args=vars(args),
    )
    split_audit = comparison["split_audit"]

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_jsonl(out / "all.jsonl", selected_examples)
    for split, rows in selected_splits.items():
        write_jsonl(out / f"{split}.jsonl", rows)
    _write_json(out / "stats.json", selected_stats)
    _write_json(out / "selection_report.json", selected["report"])
    (out / "selection_report.md").write_text(
        selection_report_markdown(selected["report"]),
        encoding="utf-8",
    )
    _write_json(out / "diversity_report.json", selected_report)
    _write_json(out / "random_baseline_diversity_report.json", baseline_report)
    _write_json(out / "diversity_improvement_comparison.json", comparison)
    (out / "diversity_improvement_comparison.md").write_text(
        _comparison_markdown(comparison),
        encoding="utf-8",
    )
    (out / "tables_diversity_improvement.tex").write_text(
        render_diversity_improvement_table(comparison),
        encoding="utf-8",
    )
    manifest = {
        "benchmark": args.benchmark,
        "schema": args.schema,
        "target_per_graph_category": args.target_per_graph_category,
        "split_mode": args.split_mode,
        "seed": args.seed,
        "selected_examples": len(selected_examples),
        "random_baseline_examples": len(random_baseline),
        "split_audit": split_audit,
        "split_counts": {split: len(rows) for split, rows in selected_splits.items()},
        "sha256": report_sha256(
            {
                "selected_ids": [row.get("id") for row in selected_examples],
                "comparison": comparison,
            }
        ),
        "outputs": {
            "all": str(out / "all.jsonl"),
            "diversity_report": str(out / "diversity_report.json"),
            "comparison": str(out / "diversity_improvement_comparison.json"),
        },
    }
    _write_json(out / "manifest.json", manifest)
    print(f"wrote diversity-governed subset to {out}")


def _balanced_hash_baseline(
    examples: list[dict[str, Any]],
    *,
    target_per_group: int,
    seed: str,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in examples:
        key = (str(row.get("graph_profile", "unknown")), str(row.get("category", "unknown")))
        groups.setdefault(key, []).append(row)
    selected: list[dict[str, Any]] = []
    for group, rows in sorted(groups.items()):
        ordered = sorted(
            rows,
            key=lambda row: report_sha256(
                {
                    "seed": seed,
                    "group": group,
                    "id": row.get("id"),
                    "question": row.get("question"),
                }
            ),
        )
        selected.extend(ordered[: min(target_per_group, len(ordered))])
    return sorted(selected, key=lambda row: str(row.get("id", "")))


def _comparison_payload(
    *,
    baseline_report: dict[str, Any],
    selected_report: dict[str, Any],
    selection_report: dict[str, Any],
    split_audit: dict[str, Any],
    args: dict[str, Any],
) -> dict[str, Any]:
    metrics = {
        "pipe_diversity_index": (
            baseline_report["pipe_diversity_index"]["score"],
            selected_report["pipe_diversity_index"]["score"],
        ),
        "query_signature_ratio": (
            baseline_report["query_templates"]["unique_signature_ratio"],
            selected_report["query_templates"]["unique_signature_ratio"],
        ),
        "top_signature_share": (
            baseline_report["query_templates"]["top_signature_share"],
            selected_report["query_templates"]["top_signature_share"],
        ),
        "template_family_entropy": (
            baseline_report["template_families"]["distribution"]["normalized_entropy"],
            selected_report["template_families"]["distribution"]["normalized_entropy"],
        ),
        "operator_combo_entropy": (
            baseline_report["distributions"]["operator_combinations"]["normalized_entropy"],
            selected_report["distributions"]["operator_combinations"]["normalized_entropy"],
        ),
        "structural_substructures": (
            baseline_report["structural_substructures"]["unique_substructure_count"],
            selected_report["structural_substructures"]["unique_substructure_count"],
        ),
        "self_bleu_2": (
            baseline_report["question_text"]["self_bleu_2_sampled"],
            selected_report["question_text"]["self_bleu_2_sampled"],
        ),
        "ead_distinct_2": (
            baseline_report["question_text"]["ead_distinct_2"],
            selected_report["question_text"]["ead_distinct_2"],
        ),
        "schema_property_coverage": (
            baseline_report["schema_coverage"]["properties"]["coverage"],
            selected_report["schema_coverage"]["properties"]["coverage"],
        ),
    }
    rows = []
    for name, (baseline, selected) in metrics.items():
        rows.append(
            {
                "metric": name,
                "random_balanced": baseline,
                "diversity_governed": selected,
                "delta": selected - baseline,
            }
        )
    return {
        "method": "balanced_random_vs_diversity_governed_subset",
        "args": args,
        "rows": rows,
        "selection_report": selection_report,
        "split_audit": split_audit,
    }


def _comparison_markdown(comparison: dict[str, Any]) -> str:
    lines = [
        "# Diversity Improvement Comparison",
        "",
        "| Metric | Random balanced | Diversity governed | Delta |",
        "|---|---:|---:|---:|",
    ]
    for row in comparison["rows"]:
        lines.append(
            "| {metric} | {baseline:.3f} | {selected:.3f} | {delta:+.3f} |".format(
                metric=row["metric"],
                baseline=float(row["random_balanced"]),
                selected=float(row["diversity_governed"]),
                delta=float(row["delta"]),
            )
        )
    audit = comparison.get("split_audit", {})
    lines.extend(
        [
            "",
            f"- Split mode: `{audit.get('mode')}`",
            f"- Leakage-free split blocks: `{audit.get('leakage_free')}`",
            "",
        ]
    )
    return "\n".join(lines)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
