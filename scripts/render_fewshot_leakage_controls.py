#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.fewshot_audit import (
    audit_fewshot_leakage_from_paths,
    build_fewshot_leakage_control_report,
    render_fewshot_leakage_control_latex,
    render_fewshot_leakage_control_markdown,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render a multi-mode few-shot leakage control table."
    )
    parser.add_argument(
        "--benchmark-dir",
        default="artifacts/benchmarks/20260604_live_full_qwen9b_reviewfix",
    )
    parser.add_argument("--split", default="test")
    parser.add_argument(
        "--selection-log",
        action="append",
        required=True,
        metavar="LABEL=PATH",
        help="Selection log with a reader-facing mode label.",
    )
    parser.add_argument("--high-similarity-threshold", type=float, default=0.90)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", default="")
    parser.add_argument("--output-tex", default="")
    args = parser.parse_args()

    reports = {}
    for spec in args.selection_log:
        label, path = _parse_selection_spec(spec)
        reports[label] = audit_fewshot_leakage_from_paths(
            benchmark_dir=args.benchmark_dir,
            split=args.split,
            selection_path=path,
            high_similarity_threshold=args.high_similarity_threshold,
        )

    report = build_fewshot_leakage_control_report(reports)
    _write(Path(args.output_json), json.dumps(report, indent=2, sort_keys=True) + "\n")
    if args.output_md:
        _write(Path(args.output_md), render_fewshot_leakage_control_markdown(report))
    if args.output_tex:
        _write(Path(args.output_tex), render_fewshot_leakage_control_latex(report))


def _parse_selection_spec(spec: str) -> tuple[str, str]:
    if "=" not in spec:
        raise SystemExit(f"--selection-log must be LABEL=PATH, got: {spec}")
    label, path = spec.split("=", 1)
    if not label or not path:
        raise SystemExit(f"--selection-log must be LABEL=PATH, got: {spec}")
    if not Path(path).exists():
        raise SystemExit(f"selection log does not exist: {path}")
    return label, path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
