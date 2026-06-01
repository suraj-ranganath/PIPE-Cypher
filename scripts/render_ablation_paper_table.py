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


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a LaTeX paper table from ablation run artifacts.")
    parser.add_argument("runs", nargs="+", help="Run directories or records.jsonl files.")
    parser.add_argument("--target-per-category", type=int, default=5)
    parser.add_argument("--category-count", type=int, default=8)
    parser.add_argument(
        "--output",
        default="paper_emnlp2026_industry/tables_ablation_results.tex",
    )
    args = parser.parse_args()

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


if __name__ == "__main__":
    main()
