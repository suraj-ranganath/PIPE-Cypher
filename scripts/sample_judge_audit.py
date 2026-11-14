#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.calibration import load_records, sample_for_audit, write_audit_csv


def main() -> None:
    parser = argparse.ArgumentParser(description="Sample PIPE-Cypher records for judge calibration")
    parser.add_argument("--records", nargs="+", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument(
        "--no-stratify",
        action="store_true",
        help="Disable graph/category/judge-outcome stratification and use global accept/reject sampling.",
    )
    args = parser.parse_args()

    records = []
    for records_path in args.records:
        records.extend(load_records(records_path))
    sample = sample_for_audit(records, n=args.n, seed=args.seed, stratify=not args.no_stratify)
    write_audit_csv(sample, args.output)
    print(f"sampled={len(sample)} output={args.output}")


if __name__ == "__main__":
    main()
