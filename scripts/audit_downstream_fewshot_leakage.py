#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.fewshot_audit import (
    audit_fewshot_leakage_from_paths,
    render_fewshot_leakage_latex,
    render_fewshot_leakage_markdown,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit few-shot demonstration overlap for downstream Text2Cypher runs."
    )
    parser.add_argument(
        "--benchmark-dir",
        default="artifacts/benchmarks/20260601_live_full_qwen9b",
    )
    parser.add_argument("--split", default="test")
    parser.add_argument("--predictions", default="")
    parser.add_argument("--selection-log", default="")
    parser.add_argument("--high-similarity-threshold", type=float, default=0.90)
    parser.add_argument(
        "--reconstruct-mode",
        choices=["", "ordered_same_category", "random_same_category", "scored_no_signature"],
        default="",
        help="Reconstruct selected examples from train/test splits when no selection log exists.",
    )
    parser.add_argument("--few-shot-k", type=int, default=5)
    parser.add_argument("--few-shot-seed", type=int, default=13)
    parser.add_argument("--few-shot-max-question-sim", type=float, default=0.90)
    parser.add_argument("--few-shot-exclude-signature-match", action="store_true")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", default="")
    parser.add_argument("--output-tex", default="")
    args = parser.parse_args()

    report = audit_fewshot_leakage_from_paths(
        benchmark_dir=args.benchmark_dir,
        split=args.split,
        predictions_path=args.predictions or None,
        selection_path=args.selection_log or None,
        high_similarity_threshold=args.high_similarity_threshold,
        reconstruct_mode=args.reconstruct_mode,
        few_shot_k=args.few_shot_k,
        few_shot_seed=args.few_shot_seed,
        few_shot_max_question_similarity=args.few_shot_max_question_sim,
        few_shot_exclude_signature_match=args.few_shot_exclude_signature_match,
    )
    _write(Path(args.output_json), json.dumps(report, indent=2, sort_keys=True) + "\n")
    if args.output_md:
        _write(Path(args.output_md), render_fewshot_leakage_markdown(report))
    if args.output_tex:
        _write(Path(args.output_tex), render_fewshot_leakage_latex(report))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
