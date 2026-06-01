# Qwen3.5-35B-A3B Capacity Snapshot

Date checked: June 1, 2026 18:32 UTC on `ds-serv6`.

Command:

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

GPU snapshot:

| GPU | Used MiB | Free MiB | Utilization | Interpretation |
| ---: | ---: | ---: | ---: | --- |
| 0 | 8,329 | 15,784 | 0% | memory occupied |
| 1 | 6,622 | 17,492 | 0% | memory occupied |
| 2 | 20,555 | 3,558 | 0% | occupied by Qwen3.5-9B/vLLM stack |
| 3 | 1 | 24,112 | 0% | safe |
| 4 | 415 | 23,698 | 100% | high utilization |
| 5 | 415 | 23,698 | 100% | high utilization |
| 6 | 20,281 | 3,832 | 0% | memory occupied |
| 7 | 20,281 | 3,832 | 0% | memory occupied |

Conclusion: the target 35B model remains staged but should not be launched until at least four low-utilization A5000 GPUs are available, or until a tested quantized/offload serving configuration is added. The current full benchmark and downstream evidence should continue to be reported as Qwen3.5-9B fallback results.
