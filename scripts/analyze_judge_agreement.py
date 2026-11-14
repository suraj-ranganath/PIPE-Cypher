#!/usr/bin/env python3
"""Analyze agreement between the original judge and independent re-judges (E2.1).

Inputs are one or more JSONL files from ``rejudge_with_independent_model.py``
(``label=path`` overrides the judge label). Original decisions are taken from
the rows' embedded ``original_judge`` block unless ``--original-benchmark`` /
``--original-records`` are given.

Outputs: JSON + Markdown + LaTeX summary (aggregate metrics only) and an
optional disagreement CSV for human adjudication, which is PRIVATE/internal
(first line is a ``#`` privacy comment) because it carries questions, Cypher
literals, and result rows.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.judge_agreement import (  # noqa: E402
    analyze_judge_agreement,
    judge_disagreement_rows,
    load_rejudge_file,
    original_decisions_from_sources,
    render_agreement_latex,
    render_agreement_markdown,
    render_agreement_slices_latex,
    write_private_csv,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rejudge", nargs="+", required=True, help="Rejudge JSONL files (optionally label=path)")
    parser.add_argument("--original-benchmark", nargs="*", default=[], help="Export dirs/JSONL with gates.judge_pass")
    parser.add_argument("--original-records", nargs="*", default=[], help="records.jsonl files for rejected candidates")
    parser.add_argument("--original-split", default="all", choices=["all", "train", "dev", "test"])
    parser.add_argument("--original-label", default="original_qwen3.5_9b")
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    parser.add_argument("--output-tex", default="")
    parser.add_argument("--output-slices-tex", default="", help="Per-category pass-rate LaTeX table")
    parser.add_argument("--output-disagreements-csv", default="", help="PRIVATE/internal adjudication packet")
    parser.add_argument("--preview-rows", type=int, default=3)
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="Exit non-zero if any judge has failed calls or is missing items",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runs = []
    for spec in args.rejudge:
        label = None
        path = spec
        if "=" in spec and not Path(spec).exists():
            label, path = spec.split("=", 1)
        runs.append(load_rejudge_file(path, label=label))

    override = None
    if args.original_benchmark or args.original_records:
        override = original_decisions_from_sources(
            args.original_benchmark,
            args.original_records,
            split=args.original_split,
        )
    report = analyze_judge_agreement(runs, original_override=override, original_label=args.original_label)
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.output_json:
        _write(args.output_json, text + "\n")
    if args.output_md:
        _write(args.output_md, render_agreement_markdown(report))
    if args.output_tex:
        _write(args.output_tex, render_agreement_latex(report))
    if args.output_slices_tex:
        _write(args.output_slices_tex, render_agreement_slices_latex(report))
    if args.output_disagreements_csv:
        rows, fields = judge_disagreement_rows(
            runs, report, preview_rows=args.preview_rows, original_override=override
        )
        write_private_csv(args.output_disagreements_csv, rows, fields)
        print(f"wrote {args.output_disagreements_csv} ({len(rows)} rows, PRIVATE/internal)", file=sys.stderr)

    flags = report["flags"]
    print(
        f"items={report['items']['n_items']} judges={[j['label'] for j in report['judges']]} "
        f"flagged_by_any_independent={flags['flagged_by_any_independent']}/{flags['original_pass_items']} "
        f"fleiss_all={report['fleiss']['all_judges']['kappa']}"
    )
    if args.require_complete:
        incomplete = [
            f"{judge['label']}: errors={judge.get('errors', 0)} missing={judge.get('missing_items', 0)}"
            for judge in report["judges"]
            if judge.get("errors") or judge.get("missing_items")
        ]
        if incomplete:
            print("incomplete judge runs: " + "; ".join(incomplete), file=sys.stderr)
            return 1
    return 0


def _write(path: str, text: str) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
