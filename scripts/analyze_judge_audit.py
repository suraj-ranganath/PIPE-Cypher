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

from pipecypher.calibration import analyze_audit_csv, summarize_audit_csv


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze completed judge calibration CSV")
    parser.add_argument("--audit", required=True)
    parser.add_argument(
        "--require-labels",
        action="store_true",
        help="Exit non-zero if the audit CSV has no completed human labels.",
    )
    parser.add_argument(
        "--require-complete-labels",
        action="store_true",
        help="Exit non-zero unless every audit row has a completed human label.",
    )
    args = parser.parse_args()
    metrics = analyze_audit_csv(args.audit)
    coverage = summarize_audit_csv(args.audit)
    print(
        json.dumps(
            {
                "coverage": asdict(coverage),
                "metrics": asdict(metrics),
            },
            indent=2,
            sort_keys=True,
        )
    )
    if args.require_labels and metrics.total_labeled == 0:
        raise SystemExit("judge audit has no completed human labels")
    if args.require_complete_labels and (coverage.total_rows == 0 or coverage.unlabeled_rows > 0):
        raise SystemExit(
            "judge audit is not fully labeled: "
            f"{coverage.labeled_rows}/{coverage.total_rows} rows labeled"
        )


if __name__ == "__main__":
    main()
