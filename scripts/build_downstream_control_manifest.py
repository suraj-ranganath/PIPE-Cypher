#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.artifact_snapshot import sha256_file


ZERO_FILES = (
    "zero_shot_predictions.jsonl",
    "zero_shot_evaluation.jsonl",
    "zero_shot_summary.json",
)
CONTROL_FILES = (
    "few_shot_predictions.jsonl",
    "few_shot_evaluation.jsonl",
    "few_shot_selection.jsonl",
    "few_shot_summary.json",
    "metadata.json",
)
SNAPSHOT_FILES = (
    "fewshot_control_summary.json",
    "fewshot_control_summary.md",
    "fewshot_leakage_control_audit.json",
    "fewshot_leakage_control_audit.md",
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a readiness manifest for downstream few-shot control runs."
    )
    parser.add_argument("--evaluation-root", default="artifacts/evaluations")
    parser.add_argument(
        "--snapshot-dir",
        default="experiments/snapshots/20260604_clean_downstream_model_transfer",
    )
    parser.add_argument(
        "--zero-prefix",
        default="20260604_clean_downstream_",
        help="Optional prefix filter for zero/few-shot run directories.",
    )
    parser.add_argument(
        "--control-prefix",
        default="20260604_clean_control_",
        help="Prefix filter for few-shot control run directories.",
    )
    parser.add_argument("--expected-zero-runs", type=int, default=11)
    parser.add_argument("--expected-control-runs", type=int, default=45)
    parser.add_argument("--rows-per-run", type=int, default=296)
    parser.add_argument("--control-modes-per-model", type=int, default=4)
    parser.add_argument(
        "--exclude-run-substring",
        action="append",
        default=["stable_cypher_instruct3b_transformers"],
        help="Exclude known failed or intentionally omitted run directories containing this substring.",
    )
    parser.add_argument(
        "--output",
        default="experiments/snapshots/20260604_clean_downstream_model_transfer/downstream_control_manifest.json",
    )
    args = parser.parse_args()

    manifest = build_manifest(
        evaluation_root=Path(args.evaluation_root),
        snapshot_dir=Path(args.snapshot_dir),
        zero_prefix=args.zero_prefix,
        control_prefix=args.control_prefix,
        expected_zero_runs=args.expected_zero_runs,
        expected_control_runs=args.expected_control_runs,
        rows_per_run=args.rows_per_run,
        control_modes_per_model=args.control_modes_per_model,
        exclude_run_substrings=tuple(args.exclude_run_substring),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {output}")


def build_manifest(
    *,
    evaluation_root: Path,
    snapshot_dir: Path,
    zero_prefix: str = "",
    control_prefix: str = "20260603_control_",
    expected_zero_runs: int = 12,
    expected_control_runs: int = 60,
    rows_per_run: int = 296,
    control_modes_per_model: int = 5,
    exclude_run_substrings: tuple[str, ...] = (),
) -> dict[str, Any]:
    zero_dirs = sorted(
        path
        for path in evaluation_root.iterdir()
        if path.is_dir()
        and path.name.endswith("zero_fewshot")
        and (not zero_prefix or path.name.startswith(zero_prefix))
        and not _excluded(path.name, exclude_run_substrings)
    )
    control_dirs = sorted(
        path
        for path in evaluation_root.iterdir()
        if path.is_dir() and path.name.startswith(control_prefix)
        and not _excluded(path.name, exclude_run_substrings)
    )
    zero_runs = [_run_entry(path, ZERO_FILES, rows_per_run=rows_per_run) for path in zero_dirs]
    control_runs = [_run_entry(path, CONTROL_FILES, rows_per_run=rows_per_run) for path in control_dirs]
    issues = [
        issue
        for entry in [*zero_runs, *control_runs]
        for issue in entry.get("issues", [])
    ]
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_root": str(evaluation_root),
        "snapshot_dir": str(snapshot_dir),
        "filters": {
            "zero_prefix": zero_prefix,
            "control_prefix": control_prefix,
            "exclude_run_substrings": list(exclude_run_substrings),
        },
        "expected": {
            "zero_runs": expected_zero_runs,
            "control_runs": expected_control_runs,
            "rows_per_run": rows_per_run,
            "control_modes_per_model": control_modes_per_model,
        },
        "observed": {
            "zero_runs": len(zero_runs),
            "control_runs": len(control_runs),
            "all_complete": not issues
            and len(zero_runs) == expected_zero_runs
            and len(control_runs) == expected_control_runs,
        },
        "issues": issues,
        "zero_runs": zero_runs,
        "control_runs": control_runs,
        "snapshot_files": _file_entries(snapshot_dir, SNAPSHOT_FILES),
    }


def _run_entry(path: Path, expected_files: tuple[str, ...], *, rows_per_run: int) -> dict[str, Any]:
    files = _file_entries(path, expected_files)
    issues = []
    for name in expected_files:
        if name not in files:
            issues.append(f"{path.name}: missing {name}")
    for name, entry in files.items():
        if name.endswith(".jsonl") and entry.get("line_count") != rows_per_run:
            issues.append(f"{path.name}: {name} has {entry.get('line_count')} rows")
    return {
        "run_id": path.name,
        "path": str(path),
        "files": files,
        "issues": issues,
    }


def _excluded(name: str, substrings: tuple[str, ...]) -> bool:
    return any(substring and substring in name for substring in substrings)


def _file_entries(root: Path, names: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    entries = {}
    for name in names:
        path = root / name
        if not path.exists():
            continue
        entry: dict[str, Any] = {
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        if path.suffix == ".jsonl":
            entry["line_count"] = _line_count(path)
        entries[name] = entry
    return entries


def _line_count(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for _ in handle)


if __name__ == "__main__":
    main()
