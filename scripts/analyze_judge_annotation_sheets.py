#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.calibration import (
    analyze_annotation_sheets,
    disagreement_rows,
    write_disagreement_csv,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze independent judge-audit annotation sheets."
    )
    parser.add_argument("--annotator-a", required=True)
    parser.add_argument("--annotator-b", required=True)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-disagreements-csv", default="")
    parser.add_argument(
        "--require-complete-labels",
        action="store_true",
        help="Exit non-zero unless both annotator sheets label every shared row.",
    )
    args = parser.parse_args()

    metrics = analyze_annotation_sheets(args.annotator_a, args.annotator_b)
    payload = {"agreement": asdict(metrics)}
    text = json.dumps(payload, indent=2, sort_keys=True)
    print(text)
    if args.output_json:
        output = Path(args.output_json)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {output}", file=sys.stderr)
    if args.output_disagreements_csv:
        rows = disagreement_rows(args.annotator_a, args.annotator_b)
        write_disagreement_csv(rows, args.output_disagreements_csv)
        print(f"wrote {args.output_disagreements_csv}", file=sys.stderr)
    if args.require_complete_labels:
        if metrics.duplicate_ids_a or metrics.duplicate_ids_b:
            raise SystemExit("annotation sheets contain duplicate row ids")
        if metrics.missing_in_a or metrics.missing_in_b:
            raise SystemExit(
                "annotation sheets do not cover the same ids: "
                f"missing_in_a={metrics.missing_in_a}, missing_in_b={metrics.missing_in_b}"
            )
        if metrics.unlabeled_in_a or metrics.unlabeled_in_b:
            raise SystemExit(
                "annotation sheets are not fully labeled: "
                f"unlabeled_in_a={metrics.unlabeled_in_a}, "
                f"unlabeled_in_b={metrics.unlabeled_in_b}"
            )


if __name__ == "__main__":
    main()
