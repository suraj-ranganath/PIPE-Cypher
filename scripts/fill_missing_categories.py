#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.config import load_config
from pipecypher.io import read_jsonl
from pipecypher.pipeline import question_key


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Launch category-specific top-up runs for an incomplete PIPE-Cypher run."
    )
    parser.add_argument("--config", required=True, help="Base config used for the original run.")
    parser.add_argument(
        "--records",
        nargs="+",
        required=True,
        help="Existing run directories or records.jsonl files to count accepted examples from.",
    )
    parser.add_argument(
        "--run-prefix",
        default=f"fill_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        help="Prefix for generated run names and temporary config files.",
    )
    parser.add_argument("--python-bin", default=sys.executable)
    parser.add_argument("--output-config-dir", default="")
    parser.add_argument(
        "--passes",
        type=int,
        default=1,
        help="Maximum number of fill passes. Later passes count earlier top-up outputs.",
    )
    parser.add_argument("--offline-smoke", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cfg = load_config(args.config)
    source_data = _load_yaml_mapping(Path(args.config))
    if args.passes < 1:
        raise ValueError("--passes must be >= 1")

    config_dir = (
        Path(args.output_config_dir)
        if args.output_config_dir
        else Path(cfg.paths.artifact_dir) / "fill_configs" / args.run_prefix
    )
    config_dir.mkdir(parents=True, exist_ok=True)

    records_for_counts = [str(path) for path in args.records]
    for pass_idx in range(1, args.passes + 1):
        counts = accepted_by_category(records_for_counts)
        missing = missing_by_category(
            counts=counts,
            categories=cfg.generation.categories,
            target_per_category=cfg.generation.target_per_category,
        )
        payload = {
            "accepted_by_category": dict(sorted(counts.items())),
            "missing_by_category": missing,
            "pass": pass_idx,
            "target_per_category": cfg.generation.target_per_category,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        if not missing:
            return

        for category, needed in missing.items():
            run_name = fill_run_name(args.run_prefix, category=category, pass_idx=pass_idx)
            config_path = config_dir / f"{run_name}.yaml"
            config_data = patched_config_for_category(source_data, category=category, target=needed)
            config_path.write_text(yaml.safe_dump(config_data, sort_keys=False), encoding="utf-8")
            command = [
                args.python_bin,
                "scripts/run_pipeline.py",
                "--config",
                str(config_path),
                "--run-name",
                run_name,
            ]
            if records_for_counts:
                command.append("--seen-records")
                command.extend(records_for_counts)
            if args.offline_smoke:
                command.append("--offline-smoke")
            print(" ".join(command))
            if not args.dry_run:
                subprocess.run(command, check=True)
                records_for_counts.append(
                    str(latest_run_dir(Path(cfg.paths.artifact_dir) / "runs", run_name))
                )


def _records_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_dir():
        return candidate / "records.jsonl"
    return candidate


def accepted_by_category(paths: list[str] | tuple[str, ...]) -> Counter[str]:
    counts: Counter[str] = Counter()
    seen: set[tuple[str, str, str]] = set()
    for raw_path in paths:
        records_path = _records_path(raw_path)
        if not records_path.exists():
            raise FileNotFoundError(f"records file not found: {records_path}")
        for record in read_jsonl(records_path):
            if not (record.get("accepted") and record.get("category") and record.get("question")):
                continue
            key = (
                str(record.get("graph_profile", "")),
                *question_key(str(record["category"]), str(record["question"])),
            )
            if key in seen:
                continue
            seen.add(key)
            counts[str(record["category"])] += 1
    return counts


def missing_by_category(
    *,
    counts: Counter[str],
    categories: list[str],
    target_per_category: int,
) -> dict[str, int]:
    return {
        category: target_per_category - counts.get(category, 0)
        for category in categories
        if counts.get(category, 0) < target_per_category
    }


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config YAML must be a mapping: {path}")
    return data


def patched_config_for_category(
    source_data: dict[str, Any],
    *,
    category: str,
    target: int,
) -> dict[str, Any]:
    data = copy.deepcopy(source_data)
    generation = data.setdefault("generation", {})
    if not isinstance(generation, dict):
        raise ValueError("generation config must be a mapping")
    generation["categories"] = [category]
    generation["target_per_category"] = int(target)
    return data


def fill_run_name(run_prefix: str, *, category: str, pass_idx: int) -> str:
    if pass_idx == 1:
        return f"{run_prefix}_{category}"
    return f"{run_prefix}_pass{pass_idx}_{category}"


def latest_run_dir(runs_dir: Path, run_name: str) -> Path:
    matches = sorted(path for path in runs_dir.glob(f"*_{run_name}") if path.is_dir())
    if not matches:
        raise FileNotFoundError(f"no run directory found for run name: {run_name}")
    return matches[-1]


if __name__ == "__main__":
    main()
