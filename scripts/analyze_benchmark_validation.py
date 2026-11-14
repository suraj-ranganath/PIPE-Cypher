#!/usr/bin/env python3
"""Analyze filled benchmark-validation sheets from 2+ annotators (E2.2).

Reports the benchmark reference error rate (reference_correct == no) with
Wilson 95% intervals, any/all-annotator bounds, per graph/category/difficulty
rates, a stratified estimate (instances packet) or signature-level estimate
(templates packet), Cohen's kappa per annotator pair (Fleiss' kappa for >2
annotators), error-type counts, and a PRIVATE/internal disagreement CSV that
doubles as the adjudication template (feed it back with --adjudication).
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
    analyze_validation_sheets,
    render_validation_latex,
    render_validation_markdown,
    validation_disagreement_rows,
    write_validation_disagreements,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sheets", nargs="+", required=True, help="Filled annotator CSVs (2 or more)")
    parser.add_argument("--key", default="", help="Key CSV written by build_benchmark_validation_packet.py")
    parser.add_argument("--adjudication", default="", help="Filled disagreement CSV with adjudicated_* columns")
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    parser.add_argument("--output-tex", default="")
    parser.add_argument("--output-disagreements-csv", default="", help="PRIVATE/internal adjudication template")
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="Exit non-zero unless every sheet labels every item and no reference label is unresolved",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if len(args.sheets) < 2:
        print("warning: agreement statistics need at least two annotator sheets", file=sys.stderr)
    report = analyze_validation_sheets(
        args.sheets,
        key_path=args.key or None,
        adjudication_path=args.adjudication or None,
    )
    if args.output_json:
        _write(args.output_json, json.dumps(report, indent=2, sort_keys=True) + "\n")
    if args.output_md:
        _write(args.output_md, render_validation_markdown(report))
    if args.output_tex:
        _write(args.output_tex, render_validation_latex(report))
    if args.output_disagreements_csv:
        rows, fields = validation_disagreement_rows(args.sheets, key_path=args.key or None)
        write_validation_disagreements(args.output_disagreements_csv, rows, fields)
        print(f"wrote {args.output_disagreements_csv} ({len(rows)} rows, PRIVATE/internal)", file=sys.stderr)
    head = report["headline"]
    rate = head["reference_error_rate"]
    print(
        f"mode={report['mode']} items={report['items']} annotators={report['annotators']} "
        f"reference_error={rate['rate']} ci95={rate['ci95']} n={rate['n']} "
        f"unresolved={head['unresolved_reference_items']} ready_for_paper={head['ready_for_paper']}"
    )
    if args.require_complete and not head["ready_for_paper"]:
        incomplete = {
            name: entry for name, entry in report["completeness"].items() if not entry["complete"]
        }
        print(
            "validation incomplete: "
            + json.dumps(
                {
                    "incomplete_sheets": {
                        name: {"missing": e["missing_items"], "unlabeled": e["unlabeled"]}
                        for name, e in incomplete.items()
                    },
                    "unresolved_reference_items": head["unresolved_reference_items"],
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    return 0


def _write(path: str, text: str) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
