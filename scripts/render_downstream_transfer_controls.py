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
    render_model_transfer_latex,
    render_model_transfer_markdown,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render downstream transfer-control report artifacts."
    )
    parser.add_argument("--summary-json", required=True)
    parser.add_argument("--output-md", default="")
    parser.add_argument("--output-tex", default="")
    args = parser.parse_args()

    report = json.loads(Path(args.summary_json).read_text(encoding="utf-8"))
    if args.output_md:
        _write(Path(args.output_md), render_model_transfer_markdown(report))
    if args.output_tex:
        _write(Path(args.output_tex), render_model_transfer_latex(report))
    if not args.output_md and not args.output_tex:
        print(render_model_transfer_markdown(report))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
