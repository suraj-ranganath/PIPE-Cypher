#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.failure_taxonomy import failure_taxonomy_report, load_record_paths
from pipecypher.paper_tables import render_failure_taxonomy_table


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze rejection stages and failure buckets for PIPE-Cypher records."
    )
    parser.add_argument(
        "--records",
        nargs="+",
        required=True,
        help="records.jsonl files or run directories.",
    )
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-tex", default="")
    parser.add_argument("--top-n", type=int, default=12)
    args = parser.parse_args()

    records = load_record_paths(args.records)
    report = failure_taxonomy_report(records, source_paths=args.records, top_n=args.top_n)

    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {output_json}")

    if args.output_tex:
        output_tex = Path(args.output_tex)
        output_tex.parent.mkdir(parents=True, exist_ok=True)
        output_tex.write_text(render_failure_taxonomy_table(report), encoding="utf-8")
        print(f"wrote {output_tex}")


if __name__ == "__main__":
    main()
