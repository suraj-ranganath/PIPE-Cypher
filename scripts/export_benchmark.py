#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.benchmark_export import export_benchmark_package


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export accepted PIPE-Cypher records as a benchmark package"
    )
    parser.add_argument(
        "--records",
        nargs="+",
        required=True,
        help="Run directories or records.jsonl paths. Multiple sources are deduplicated by example ID.",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--include-rejected", action="store_true")
    parser.add_argument("--split-seed", default="pipe-cypher-v1")
    parser.add_argument("--result-sample-limit", type=int, default=5)
    args = parser.parse_args()

    result = export_benchmark_package(
        records_paths=args.records,
        output_dir=args.output_dir,
        accepted_only=not args.include_rejected,
        split_seed=args.split_seed,
        result_sample_limit=args.result_sample_limit,
    )
    print(json.dumps(result["manifest"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
