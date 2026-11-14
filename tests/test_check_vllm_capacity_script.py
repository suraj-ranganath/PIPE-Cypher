from argparse import Namespace

from scripts.check_vllm_capacity import build_remote_command


def test_build_remote_command_wraps_capacity_check_over_ssh():
    command = build_remote_command(
        Namespace(
            host="user@gpu-host",
            remote_project_root="/home/user/PIPE-Cypher",
            remote_python="/home/user/pipecypher-tools/runtime-venv/bin/python",
            model_dir="/home/user/pipecypher-models/Qwen3.5-35B-A3B",
            gpu_memory_utilization=0.9,
            reserve_mib=2048,
            max_used_mib=1024,
            max_utilization_pct=10,
            format="json",
            gpu_csv="",
        )
    )

    assert command[:5] == ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8"]
    assert command[5] == "user@gpu-host"
    assert "cd /home/user/PIPE-Cypher" in command[6]
    assert "scripts/check_vllm_capacity.py" in command[6]
    assert "--remote" not in command[6]
    assert "--format json" in command[6]
