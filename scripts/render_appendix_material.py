#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.paper_appendix import (
    load_examples,
    render_example_cards_tex,
    render_prompt_contracts_tex,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render appendix prompt contracts and representative benchmark examples."
    )
    parser.add_argument(
        "--examples",
        default="experiments/snapshots/20260601_live_full_qwen9b/sample_examples.json",
    )
    parser.add_argument(
        "--output-prompts",
        default="paper_emnlp2026_industry/appendix_prompt_contracts.tex",
    )
    parser.add_argument(
        "--output-examples",
        default="paper_emnlp2026_industry/appendix_example_cards.tex",
    )
    parser.add_argument("--max-examples", type=int, default=16)
    args = parser.parse_args()

    prompts_path = Path(args.output_prompts)
    prompts_path.parent.mkdir(parents=True, exist_ok=True)
    prompts_path.write_text(render_prompt_contracts_tex(), encoding="utf-8")
    print(f"wrote {prompts_path}")

    examples = load_examples(args.examples)
    examples_path = Path(args.output_examples)
    examples_path.parent.mkdir(parents=True, exist_ok=True)
    examples_path.write_text(
        render_example_cards_tex(examples, max_examples=args.max_examples),
        encoding="utf-8",
    )
    print(f"wrote {examples_path}")


if __name__ == "__main__":
    main()
