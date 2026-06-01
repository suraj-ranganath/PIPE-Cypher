from __future__ import annotations

import json
import shlex
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipecypher.artifact_snapshot import sha256_file


LOG_METADATA_KEYS = {
    "run_prefix",
    "target_per_category",
    "generation_model",
    "judge_model",
    "code_revision",
    "summary_dir",
}


def parse_run_log_metadata(text: str) -> dict[str, str]:
    """Extract top-level KEY=VALUE metadata emitted by live run scripts."""

    metadata: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in LOG_METADATA_KEYS and key not in metadata:
            metadata[key] = value.strip()
    return metadata


def build_remote_find_runs_command(*, remote_root: str, run_prefix: str) -> str:
    pattern = f"*{run_prefix}*"
    return (
        "cd {root} || exit 2; "
        "[ -d artifacts/runs ] || exit 0; "
        "find artifacts/runs -maxdepth 1 -type d -name {pattern} -printf '%f\\n' | sort"
    ).format(root=shlex.quote(remote_root), pattern=shlex.quote(pattern))


def build_tmux_has_session_command(session: str) -> str:
    return f"tmux has-session -t {shlex.quote(session)}"


def build_remote_ablation_status_command(*, remote_root: str, run_prefix: str) -> str:
    pattern = f"*{run_prefix}*"
    return (
        "cd {root} || exit 2; "
        "[ -d artifacts/runs ] || exit 0; "
        "for d in $(find artifacts/runs -maxdepth 1 -type d -name {pattern} | sort); do "
        "records=0; "
        "if [ -f \"$d/records.jsonl\" ]; then records=$(wc -l < \"$d/records.jsonl\"); fi; "
        "summary=no; "
        "if [ -f \"$d/summary.txt\" ]; then summary=yes; fi; "
        "printf '%s\\t%s\\t%s\\n' \"$(basename \"$d\")\" \"$records\" \"$summary\"; "
        "done"
    ).format(root=shlex.quote(remote_root), pattern=shlex.quote(pattern))


def parse_remote_ablation_status_rows(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        run, records, summary = parts
        rows.append(
            {
                "run": run,
                "records": int(records),
                "summary_present": summary == "yes",
            }
        )
    return rows


def build_rsync_run_command(
    *,
    host: str,
    remote_root: str,
    run_dir_name: str,
    local_run_root: str | Path,
) -> list[str]:
    remote_path = f"{remote_root.rstrip('/')}/artifacts/runs/{run_dir_name}/"
    return [
        "rsync",
        "-a",
        f"{host}:{shlex.quote(remote_path)}",
        str(Path(local_run_root) / run_dir_name),
    ]


def build_summary_metadata(
    *,
    run_prefix: str,
    log_file: str,
    parsed_log: dict[str, str],
    generation_model: str | None = None,
    judge_model: str | None = None,
    code_revision: str | None = None,
) -> dict[str, str]:
    return {
        "run_prefix": run_prefix,
        "generation_model": generation_model or parsed_log.get("generation_model", ""),
        "judge_model": judge_model or parsed_log.get("judge_model", ""),
        "code_revision": code_revision or parsed_log.get("code_revision", ""),
        "log_file": log_file,
    }


def build_collection_manifest(
    *,
    host: str,
    remote_root: str,
    run_prefix: str,
    target_per_category: int,
    category_count: int,
    snapshot_dir: str | Path,
    local_run_root: str | Path,
    run_names: list[str],
    metadata: dict[str, str],
    log_file: str,
    render_paper: bool,
    paper_dir: str | Path,
    collected_at: str | None = None,
) -> dict[str, Any]:
    snapshot_path = Path(snapshot_dir)
    run_root = Path(local_run_root)
    paper_path = Path(paper_dir)
    manifest = {
        "collected_at": collected_at or datetime.now(timezone.utc).isoformat(),
        "host": host,
        "remote_root": remote_root,
        "run_prefix": run_prefix,
        "target_per_category": target_per_category,
        "category_count": category_count,
        "metadata": dict(sorted(metadata.items())),
        "remote_log_file": log_file,
        "run_count": len(run_names),
        "runs": {
            run_name: _checksums_for_paths(
                run_root / run_name,
                ["records.jsonl", "summary.txt"],
            )
            for run_name in sorted(run_names)
        },
        "snapshot_files": _checksums_for_paths(
            snapshot_path,
            [
                "remote_run.log",
                "ablation_suite_summary.json",
                "ablation_suite_summary.md",
                "ablation_suite_summary.csv",
                "ablation_suite_audit.json",
                "ablation_suite_audit.md",
            ],
        ),
        "paper_files": (
            _checksums_for_paths(
                paper_path,
                [
                    "tables_ablation_results.tex",
                    "tables_ablation_quality.tex",
                    f"figures/ablation_suite_target{target_per_category}.pdf",
                ],
            )
            if render_paper
            else {}
        ),
    }
    return manifest


def write_collection_manifest(manifest: dict[str, Any], path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _checksums_for_paths(base: Path, names: list[str]) -> dict[str, dict[str, Any]]:
    checksums: dict[str, dict[str, Any]] = {}
    for name in names:
        path = base / name
        if path.exists() and path.is_file():
            checksums[name] = {
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
    return checksums
