#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.ablation_comparison import (
    compare_ablation_suites,
    format_ablation_suite_comparison_csv,
    format_ablation_suite_comparison_markdown,
    format_ablation_suite_comparison_tex,
    write_ablation_suite_comparison_json,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare completed PIPE-Cypher ablation suite summary JSON files."
    )
    parser.add_argument(
        "summaries",
        nargs="+",
        help="Paths to ablation_suite_summary.json files from collected suites.",
    )
    parser.add_argument("--output-json")
    parser.add_argument("--output-md")
    parser.add_argument("--output-csv")
    parser.add_argument("--output-tex")
    parser.add_argument(
        "--allow-diagnostic-tex",
        action="store_true",
        help="Allow LaTeX output before all compared suites are evidence-ready.",
    )
    args = parser.parse_args()

    report = compare_ablation_suites(args.summaries)
    if args.output_json:
        write_ablation_suite_comparison_json(report, args.output_json)
        print(f"wrote {args.output_json}")
    markdown = format_ablation_suite_comparison_markdown(report)
    if args.output_md:
        output_md = Path(args.output_md)
        output_md.parent.mkdir(parents=True, exist_ok=True)
        output_md.write_text(markdown, encoding="utf-8")
        print(f"wrote {output_md}")
    if args.output_csv:
        output_csv = Path(args.output_csv)
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        output_csv.write_text(format_ablation_suite_comparison_csv(report), encoding="utf-8")
        print(f"wrote {output_csv}")
    if args.output_tex:
        _require_tex_ready(report, args.allow_diagnostic_tex)
        output_tex = Path(args.output_tex)
        output_tex.parent.mkdir(parents=True, exist_ok=True)
        output_tex.write_text(format_ablation_suite_comparison_tex(report), encoding="utf-8")
        print(f"wrote {output_tex}")
    if not any([args.output_json, args.output_md, args.output_csv, args.output_tex]):
        print(markdown)


def _require_tex_ready(report: dict, allow_diagnostic: bool) -> None:
    if allow_diagnostic:
        return
    if int(report.get("suite_count", 0)) < 2:
        raise SystemExit(
            "refusing to render comparison LaTeX from fewer than two suites; "
            "use --allow-diagnostic-tex only for internal diagnostics"
        )
    if int(report.get("evidence_ready_suite_count", 0)) == int(report.get("suite_count", 0)):
        return
    not_ready = [
        str(suite.get("run_prefix", ""))
        for suite in report.get("suites", [])
        if not suite.get("evidence_ready")
    ]
    raise SystemExit(
        "refusing to render comparison LaTeX before all suites are collected and "
        "paper-ready; not ready: {items}. Use --allow-diagnostic-tex only for "
        "internal diagnostics".format(items=", ".join(not_ready))
    )


if __name__ == "__main__":
    main()
