#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.ablation_comparison import (
    compare_ablation_suites,
    format_ablation_suite_comparison_csv,
    format_ablation_suite_comparison_markdown,
    write_ablation_suite_comparison_json,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare completed PIPE-Cypher ablation suite summary JSON files."
    )
    parser.add_argument(
        "summaries",
        nargs="+",
        help="Paths to ablation_suite_summary.json files from collected suites.",
    )
    parser.add_argument("--output-json")
    parser.add_argument("--output-md")
    parser.add_argument("--output-csv")
    args = parser.parse_args()

    report = compare_ablation_suites(args.summaries)
    if args.output_json:
        write_ablation_suite_comparison_json(report, args.output_json)
        print(f"wrote {args.output_json}")
    markdown = format_ablation_suite_comparison_markdown(report)
    if args.output_md:
        output_md = Path(args.output_md)
        output_md.parent.mkdir(parents=True, exist_ok=True)
        output_md.write_text(markdown, encoding="utf-8")
        print(f"wrote {output_md}")
    if args.output_csv:
        output_csv = Path(args.output_csv)
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        output_csv.write_text(format_ablation_suite_comparison_csv(report), encoding="utf-8")
        print(f"wrote {output_csv}")
    if not any([args.output_json, args.output_md, args.output_csv]):
        print(markdown)


if __name__ == "__main__":
    main()
