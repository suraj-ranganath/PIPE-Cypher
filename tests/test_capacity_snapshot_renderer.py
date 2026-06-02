from __future__ import annotations

from scripts.render_vllm_capacity_snapshot import render_capacity_snapshot_markdown


def test_render_capacity_snapshot_marks_infeasible_35b_serving():
    text = render_capacity_snapshot_markdown(
        _snapshot(feasible=False, safe_gpu_indices=[3]),
        title="Qwen3.5-35B-A3B Capacity Snapshot",
        checked_at="June 2, 2026 00:30 UTC on ds-serv6",
        command="python scripts/check_vllm_capacity.py --remote --format json",
        exit_code=2,
        json_path="experiments/snapshots/qwen35b_capacity_20260601_latest.json",
    )

    assert "Qwen3.5-35B-A3B Capacity Snapshot" in text
    assert "| Required A5000 GPUs | 4 |" in text
    assert "| Safe GPUs | 1 (`3`) |" in text
    assert "should not be launched" in text
    assert "high utilization" in text
    assert "memory occupied" in text
    assert "safe" in text


def test_render_capacity_snapshot_marks_feasible_serving():
    text = render_capacity_snapshot_markdown(
        _snapshot(feasible=True, safe_gpu_indices=[0, 1, 2, 3]),
        title="Capacity",
        checked_at="June 2, 2026",
        command="check",
        exit_code=0,
        json_path="snapshot.json",
    )

    assert "| Feasible now | yes |" in text
    assert "Candidate GPUs: `0, 1, 2, 3`" in text


def _snapshot(*, feasible: bool, safe_gpu_indices: list[int]) -> dict:
    return {
        "feasible": feasible,
        "gpu_memory_utilization": 0.9,
        "gpus": [
            {
                "index": 0,
                "memory_total_mib": 24564,
                "memory_used_mib": 8329,
                "name": "NVIDIA RTX A5000",
                "utilization_gpu_pct": 0,
            },
            {
                "index": 1,
                "memory_total_mib": 24564,
                "memory_used_mib": 415,
                "name": "NVIDIA RTX A5000",
                "utilization_gpu_pct": 100,
            },
            {
                "index": 3,
                "memory_total_mib": 24564,
                "memory_used_mib": 1,
                "name": "NVIDIA RTX A5000",
                "utilization_gpu_pct": 0,
            },
        ],
        "model_dir": "/home/suraj/pipecypher-models/Qwen3.5-35B-A3B",
        "model_size_mib": 68573,
        "per_gpu_usable_mib": 20059,
        "required_gpu_count": 4,
        "reserve_mib": 2048,
        "safe_gpu_count": len(safe_gpu_indices),
        "safe_gpu_indices": safe_gpu_indices,
    }
