#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.evaluation_uncertainty import (
    DEFAULT_GROUP_KEYS,
    DEFAULT_METRICS,
    analyze_evaluation_uncertainty,
    format_evaluation_uncertainty_markdown,
    render_downstream_uncertainty_table,
)
from pipecypher.io import read_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bootstrap uncertainty intervals for downstream Text2Cypher evaluation rows."
    )
    parser.add_argument("--evaluation", required=True, help="Evaluation JSONL rows")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", default="")
    parser.add_argument("--output-tex", default="")
    parser.add_argument("--iterations", type=int, default=2000)
    parser.add_argument("--confidence-level", type=float, default=0.95)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument(
        "--metric",
        action="append",
        dest="metrics",
        help="Metric column to analyze; defaults to core downstream metrics.",
    )
    parser.add_argument(
        "--group-key",
        action="append",
        dest="group_keys",
        help="Grouping key for appendix diagnostics; defaults to graph/category/difficulty.",
    )
    args = parser.parse_args()

    rows = read_jsonl(args.evaluation)
    report = analyze_evaluation_uncertainty(
        rows,
        metrics=tuple(args.metrics or DEFAULT_METRICS),
        group_keys=tuple(args.group_keys or DEFAULT_GROUP_KEYS),
        iterations=args.iterations,
        confidence_level=args.confidence_level,
        seed=args.seed,
    )

    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {output_json}")

    if args.output_md:
        output_md = Path(args.output_md)
        output_md.parent.mkdir(parents=True, exist_ok=True)
        output_md.write_text(format_evaluation_uncertainty_markdown(report), encoding="utf-8")
        print(f"wrote {output_md}")

    if args.output_tex:
        output_tex = Path(args.output_tex)
        output_tex.parent.mkdir(parents=True, exist_ok=True)
        output_tex.write_text(render_downstream_uncertainty_table(report), encoding="utf-8")
        print(f"wrote {output_tex}")


if __name__ == "__main__":
    main()
