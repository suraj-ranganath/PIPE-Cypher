#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.gpu_capacity import (
    build_capacity_report,
    capacity_report_to_json,
    capacity_report_to_markdown,
    gpu_statuses_to_dicts,
    parse_nvidia_smi_gpu_csv,
    query_nvidia_smi,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Estimate whether a staged model can be served with vLLM on currently safe GPUs."
    )
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.90)
    parser.add_argument("--reserve-mib", type=int, default=2048)
    parser.add_argument("--max-used-mib", type=int, default=1024)
    parser.add_argument("--max-utilization-pct", type=int, default=10)
    parser.add_argument(
        "--gpu-csv",
        default="",
        help="Optional path to nvidia-smi CSV fixture for offline checks.",
    )
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    args = parser.parse_args()

    if args.gpu_csv:
        gpus = parse_nvidia_smi_gpu_csv(Path(args.gpu_csv).read_text(encoding="utf-8"))
    else:
        gpus = query_nvidia_smi()

    report = build_capacity_report(
        model_dir=args.model_dir,
        gpus=gpus,
        gpu_memory_utilization=args.gpu_memory_utilization,
        reserve_mib=args.reserve_mib,
        max_used_mib=args.max_used_mib,
        max_utilization_pct=args.max_utilization_pct,
    )
    if args.format == "json":
        payload = json.loads(capacity_report_to_json(report))
        payload["gpus"] = gpu_statuses_to_dicts(gpus)
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(capacity_report_to_markdown(report))
        print("\nGPU snapshot:")
        print("| GPU | Used MiB | Total MiB | Util % | Name |")
        print("|---:|---:|---:|---:|---|")
        for gpu in gpus:
            print(
                f"| {gpu.index} | {gpu.memory_used_mib} | {gpu.memory_total_mib} | "
                f"{gpu.utilization_gpu_pct} | {gpu.name} |"
            )
    if not report.feasible:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
