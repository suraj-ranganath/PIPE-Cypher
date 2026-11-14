#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.models import DEFAULT_CATEGORIES
from pipecypher.onboarding_audit import (
    render_onboarding_summary_markdown,
    summarize_onboarding_records_path,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Render a sanitized aggregate summary for one enterprise graph "
            "onboarding generation run."
        )
    )
    parser.add_argument("records_or_run_dir")
    parser.add_argument("--target-per-category", type=int, required=True)
    parser.add_argument(
        "--expected-categories",
        default=",".join(DEFAULT_CATEGORIES),
        help="Comma-separated category list expected to reach the target.",
    )
    parser.add_argument("--graph-profile", default="")
    parser.add_argument(
        "--metadata",
        action="append",
        default=[],
        help="Run metadata as key=value. Use for model IDs, seed, code revision, and config.",
    )
    parser.add_argument("--output-json")
    parser.add_argument("--output-md")
    args = parser.parse_args()

    summary = summarize_onboarding_records_path(
        args.records_or_run_dir,
        target_per_category=args.target_per_category,
        expected_categories=_split_csv(args.expected_categories),
        graph_profile=args.graph_profile,
        metadata=_parse_metadata(args.metadata),
    )
    payload = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    if args.output_json:
        _write(args.output_json, payload)
    else:
        print(payload, end="")
    if args.output_md:
        _write(args.output_md, render_onboarding_summary_markdown(summary))


def _split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _parse_metadata(values: list[str]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for item in values:
        if "=" not in item:
            raise SystemExit(f"--metadata must be key=value, got {item!r}")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise SystemExit("--metadata key cannot be empty")
        metadata[key] = value.strip()
    return metadata


def _write(path: str | Path, text: str) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
