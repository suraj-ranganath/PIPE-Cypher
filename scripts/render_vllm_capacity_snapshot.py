#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def render_capacity_snapshot_markdown(
    snapshot: dict[str, Any],
    *,
    title: str,
    checked_at: str,
    command: str,
    exit_code: int,
    json_path: str,
) -> str:
    safe = ", ".join(str(index) for index in snapshot.get("safe_gpu_indices", [])) or "none"
    feasible = "yes" if snapshot.get("feasible") else "no"
    rows = [
        f"# {title}",
        "",
        f"Date checked: {checked_at}.",
        "",
        "Command:",
        "",
        "```bash",
        command,
        "```",
        "",
        f"Exit code: `{exit_code}`. The capacity checker exits non-zero when `feasible=false`.",
        "",
        f"Tracked JSON evidence: `{json_path}`.",
        "",
        "## Capacity Result",
        "",
        "| Field | Value |",
        "| --- | ---: |",
        f"| Staged safetensor size | {_fmt_int(snapshot['model_size_mib'])} MiB |",
        f"| GPU memory utilization budget | {float(snapshot['gpu_memory_utilization']):.2f} |",
        f"| Reserve MiB/GPU | {_fmt_int(snapshot['reserve_mib'])} |",
        f"| Usable memory/GPU under budget | {_fmt_int(snapshot['per_gpu_usable_mib'])} MiB |",
        f"| Required A5000 GPUs | {_fmt_int(snapshot['required_gpu_count'])} |",
        f"| Safe GPUs | {_fmt_int(snapshot['safe_gpu_count'])} (`{safe}`) |",
        f"| Feasible now | {feasible} |",
        "",
        "## GPU Snapshot",
        "",
        "| GPU | Used MiB | Free MiB | Utilization | Interpretation |",
        "| ---: | ---: | ---: | ---: | --- |",
    ]
    for gpu in snapshot.get("gpus", []):
        total = int(gpu["memory_total_mib"])
        used = int(gpu["memory_used_mib"])
        util = int(gpu["utilization_gpu_pct"])
        rows.append(
            "| {index} | {used} | {free} | {util}% | {meaning} |".format(
                index=gpu["index"],
                used=_fmt_int(used),
                free=_fmt_int(total - used),
                util=util,
                meaning=_gpu_interpretation(used, util),
            )
        )
    rows.extend(
        [
            "",
            "## Conclusion",
            "",
            _conclusion(snapshot),
            "",
        ]
    )
    return "\n".join(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render a Markdown evidence note from check_vllm_capacity JSON output."
    )
    parser.add_argument("--snapshot-json", required=True)
    parser.add_argument("--output-md", required=True)
    parser.add_argument("--title", default="Qwen3.5-35B-A3B Capacity Snapshot")
    parser.add_argument("--checked-at", required=True)
    parser.add_argument("--command", required=True)
    parser.add_argument("--exit-code", type=int, required=True)
    parser.add_argument(
        "--json-path",
        default="experiments/snapshots/qwen35b_capacity_20260601_latest.json",
        help="Repository-relative path to cite in the generated note.",
    )
    args = parser.parse_args()

    snapshot = json.loads(Path(args.snapshot_json).read_text(encoding="utf-8"))
    output = Path(args.output_md)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_capacity_snapshot_markdown(
            snapshot,
            title=args.title,
            checked_at=args.checked_at,
            command=args.command,
            exit_code=args.exit_code,
            json_path=args.json_path,
        ),
        encoding="utf-8",
    )
    print(f"wrote {output}")


def _gpu_interpretation(used_mib: int, utilization_pct: int) -> str:
    if used_mib <= 1024 and utilization_pct <= 10:
        return "safe"
    if utilization_pct > 10:
        return "high utilization"
    return "memory occupied"


def _conclusion(snapshot: dict[str, Any]) -> str:
    if snapshot.get("feasible"):
        safe = ", ".join(str(index) for index in snapshot.get("safe_gpu_indices", []))
        return (
            "The staged model has enough currently safe GPUs under the conservative "
            f"serving budget. Candidate GPUs: `{safe}`. Launch only after checking "
            "that no active ablation or user workload depends on those GPUs."
        )
    required = int(snapshot.get("required_gpu_count", 0))
    safe_count = int(snapshot.get("safe_gpu_count", 0))
    gpu_word = "GPU is" if safe_count == 1 else "GPUs are"
    return (
        "The staged target model should not be launched under this snapshot: "
        f"it requires {required} low-utilization A5000 GPUs under the conservative "
        f"vLLM budget, but only {safe_count} {gpu_word} safe. Treat this as an "
        "internal serving-capacity note, not as paper-facing fallback evidence."
    )


def _fmt_int(value: int | float) -> str:
    return f"{int(value):,}"


if __name__ == "__main__":
    try:
        main()
    except KeyError as exc:
        raise SystemExit(f"snapshot missing required key: {exc}") from exc
