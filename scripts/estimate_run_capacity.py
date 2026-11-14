#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.config import load_config
from pipecypher.run_estimate import estimate_run_capacity, format_run_estimate_markdown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Estimate candidate attempts, LLM calls, and rough token load for a run config"
    )
    parser.add_argument("--config", required=True)
    parser.add_argument(
        "--target-per-category",
        type=int,
        help="Optional launch-scale override for generation.target_per_category.",
    )
    parser.add_argument("--assumed-accept-rate", type=float, default=0.25)
    parser.add_argument(
        "--llm-calls-per-minute",
        type=float,
        help="Optional calibrated endpoint throughput for rough wall-clock estimates",
    )
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    args = parser.parse_args(argv)

    config = load_config(args.config, strict=True, validate=True)
    if args.target_per_category is not None:
        if args.target_per_category <= 0:
            raise SystemExit("--target-per-category must be > 0")
        config.generation.target_per_category = args.target_per_category
    estimate = estimate_run_capacity(
        config,
        assumed_accept_rate=args.assumed_accept_rate,
        llm_calls_per_minute=args.llm_calls_per_minute,
    )
    if args.format == "json":
        print(json.dumps(estimate, indent=2, sort_keys=True))
    else:
        print(format_run_estimate_markdown(estimate))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
