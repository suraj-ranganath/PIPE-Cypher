#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.experiments import summarize_records_path
from pipecypher.io import read_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor a PIPE-Cypher records.jsonl run")
    parser.add_argument("records", help="Run directory or records.jsonl path")
    parser.add_argument("--target-per-category", type=int, default=0)
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args()

    records_path = _records_path(args.records)
    if not records_path.exists():
        raise SystemExit(f"records file not found: {records_path}")
    summary = summarize_records_path(records_path)
    rows = read_jsonl(records_path)
    latest = rows[-1] if rows else {}
    payload = {
        "summary": summary,
        "latest": {
            "category": latest.get("category"),
            "accepted": latest.get("accepted"),
            "question": latest.get("question"),
            "judge_failure_reason": latest.get("judge", {}).get("failure_reason", ""),
        },
        "coverage": _coverage(summary.get("accepted_by_category", {}), args.target_per_category),
    }
    if args.format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(f"records={summary['records']} accepted={summary['accepted']} accept_rate={summary['accept_rate']:.3f}")
    print("accepted_by_category=" + json.dumps(summary["accepted_by_category"], sort_keys=True))
    if args.target_per_category:
        print("coverage=" + json.dumps(payload["coverage"], sort_keys=True))
    if payload["latest"]["question"]:
        print("latest=" + json.dumps(payload["latest"], sort_keys=True))


def _records_path(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_dir():
        return candidate / "records.jsonl"
    return candidate


def _coverage(counts: dict[str, int], target: int) -> dict[str, str]:
    if target <= 0:
        return {}
    return {category: f"{count}/{target}" for category, count in sorted(counts.items())}


if __name__ == "__main__":
    main()
