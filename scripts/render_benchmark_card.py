#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.benchmark_card import render_benchmark_card


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render a redacted benchmark card for a PIPE-Cypher run or export"
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--records", help="Run directory or records.jsonl file")
    parser.add_argument("--benchmark-dir", help="Benchmark export directory with manifest/stats")
    parser.add_argument("--title", default="PIPE-Cypher Benchmark Card")
    parser.add_argument("--output", help="Markdown output path. Defaults to stdout.")
    args = parser.parse_args(argv)

    card = render_benchmark_card(
        config_path=args.config,
        records_path=args.records,
        benchmark_dir=args.benchmark_dir,
        title=args.title,
    )
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(card + "\n", encoding="utf-8")
    else:
        print(card)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
