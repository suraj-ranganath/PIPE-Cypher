#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.experiments import format_summary_lines, summarize_records_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize PIPE-Cypher JSONL records")
    parser.add_argument("records")
    args = parser.parse_args()

    summary = summarize_records_path(args.records)
    print("\n".join(format_summary_lines(summary)))


if __name__ == "__main__":
    main()
