from __future__ import annotations

import shlex
from pathlib import Path


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
    return "cd {root} && find artifacts/runs -maxdepth 1 -type d -name {pattern} -printf '%f\\n' | sort".format(
        root=shlex.quote(remote_root),
        pattern=shlex.quote(pattern),
    )


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

