#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipecypher.downstream_model_transfer import (
    build_model_transfer_report,
    render_model_transfer_latex,
    render_model_transfer_markdown,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize completed local-model downstream Text2Cypher transfer runs."
    )
    parser.add_argument(
        "--run-dir",
        action="append",
        required=True,
        help="Evaluation run directory containing zero_shot_summary.json and few_shot_summary.json.",
    )
    parser.add_argument(
        "--metadata-json",
        help="Optional JSON mapping run directory names to model metadata.",
    )
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md")
    parser.add_argument("--output-tex")
    args = parser.parse_args()

    metadata = {}
    if args.metadata_json:
        metadata = json.loads(Path(args.metadata_json).read_text(encoding="utf-8"))

    report = build_model_transfer_report([Path(item) for item in args.run_dir], metadata)

    _write_text(Path(args.output_json), json.dumps(report, indent=2, sort_keys=True) + "\n")
    if args.output_md:
        _write_text(Path(args.output_md), render_model_transfer_markdown(report))
    if args.output_tex:
        _write_text(Path(args.output_tex), render_model_transfer_latex(report))


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
