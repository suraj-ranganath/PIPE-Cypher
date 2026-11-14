#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.provenance import (
    DEFAULT_APPROVED_MODELS,
    file_manifest,
    model_provenance_from_records,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a checksum and model-provenance manifest for paper-facing evidence."
    )
    parser.add_argument("--name", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--records",
        nargs="*",
        action="append",
        default=[],
        help="Record directories or records.jsonl paths. May be supplied multiple times.",
    )
    parser.add_argument("--artifact", action="append", default=[])
    parser.add_argument("--approved-model", action="append", default=[])
    parser.add_argument("--note", action="append", default=[])
    args = parser.parse_args()

    approved = set(args.approved_model or DEFAULT_APPROVED_MODELS)
    manifest = build_evidence_manifest(
        name=args.name,
        records=[Path(path) for path in _flatten(args.records)],
        artifacts=[Path(path) for path in args.artifact],
        approved_models=approved,
        notes=args.note,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {output}")
    if not manifest["paper_ready"]:
        raise SystemExit(1)


def build_evidence_manifest(
    *,
    name: str,
    records: list[Path],
    artifacts: list[Path],
    approved_models: set[str],
    notes: list[str] | None = None,
) -> dict[str, object]:
    artifact_files = _expand_artifacts(artifacts)
    model_report = (
        model_provenance_from_records(records, approved_models=approved_models)
        if records
        else {"pass": True, "records": 0, "model_counts": {}, "disallowed_model_counts": {}}
    )
    missing_artifacts = [str(path) for path in artifacts if not path.exists()]
    paper_ready = not missing_artifacts and bool(model_report.get("pass", False))
    return {
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "code_revision": _git_revision(),
        "approved_models": sorted(approved_models),
        "records": [str(path) for path in records],
        "artifacts": [str(path) for path in artifacts],
        "missing_artifacts": missing_artifacts,
        "artifact_files": file_manifest(artifact_files, root=PROJECT_ROOT),
        "model_provenance": model_report,
        "notes": notes or [],
        "paper_ready": paper_ready,
    }


def _expand_artifacts(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(sorted(child for child in path.rglob("*") if child.is_file()))
    return files


def _flatten(groups: list[list[str]]) -> list[str]:
    return [item for group in groups for item in group]


def _git_revision() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


if __name__ == "__main__":
    main()
