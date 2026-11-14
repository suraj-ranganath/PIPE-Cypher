from __future__ import annotations

import csv
import json
import math
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GpuStatus:
    index: int
    name: str
    memory_used_mib: int
    memory_total_mib: int
    utilization_gpu_pct: int


@dataclass(frozen=True)
class VllmCapacityReport:
    model_dir: str
    model_size_mib: int
    gpu_memory_utilization: float
    reserve_mib: int
    per_gpu_usable_mib: int
    required_gpu_count: int
    safe_gpu_indices: list[int]
    safe_gpu_count: int
    feasible: bool


def model_safetensor_size_mib(model_dir: str | Path) -> int:
    path = Path(model_dir).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"model directory does not exist: {path}")
    total_bytes = sum(item.stat().st_size for item in path.rglob("*.safetensors") if item.is_file())
    if total_bytes == 0:
        raise ValueError(f"no .safetensors files found under: {path}")
    return math.ceil(total_bytes / (1024 * 1024))


def parse_nvidia_smi_gpu_csv(text: str) -> list[GpuStatus]:
    rows: list[GpuStatus] = []
    reader = csv.reader(line for line in text.splitlines() if line.strip())
    for raw in reader:
        if len(raw) != 5:
            raise ValueError(f"expected 5 nvidia-smi CSV columns, got {len(raw)}: {raw}")
        index, name, memory_used, memory_total, util = [item.strip() for item in raw]
        rows.append(
            GpuStatus(
                index=int(index),
                name=name,
                memory_used_mib=int(memory_used),
                memory_total_mib=int(memory_total),
                utilization_gpu_pct=int(util),
            )
        )
    return rows


def query_nvidia_smi() -> list[GpuStatus]:
    output = subprocess.check_output(
        [
            "nvidia-smi",
            "--query-gpu=index,name,memory.used,memory.total,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        text=True,
    )
    return parse_nvidia_smi_gpu_csv(output)


def safe_gpu_indices(
    gpus: list[GpuStatus],
    *,
    max_used_mib: int = 1024,
    max_utilization_pct: int = 10,
) -> list[int]:
    return [
        gpu.index
        for gpu in gpus
        if gpu.memory_used_mib <= max_used_mib and gpu.utilization_gpu_pct <= max_utilization_pct
    ]


def required_gpu_count(
    *,
    model_size_mib: int,
    memory_total_mib: int,
    gpu_memory_utilization: float = 0.90,
    reserve_mib: int = 2048,
) -> int:
    if not (0 < gpu_memory_utilization <= 1):
        raise ValueError("gpu_memory_utilization must be in (0, 1]")
    per_gpu_usable = math.floor(memory_total_mib * gpu_memory_utilization) - reserve_mib
    if per_gpu_usable <= 0:
        raise ValueError("reserve_mib leaves no usable GPU memory")
    return math.ceil(model_size_mib / per_gpu_usable)


def build_capacity_report(
    *,
    model_dir: str | Path,
    gpus: list[GpuStatus],
    gpu_memory_utilization: float = 0.90,
    reserve_mib: int = 2048,
    max_used_mib: int = 1024,
    max_utilization_pct: int = 10,
) -> VllmCapacityReport:
    if not gpus:
        raise ValueError("no GPU statuses provided")
    model_size = model_safetensor_size_mib(model_dir)
    # Use the smallest GPU in the candidate pool for a conservative TP estimate.
    memory_total = min(gpu.memory_total_mib for gpu in gpus)
    usable = math.floor(memory_total * gpu_memory_utilization) - reserve_mib
    required = required_gpu_count(
        model_size_mib=model_size,
        memory_total_mib=memory_total,
        gpu_memory_utilization=gpu_memory_utilization,
        reserve_mib=reserve_mib,
    )
    safe = safe_gpu_indices(
        gpus,
        max_used_mib=max_used_mib,
        max_utilization_pct=max_utilization_pct,
    )
    return VllmCapacityReport(
        model_dir=str(Path(model_dir).expanduser()),
        model_size_mib=model_size,
        gpu_memory_utilization=gpu_memory_utilization,
        reserve_mib=reserve_mib,
        per_gpu_usable_mib=usable,
        required_gpu_count=required,
        safe_gpu_indices=safe,
        safe_gpu_count=len(safe),
        feasible=len(safe) >= required,
    )


def capacity_report_to_json(report: VllmCapacityReport) -> str:
    return json.dumps(asdict(report), indent=2, sort_keys=True)


def capacity_report_to_markdown(report: VllmCapacityReport) -> str:
    safe = ", ".join(str(index) for index in report.safe_gpu_indices) or "none"
    feasible = "yes" if report.feasible else "no"
    return "\n".join(
        [
            "| Field | Value |",
            "|---|---:|",
            f"| Model size MiB | {report.model_size_mib} |",
            f"| GPU memory utilization | {report.gpu_memory_utilization:.2f} |",
            f"| Reserve MiB/GPU | {report.reserve_mib} |",
            f"| Usable MiB/GPU | {report.per_gpu_usable_mib} |",
            f"| Required GPUs | {report.required_gpu_count} |",
            f"| Safe GPUs | {report.safe_gpu_count} ({safe}) |",
            f"| Feasible now | {feasible} |",
        ]
    )


def gpu_statuses_to_dicts(gpus: list[GpuStatus]) -> list[dict[str, Any]]:
    return [asdict(gpu) for gpu in gpus]
