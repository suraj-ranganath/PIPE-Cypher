#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.experiments import (
    compare_runs,
    format_run_comparison_csv,
    format_run_comparison_markdown,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare PIPE-Cypher run artifacts")
    parser.add_argument("runs", nargs="+", help="Run directories or records.jsonl files")
    parser.add_argument("--format", choices=["markdown", "csv", "json"], default="markdown")
    args = parser.parse_args()

    summaries = compare_runs(args.runs)
    if args.format == "markdown":
        print(format_run_comparison_markdown(summaries))
    elif args.format == "csv":
        print(format_run_comparison_csv(summaries), end="")
    else:
        print(json.dumps(summaries, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
