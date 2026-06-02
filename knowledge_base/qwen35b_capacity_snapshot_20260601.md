# Qwen3.5-35B-A3B Capacity Snapshot

Date checked: June 2, 2026 00:33 UTC on ds-serv6.

Command:

```bash
python scripts/check_vllm_capacity.py --model-dir /home/suraj/pipecypher-models/Qwen3.5-35B-A3B --gpu-memory-utilization 0.90 --reserve-mib 2048 --remote --format json
```

Exit code: `2`. The capacity checker exits non-zero when `feasible=false`.

Tracked JSON evidence: `experiments/snapshots/qwen35b_capacity_20260601_latest.json`.

## Capacity Result

| Field | Value |
| --- | ---: |
| Staged safetensor size | 68,573 MiB |
| GPU memory utilization budget | 0.90 |
| Reserve MiB/GPU | 2,048 |
| Usable memory/GPU under budget | 20,059 MiB |
| Required A5000 GPUs | 4 |
| Safe GPUs | 1 (`3`) |
| Feasible now | no |

## GPU Snapshot

| GPU | Used MiB | Free MiB | Utilization | Interpretation |
| ---: | ---: | ---: | ---: | --- |
| 0 | 8,329 | 16,235 | 0% | memory occupied |
| 1 | 6,622 | 17,942 | 0% | memory occupied |
| 2 | 20,555 | 4,009 | 90% | high utilization |
| 3 | 1 | 24,563 | 0% | safe |
| 4 | 415 | 24,149 | 100% | high utilization |
| 5 | 415 | 24,149 | 100% | high utilization |
| 6 | 20,281 | 4,283 | 0% | memory occupied |
| 7 | 20,281 | 4,283 | 0% | memory occupied |

## Conclusion

The staged target model should not be launched under this snapshot: it requires 4 low-utilization A5000 GPUs under the conservative vLLM budget, but only 1 GPU is safe. Continue reporting live results as Qwen3.5-9B fallback evidence unless a later snapshot or tested quantized/offload serving configuration changes this constraint.
