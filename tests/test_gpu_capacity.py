from __future__ import annotations

from pathlib import Path

from pipecypher.gpu_capacity import (
    build_capacity_report,
    capacity_report_to_markdown,
    model_safetensor_size_mib,
    parse_nvidia_smi_gpu_csv,
    required_gpu_count,
    safe_gpu_indices,
)


def test_parse_nvidia_smi_gpu_csv():
    rows = parse_nvidia_smi_gpu_csv(
        "0, NVIDIA RTX A5000, 100, 24564, 0\n"
        "1, NVIDIA RTX A5000, 2048, 24564, 50\n"
    )

    assert rows[0].index == 0
    assert rows[0].memory_used_mib == 100
    assert rows[1].utilization_gpu_pct == 50


def test_safe_gpu_indices_require_low_memory_and_utilization():
    rows = parse_nvidia_smi_gpu_csv(
        "0, NVIDIA RTX A5000, 100, 24564, 0\n"
        "1, NVIDIA RTX A5000, 2048, 24564, 0\n"
        "2, NVIDIA RTX A5000, 100, 24564, 99\n"
    )

    assert safe_gpu_indices(rows, max_used_mib=1024, max_utilization_pct=10) == [0]


def test_required_gpu_count_uses_weight_size_and_reserved_memory():
    assert (
        required_gpu_count(
            model_size_mib=68_000,
            memory_total_mib=24_564,
            gpu_memory_utilization=0.90,
            reserve_mib=2048,
        )
        == 4
    )


def test_build_capacity_report_from_fixture(tmp_path: Path):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "part-00001.safetensors").write_bytes(b"0" * 1024 * 1024)
    rows = parse_nvidia_smi_gpu_csv("0, NVIDIA RTX A5000, 1, 24564, 0\n")

    assert model_safetensor_size_mib(model_dir) == 1
    report = build_capacity_report(model_dir=model_dir, gpus=rows)

    assert report.required_gpu_count == 1
    assert report.safe_gpu_indices == [0]
    assert report.feasible is True
    assert "Feasible now" in capacity_report_to_markdown(report)
