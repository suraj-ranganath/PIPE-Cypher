# Model Availability

Date: June 1, 2026.

Command run on `ds-serv6`:

```bash
/home/suraj/pipecypher-tools/runtime-venv/bin/python scripts/check_model_availability.py \
  --model Qwen/Qwen3.5-35B-A3B \
  --model Qwen/Qwen3.5-9B \
  --model BAAI/bge-m3 \
  --remote \
  --timeout-sec 30 \
  --format markdown
```

Result:

| Model | Cached | Snapshots | Remote | Gated/private | Safetensors |
| --- | ---: | ---: | --- | --- | ---: |
| `Qwen/Qwen3.5-35B-A3B` | no | 0 | yes |  | 14 |
| `Qwen/Qwen3.5-9B` | yes | 1 | yes |  | 4 |
| `BAAI/bge-m3` | yes | 2 | yes |  | 0 |

Interpretation:

- `Qwen/Qwen3.5-35B-A3B` remains the target generation/judge model for full-quality experiments. It is not in the default Hugging Face cache, but it has now been staged under `/home/suraj/pipecypher-models/Qwen3.5-35B-A3B`.
- `Qwen/Qwen3.5-9B` is the current local fallback model and has been used for live engineering checks, the full 3,000-example fallback benchmark, and downstream Text2Cypher evaluation so far.
- `BAAI/bge-m3` is cached for local retrieval/embedding work.
- `/data` currently has only about 1.1T free, while `/` has about 11T free. Stage large model weights under home/root-backed storage unless `/data` is cleaned.

The full-generation runner supports either target or fallback models through environment overrides:

```bash
# Fallback full run using the currently served 9B endpoint.
SESSION=pipecypher_full_qwen9b \
RUN_PREFIX=20260601_full_qwen9b \
GENERATION_MODEL=Qwen/Qwen3.5-9B \
JUDGE_MODEL=Qwen/Qwen3.5-9B \
scripts/launch_live_full_generation_tmux.sh

# Target full run after serving/staging Qwen3.5-35B-A3B.
SESSION=pipecypher_full_qwen35b \
RUN_PREFIX=20260601_full_qwen35b \
GENERATION_MODEL=Qwen/Qwen3.5-35B-A3B \
JUDGE_MODEL=Qwen/Qwen3.5-35B-A3B \
scripts/launch_live_full_generation_tmux.sh
```

## Staging 35B-A3B

A dry-run check on June 1, 2026 showed 14 safetensor shards totaling roughly 72GB, which fits the root-backed storage plan. Stage the target model in a detached remote session with:

```bash
cd /home/suraj/PIPE-Cypher
mkdir -p logs
tmux new -d -s pipecypher_stage_qwen35b \
  'MODEL=Qwen/Qwen3.5-35B-A3B LOCAL_DIR=/home/suraj/pipecypher-models/Qwen3.5-35B-A3B bash scripts/stage_qwen35b_model.sh 2>&1 | tee logs/qwen35b_stage.log'
```

Monitor with:

```bash
tail -f /home/suraj/PIPE-Cypher/logs/qwen35b_stage.log
du -sh /home/suraj/pipecypher-models/Qwen3.5-35B-A3B
```

Observed completion:

```text
tmux session: pipecypher_stage_qwen35b
created: June 1, 2026 15:32 local ds-serv6 time
log ended with: staged Qwen/Qwen3.5-35B-A3B at /home/suraj/pipecypher-models/Qwen3.5-35B-A3B
latest observed disk usage: 67G
staged files: 14 safetensor shards plus tokenizer/config files
```

Serve the staged local path while preserving the canonical model name expected by configs:

```bash
MODEL=/home/suraj/pipecypher-models/Qwen3.5-35B-A3B \
SERVED_MODEL_NAME=Qwen/Qwen3.5-35B-A3B \
CUDA_VISIBLE_DEVICES=0,1,3,4 \
TENSOR_PARALLEL_SIZE=4 \
MAX_MODEL_LEN=4096 \
GPU_MEMORY_UTILIZATION=0.90 \
CONDA_ENV=pipe-rdf-arr \
EXTRA_VLLM_ARGS='--no-enable-flashinfer-autotune --enforce-eager --max-num-seqs 1 --max-num-batched-tokens 4096' \
scripts/launch_ds_serv6_vllm.sh
```

Choose GPU IDs only after checking `nvidia-smi`; the command above is a template, not a claim that those GPUs are free.

## Serving Feasibility Snapshot

Before launching a 35B vLLM endpoint, check current GPU capacity:

```bash
python scripts/check_vllm_capacity.py \
  --model-dir /home/suraj/pipecypher-models/Qwen3.5-35B-A3B \
  --gpu-memory-utilization 0.90 \
  --reserve-mib 2048 \
  --remote \
  --format json
```

Latest June 2, 2026 00:00 UTC `ds-serv6` result:

```text
Model size MiB: 68573
Usable MiB/GPU at 0.90 utilization and 2048 MiB reserve: 20059
Required GPUs: 4
Safe GPUs: 1 (GPU 3)
Feasible now: no
```

The live GPU snapshot had GPU 2 occupied by the active Qwen3.5-9B vLLM ablation endpoint, GPUs 0/1/4/5/6/7 occupied by other long-running jobs or high utilization, and only GPU 3 safely free. Even stopping the 9B endpoint would leave at most two safe GPUs, below the conservative four-GPU requirement. This is the concrete blocker for 35B serving in the current run; the 9B fallback results are therefore the reported live results.

The detailed snapshot is recorded in `knowledge_base/qwen35b_capacity_snapshot_20260601.md`, with the latest remote JSON evidence in `experiments/snapshots/qwen35b_capacity_20260601_latest.json`.
