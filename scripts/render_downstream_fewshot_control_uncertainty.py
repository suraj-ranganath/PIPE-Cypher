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
    build_fewshot_control_uncertainty_report,
    render_fewshot_control_uncertainty_latex,
    render_fewshot_control_uncertainty_markdown,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render model-level uncertainty for downstream few-shot controls."
    )
    parser.add_argument("--summary-json", required=True)
    parser.add_argument("--iterations", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", default="")
    parser.add_argument("--output-tex", default="")
    args = parser.parse_args()

    summary = json.loads(Path(args.summary_json).read_text(encoding="utf-8"))
    report = build_fewshot_control_uncertainty_report(
        summary,
        iterations=args.iterations,
        seed=args.seed,
    )
    _write(Path(args.output_json), json.dumps(report, indent=2, sort_keys=True) + "\n")
    if args.output_md:
        _write(Path(args.output_md), render_fewshot_control_uncertainty_markdown(report))
    if args.output_tex:
        _write(Path(args.output_tex), render_fewshot_control_uncertainty_latex(report))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
