#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.downstream_model_transfer import (
    build_model_transfer_report,
    render_model_transfer_latex,
    render_model_transfer_markdown,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare completed downstream zero/few-shot control runs."
    )
    parser.add_argument(
        "--run-dir",
        action="append",
        required=True,
        help="Evaluation directory with zero_shot_summary.json and few_shot_summary.json.",
    )
    parser.add_argument("--metadata-json", default="")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", default="")
    parser.add_argument("--output-tex", default="")
    args = parser.parse_args()

    metadata = {}
    if args.metadata_json:
        metadata = json.loads(Path(args.metadata_json).read_text(encoding="utf-8"))
    report = build_model_transfer_report([Path(item) for item in args.run_dir], metadata)
    _write(Path(args.output_json), json.dumps(report, indent=2, sort_keys=True) + "\n")
    if args.output_md:
        _write(Path(args.output_md), render_model_transfer_markdown(report))
    if args.output_tex:
        _write(Path(args.output_tex), render_model_transfer_latex(report))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
