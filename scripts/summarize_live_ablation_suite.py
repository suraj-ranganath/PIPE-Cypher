#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.ablation_suite import (
    DEFAULT_GRAPHS,
    DEFAULT_PAPER_TARGET_PER_CATEGORY,
    DEFAULT_VARIANTS,
    audit_ablation_suite_for_paper,
    format_ablation_suite_audit_markdown,
    format_ablation_suite_markdown,
    summarize_ablation_suite,
    write_ablation_suite_csv,
    write_ablation_suite_json,
)
from pipecypher.paper_tables import render_ablation_quality_table, render_ablation_table


def _parse_metadata(items: list[str]) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise SystemExit(f"metadata must be KEY=VALUE, got {item!r}")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise SystemExit(f"metadata key cannot be empty: {item!r}")
        metadata[key] = value.strip()
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize a live FinBench/SNB ablation suite from run artifacts."
    )
    parser.add_argument("runs", nargs="*", help="Run directories or records.jsonl files.")
    parser.add_argument("--glob", action="append", default=[], help="Glob for run directories.")
    parser.add_argument("--target-per-category", type=int, required=True)
    parser.add_argument("--category-count", type=int, default=8)
    parser.add_argument("--expected-graph", action="append")
    parser.add_argument("--expected-variant", action="append")
    parser.add_argument("--output-json")
    parser.add_argument("--output-md")
    parser.add_argument("--output-csv")
    parser.add_argument("--output-audit-json")
    parser.add_argument("--output-audit-md")
    parser.add_argument("--output-tex")
    parser.add_argument("--output-quality-tex")
    parser.add_argument("--min-paper-target", type=int, default=DEFAULT_PAPER_TARGET_PER_CATEGORY)
    parser.add_argument(
        "--metadata",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Metadata to embed in JSON/Markdown summaries.",
    )
    parser.add_argument(
        "--allow-incomplete-tex",
        action="store_true",
        help=(
            "Allow LaTeX output even when the paper-readiness audit fails. "
            "Use only for internal diagnostics."
        ),
    )
    args = parser.parse_args()

    paths = [Path(run) for run in args.runs]
    for pattern in args.glob:
        paths.extend(Path(path) for path in sorted(glob.glob(pattern)))
    paths = sorted({path for path in paths})
    if not paths:
        raise SystemExit("no run paths matched")

    report = summarize_ablation_suite(
        paths,
        target_per_category=args.target_per_category,
        category_count=args.category_count,
        expected_graphs=args.expected_graph or list(DEFAULT_GRAPHS),
        expected_variants=args.expected_variant or list(DEFAULT_VARIANTS),
        metadata=_parse_metadata(args.metadata),
    )
    audit = audit_ablation_suite_for_paper(
        report,
        min_target_per_category=args.min_paper_target,
    )

    if args.output_json:
        write_ablation_suite_json(report, args.output_json)
        print(f"wrote {args.output_json}")
    if args.output_md:
        output = Path(args.output_md)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(format_ablation_suite_markdown(report), encoding="utf-8")
        print(f"wrote {output}")
    if args.output_csv:
        write_ablation_suite_csv(report, args.output_csv)
        print(f"wrote {args.output_csv}")
    if args.output_audit_json:
        output = Path(args.output_audit_json)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")
        print(f"wrote {output}")
    if args.output_audit_md:
        output = Path(args.output_audit_md)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(format_ablation_suite_audit_markdown(audit), encoding="utf-8")
        print(f"wrote {output}")
    if args.output_tex:
        _require_paper_ready(audit, args.allow_incomplete_tex, "ablation LaTeX")
        output = Path(args.output_tex)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            render_ablation_table(
                report["runs"],
                target_per_category=args.target_per_category,
                category_count=args.category_count,
            ),
            encoding="utf-8",
        )
        print(f"wrote {output}")
    if args.output_quality_tex:
        _require_paper_ready(audit, args.allow_incomplete_tex, "ablation quality LaTeX")
        output = Path(args.output_quality_tex)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            render_ablation_quality_table(
                report["runs"],
                target_per_category=args.target_per_category,
            ),
            encoding="utf-8",
        )
        print(f"wrote {output}")

    if not any(
        [
            args.output_json,
            args.output_md,
            args.output_csv,
            args.output_audit_json,
            args.output_audit_md,
            args.output_tex,
            args.output_quality_tex,
        ]
    ):
        print(format_ablation_suite_markdown(report))


def _require_paper_ready(audit: dict, allow_diagnostic: bool, artifact: str) -> None:
    if audit["paper_ready"] or allow_diagnostic:
        return
    failed = ", ".join(check["name"] for check in audit["failed_checks"])
    raise SystemExit(
        f"refusing to render {artifact} from a suite that is not paper-ready; "
        f"failed checks: {failed}. Use --allow-incomplete-tex only for internal diagnostics"
    )


if __name__ == "__main__":
    main()
