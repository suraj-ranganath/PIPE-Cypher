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
    parser.add_argument(
        "--split-strategy",
        choices=["random", "signature_disjoint"],
        default="random",
        help="signature_disjoint holds out whole query signatures (template-held-out test).",
    )
    parser.add_argument(
        "--max-per-signature",
        type=int,
        default=0,
        help="Global cap per (graph, category, signature); 0 disables. Use with sharded runs.",
    )
    parser.add_argument(
        "--max-per-cell",
        action="append",
        default=[],
        help="Cap per (graph, category): N (all graphs) or graph=N; repeatable. Trims round-robin across signatures.",
    )
    args = parser.parse_args()

    result = export_benchmark_package(
        records_paths=args.records,
        output_dir=args.output_dir,
        accepted_only=not args.include_rejected,
        split_seed=args.split_seed,
        result_sample_limit=args.result_sample_limit,
        split_strategy=args.split_strategy,
        max_per_signature=args.max_per_signature,
        max_per_cell=_parse_cell_caps(args.max_per_cell),
    )
    print(json.dumps(result["manifest"], indent=2, sort_keys=True))


def _parse_cell_caps(items: list[str]) -> dict[str, int]:
    caps: dict[str, int] = {}
    for item in items:
        if "=" in item:
            graph, value = item.split("=", 1)
            caps[graph.strip()] = int(value)
        else:
            caps["*"] = int(item)
    return caps


if __name__ == "__main__":
    main()
