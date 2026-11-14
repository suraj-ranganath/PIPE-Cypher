#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.diversity_metrics import (
    benchmark_diversity_report,
    load_benchmark_examples,
    load_schema_inventory,
)
from pipecypher.paper_tables import render_diversity_table
from pipecypher.paper_tables import render_query_signature_concentration_table


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute text, schema, and structural diversity metrics for a benchmark export."
    )
    parser.add_argument(
        "--benchmark",
        default="artifacts/benchmarks/20260604_live_full_qwen9b_reviewfix/all.jsonl",
        help="Path to all.jsonl or another exported benchmark JSONL file.",
    )
    parser.add_argument(
        "--schema",
        action="append",
        default=[],
        help="Schema JSON path. May be repeated.",
    )
    parser.add_argument("--self-bleu-sample-size", type=int, default=200)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-tex", default="")
    parser.add_argument("--output-signature-tex", default="")
    args = parser.parse_args()

    examples = load_benchmark_examples(args.benchmark)
    schema_inventory = load_schema_inventory(args.schema) if args.schema else None
    report = benchmark_diversity_report(
        examples,
        schema_inventory=schema_inventory,
        self_bleu_sample_size=args.self_bleu_sample_size,
    )

    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {output_json}")

    if args.output_tex:
        output_tex = Path(args.output_tex)
        output_tex.parent.mkdir(parents=True, exist_ok=True)
        output_tex.write_text(render_diversity_table(report), encoding="utf-8")
        print(f"wrote {output_tex}")
    if args.output_signature_tex:
        output_tex = Path(args.output_signature_tex)
        output_tex.parent.mkdir(parents=True, exist_ok=True)
        output_tex.write_text(
            render_query_signature_concentration_table(report),
            encoding="utf-8",
        )
        print(f"wrote {output_tex}")


if __name__ == "__main__":
    main()
