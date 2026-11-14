#!/usr/bin/env python3
"""Build human validation packets for benchmark reference correctness (E2.2).

Modes:
  templates  one group per canonical query signature x --realizations items (default 2)
  instances  seeded stratified sample over graph_profile x category (default --n 300)

Writes one CSV per annotator (identical rows, independently shuffled), a key
file, a rubric text file, optional per-graph schema text files, and a manifest
with SHA-256 checksums. Annotator sheets are PRIVATE/internal.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.benchmark_validation_packet import (  # noqa: E402
    annotator_names,
    build_instance_packet,
    build_template_packet,
    write_validation_packet,
)
from pipecypher.judge_agreement import benchmark_rows_path, load_benchmark_rows, sha256_file  # noqa: E402
from pipecypher.schema import load_schema  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--benchmark", required=True, help="Benchmark export directory or JSONL")
    parser.add_argument("--split", default="all", choices=["all", "train", "dev", "test"])
    parser.add_argument("--mode", required=True, choices=["templates", "instances"])
    parser.add_argument("--n", type=int, default=300, help="Instance sample size (instances mode)")
    parser.add_argument("--min-per-stratum", type=int, default=1)
    parser.add_argument("--realizations", type=int, default=2, help="Items per signature (templates mode)")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--annotators", type=int, default=2, help="Number of annotator sheets")
    parser.add_argument("--annotator-names", default="", help="Comma-separated names (overrides --annotators)")
    parser.add_argument("--preview-rows", type=int, default=3)
    parser.add_argument("--schema", action="append", default=[], help="graph_profile=path; writes schema_<graph>.txt")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--prefix", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    rows = load_benchmark_rows(args.benchmark, args.split)
    if args.mode == "templates":
        packet = build_template_packet(
            rows, realizations=args.realizations, seed=args.seed, preview_rows=args.preview_rows
        )
    else:
        packet = build_instance_packet(
            rows,
            n=args.n,
            seed=args.seed,
            min_per_stratum=args.min_per_stratum,
            preview_rows=args.preview_rows,
        )
    names = annotator_names(
        args.annotators,
        [name for name in args.annotator_names.split(",")] if args.annotator_names else None,
    )
    schemas = {}
    for item in args.schema:
        if "=" not in item:
            raise SystemExit("--schema entries must use graph_profile=path")
        graph, path = item.split("=", 1)
        schemas[graph] = load_schema(path)
    rows_path = benchmark_rows_path(args.benchmark, args.split)
    manifest = write_validation_packet(
        packet,
        args.output_dir,
        mode=args.mode,
        annotators=names,
        prefix=args.prefix,
        seed=args.seed,
        schemas=schemas,
        source={
            "benchmark": str(args.benchmark),
            "split": args.split,
            "rows_path": str(rows_path),
            "rows_sha256": sha256_file(rows_path),
            "benchmark_rows": len(rows),
            "n": args.n if args.mode == "instances" else None,
            "realizations": args.realizations if args.mode == "templates" else None,
            "min_per_stratum": args.min_per_stratum if args.mode == "instances" else None,
            "preview_rows": args.preview_rows,
        },
    )
    print(
        json.dumps(
            {
                "mode": manifest["mode"],
                "rows": manifest["row_count"],
                "signatures": manifest["signatures"],
                "annotators": manifest["annotators"],
                "manifest": manifest["manifest_path"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
