#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.experiments import compare_runs
from pipecypher.paper_tables import render_ablation_table

MIN_PAPER_TARGET_PER_CATEGORY = 50


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a LaTeX paper table from ablation run artifacts.")
    parser.add_argument("runs", nargs="+", help="Run directories or records.jsonl files.")
    parser.add_argument(
        "--target-per-category",
        type=int,
        default=MIN_PAPER_TARGET_PER_CATEGORY,
        help="Accepted examples per category for the rendered suite; defaults to the paper minimum.",
    )
    parser.add_argument("--category-count", type=int, default=8)
    parser.add_argument(
        "--output",
        default="paper_emnlp2026_industry/tables_ablation_results.tex",
    )
    parser.add_argument(
        "--allow-diagnostic-target",
        action="store_true",
        help="Allow sub-50 target tables for local diagnostics. Do not use for manuscript reporting.",
    )
    args = parser.parse_args()

    validate_paper_target(args.target_per_category, args.allow_diagnostic_target)

    summaries = compare_runs(args.runs)
    text = render_ablation_table(
        summaries,
        target_per_category=args.target_per_category,
        category_count=args.category_count,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(f"wrote {output}")


def validate_paper_target(target_per_category: int, allow_diagnostic_target: bool) -> None:
    if target_per_category >= MIN_PAPER_TARGET_PER_CATEGORY or allow_diagnostic_target:
        return
    raise SystemExit(
        "refusing to render paper ablation table below "
        f"target_per_category={MIN_PAPER_TARGET_PER_CATEGORY}; "
        "use --allow-diagnostic-target only for internal layout checks"
    )


if __name__ == "__main__":
    main()
