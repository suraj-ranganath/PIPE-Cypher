#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipecypher.downstream_model_transfer import (
    build_fewshot_control_report,
    render_fewshot_control_latex,
    render_fewshot_control_markdown,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize zero-shot vs few-shot downstream control runs."
    )
    parser.add_argument(
        "--zero-run-dir",
        action="append",
        required=True,
        help="Historical zero/few-shot evaluation directory containing zero_shot_summary.json.",
    )
    parser.add_argument(
        "--control-run-dir",
        action="append",
        required=True,
        help="Few-shot control evaluation directory containing few_shot_summary.json.",
    )
    parser.add_argument("--metadata-json", default="")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", default="")
    parser.add_argument("--output-tex", default="")
    args = parser.parse_args()

    metadata = {}
    if args.metadata_json:
        metadata = json.loads(Path(args.metadata_json).read_text(encoding="utf-8"))

    report = build_fewshot_control_report(
        zero_shot_dirs=[Path(item) for item in args.zero_run_dir],
        control_dirs=[Path(item) for item in args.control_run_dir],
        metadata=metadata,
    )
    _write(Path(args.output_json), json.dumps(report, indent=2, sort_keys=True) + "\n")
    if args.output_md:
        _write(Path(args.output_md), render_fewshot_control_markdown(report))
    if args.output_tex:
        _write(Path(args.output_tex), render_fewshot_control_latex(report))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
