#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.model_availability import (
    check_models,
    format_model_availability_json,
    format_model_availability_markdown,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Check local and optional Hugging Face model availability")
    parser.add_argument(
        "--model",
        action="append",
        default=[],
        help="Model ID to check. May be repeated.",
    )
    parser.add_argument(
        "--cache-root",
        default="~/.cache/huggingface/hub",
        help="Hugging Face hub cache root.",
    )
    parser.add_argument("--remote", action="store_true", help="Check Hugging Face model metadata too")
    parser.add_argument("--timeout-sec", type=int, default=20)
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    args = parser.parse_args()

    models = args.model or [
        "Qwen/Qwen3.5-35B-A3B",
        "Qwen/Qwen3.5-9B",
        "BAAI/bge-m3",
    ]
    rows = check_models(
        models,
        cache_root=args.cache_root,
        check_remote=args.remote,
        timeout_sec=args.timeout_sec,
    )
    if args.format == "json":
        print(format_model_availability_json(rows))
    else:
        print(format_model_availability_markdown(rows))


if __name__ == "__main__":
    main()
