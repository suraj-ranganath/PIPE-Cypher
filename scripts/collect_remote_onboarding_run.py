#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.models import DEFAULT_CATEGORIES
from pipecypher.onboarding_audit import build_onboarding_collection_manifest, redact_runtime_log
from pipecypher.remote_collection import (
    build_remote_find_runs_command,
    build_rsync_run_command,
    build_summary_metadata,
    parse_run_log_metadata,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch one completed enterprise graph onboarding run from ds-serv6 "
            "and write a sanitized aggregate snapshot."
        )
    )
    parser.add_argument("--host", default="suraj@ds-serv6.ucsd.edu")
    parser.add_argument("--remote-root", required=True)
    parser.add_argument("--run-prefix", required=True)
    parser.add_argument(
        "--run-dir-name",
        help="Exact remote artifacts/runs directory. If omitted, --run-prefix must match exactly one run.",
    )
    parser.add_argument("--target-per-category", type=int, required=True)
    parser.add_argument(
        "--expected-categories",
        default=",".join(DEFAULT_CATEGORIES),
        help="Comma-separated category list expected to reach the target.",
    )
    parser.add_argument("--graph-profile", required=True)
    parser.add_argument("--local-run-root", default="artifacts/runs")
    parser.add_argument("--snapshot-dir")
    parser.add_argument("--log-file")
    parser.add_argument("--generation-model")
    parser.add_argument("--judge-model")
    parser.add_argument("--code-revision")
    parser.add_argument("--run-seed")
    parser.add_argument("--config")
    parser.add_argument(
        "--metadata",
        action="append",
        default=[],
        help="Additional sanitized metadata as key=value.",
    )
    parser.add_argument("--python-bin", default=sys.executable)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    snapshot_dir = Path(args.snapshot_dir or f"experiments/snapshots/{args.run_prefix}")
    log_file = args.log_file or f"logs/{args.run_prefix}.log"
    log_text = _remote_cat(
        host=args.host,
        remote_root=args.remote_root,
        path=log_file,
        dry_run=args.dry_run,
    )
    parsed_log = parse_run_log_metadata(log_text)
    metadata = build_summary_metadata(
        run_prefix=args.run_prefix,
        log_file=log_file,
        parsed_log=parsed_log,
        generation_model=args.generation_model,
        judge_model=args.judge_model,
        code_revision=args.code_revision,
        run_seed=args.run_seed,
    )
    if args.config:
        metadata["config"] = args.config
    metadata.update(_parse_metadata(args.metadata))

    run_name = args.run_dir_name or _single_remote_run_name(
        host=args.host,
        remote_root=args.remote_root,
        run_prefix=args.run_prefix,
        dry_run=args.dry_run,
    )
    Path(args.local_run_root).mkdir(parents=True, exist_ok=True)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    if log_text and not args.dry_run:
        (snapshot_dir / "remote_run.log").write_text(redact_runtime_log(log_text), encoding="utf-8")

    _run(
        build_rsync_run_command(
            host=args.host,
            remote_root=args.remote_root,
            run_dir_name=run_name,
            local_run_root=args.local_run_root,
        ),
        dry_run=args.dry_run,
    )
    summary_cmd = [
        args.python_bin,
        "scripts/summarize_enterprise_onboarding_run.py",
        str(Path(args.local_run_root) / run_name),
        "--target-per-category",
        str(args.target_per_category),
        "--expected-categories",
        args.expected_categories,
        "--graph-profile",
        args.graph_profile,
        "--output-json",
        str(snapshot_dir / "onboarding_summary.json"),
        "--output-md",
        str(snapshot_dir / "onboarding_summary.md"),
    ]
    for key, value in metadata.items():
        if value:
            summary_cmd.extend(["--metadata", f"{key}={value}"])
    _run(summary_cmd, dry_run=args.dry_run)

    manifest_path = snapshot_dir / "collection_manifest.json"
    if args.dry_run:
        print("+ write", str(manifest_path))
        return

    manifest = build_onboarding_collection_manifest(
        host=args.host,
        remote_root=args.remote_root,
        run_prefix=args.run_prefix,
        snapshot_dir=snapshot_dir,
        local_run_root=args.local_run_root,
        run_name=run_name,
        metadata=metadata,
        log_file=log_file,
    )
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {manifest_path}")


def _remote_cat(*, host: str, remote_root: str, path: str, dry_run: bool) -> str:
    command = f"cd {remote_root!r} && cat {path!r} 2>/dev/null || true"
    if dry_run:
        print("+", "ssh", host, command)
        return ""
    return subprocess.check_output(["ssh", host, command], text=True)


def _single_remote_run_name(*, host: str, remote_root: str, run_prefix: str, dry_run: bool) -> str:
    command = build_remote_find_runs_command(remote_root=remote_root, run_prefix=run_prefix)
    if dry_run:
        print("+", "ssh", host, command)
        return f"DRY_RUN_{run_prefix}"
    text = subprocess.check_output(["ssh", host, command], text=True)
    names = [line.strip() for line in text.splitlines() if line.strip()]
    if not names:
        raise SystemExit(f"no remote run directories matched run_prefix={run_prefix!r}")
    if len(names) > 1:
        raise SystemExit(
            "run prefix matched multiple remote run directories; pass --run-dir-name: "
            + ", ".join(names)
        )
    return names[0]


def _run(command: list[str], *, dry_run: bool) -> None:
    if dry_run:
        print("+", " ".join(command))
        return
    subprocess.run(command, check=True)


def _parse_metadata(values: list[str]) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise SystemExit(f"--metadata must be key=value, got {item!r}")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise SystemExit("--metadata key cannot be empty")
        metadata[key] = value.strip()
    return metadata


if __name__ == "__main__":
    main()
