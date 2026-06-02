# Qwen3.5-35B-A3B Capacity Snapshot

Date checked: June 2, 2026 00:00 UTC on `ds-serv6`.

Remote command from the local repo:

```bash
python scripts/check_vllm_capacity.py \
  --model-dir /home/suraj/pipecypher-models/Qwen3.5-35B-A3B \
  --gpu-memory-utilization 0.90 \
  --reserve-mib 2048 \
  --remote \
  --format json
```

The command exits with status 2 when serving is not feasible. The latest tracked
JSON output is:

```text
experiments/snapshots/qwen35b_capacity_20260601_latest.json
```

Equivalent command from an SSH session on `ds-serv6`:

```bash
cd /home/suraj/PIPE-Cypher
/home/suraj/pipecypher-tools/runtime-venv/bin/python scripts/check_vllm_capacity.py \
  --model-dir /home/suraj/pipecypher-models/Qwen3.5-35B-A3B \
  --gpu-memory-utilization 0.90 \
  --reserve-mib 2048 \
  --format json
```

Capacity result:

| Field | Value |
| --- | ---: |
| Staged safetensor size | 68,573 MiB |
| Usable memory/GPU under budget | 20,059 MiB |
| Required A5000 GPUs | 4 |
| Safe GPUs | 1 (`3`) |
| Feasible now | no |

Latest local-to-remote check status: exit code 2, because `feasible=false`.

GPU snapshot:

| GPU | Used MiB | Free MiB | Utilization | Interpretation |
| ---: | ---: | ---: | ---: | --- |
| 0 | 8,329 | 15,784 | 0% | memory occupied |
| 1 | 6,622 | 17,492 | 0% | memory occupied |
| 2 | 20,555 | 3,558 | 90% | occupied by the active Qwen3.5-9B/vLLM ablation stack |
| 3 | 1 | 24,112 | 0% | safe |
| 4 | 415 | 23,698 | 100% | high utilization |
| 5 | 415 | 23,698 | 100% | high utilization |
| 6 | 20,281 | 3,832 | 0% | memory occupied |
| 7 | 20,281 | 3,832 | 0% | memory occupied |

Conclusion: the target 35B model remains staged but should not be launched until at least four low-utilization A5000 GPUs are available, or until a tested quantized/offload serving configuration is added. The current full benchmark and downstream evidence should continue to be reported as Qwen3.5-9B fallback results.
