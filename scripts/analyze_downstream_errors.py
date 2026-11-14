#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.downstream_error_analysis import (
    downstream_error_report,
    load_evaluation_rows,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze downstream Text2Cypher row-level errors."
    )
    parser.add_argument("--evaluation", required=True, help="Evaluation JSONL rows")
    parser.add_argument("--output-json", default="")
    args = parser.parse_args()

    rows = load_evaluation_rows(args.evaluation)
    report = downstream_error_report(rows, source_path=args.evaluation)
    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    if args.output_json:
        output = Path(args.output_json)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {output}", file=sys.stderr)


if __name__ == "__main__":
    main()
