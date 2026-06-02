# Local Model Serving On ds-serv6

PIPE-Cypher generation and judge review should use local models, not paid APIs.

## Current Host Snapshot

Checked with `python scripts/check_gpu_host.py` on June 1, 2026:

```text
ds-serv6
0, NVIDIA RTX A5000, 24564, 8329, 0
1, NVIDIA RTX A5000, 24564, 6622, 0
2, NVIDIA RTX A5000, 24564, 1, 0
3, NVIDIA RTX A5000, 24564, 1, 0
4, NVIDIA RTX A5000, 24564, 415, 100
5, NVIDIA RTX A5000, 24564, 415, 100
6, NVIDIA RTX A5000, 24564, 20281, 0
7, NVIDIA RTX A5000, 24564, 20281, 0
Filesystem                         Size  Used Avail Use% Mounted on
/dev/mapper/ubuntu--vg-ubuntu--lv   14T  2.7T   11T  21% /
/dev/md0p1                          46T   42T  1.1T  98% /data
```

Use GPUs 2 and 3 for first vLLM smoke tests if they remain idle. Avoid large `/data` writes until storage is cleaned.

Additional June 1, 2026 checks:

- `~/miniforge3` exists.
- Conda env `pipe-rdf-arr` has `vllm`, `torch`, `transformers`, and `huggingface_hub`.
- Cached local models include `Qwen/Qwen3.5-9B`, `Qwen/Qwen3.5-4B`, `Qwen/Qwen3.5-2B`, `Qwen/Qwen3.5-0.8B`, and `BAAI/bge-m3`.
- `Qwen/Qwen3.5-35B-A3B` exists in Hugging Face metadata and has now been staged under `/home/suraj/pipecypher-models/Qwen3.5-35B-A3B`; current live runs still use `Qwen/Qwen3.5-9B` unless a separate 35B endpoint is started.

## Suggested Setup

```bash
ssh suraj@ds-serv6.ucsd.edu
tmux new -s pipecypher

mkdir -p ~/pipecypher-models
cd /path/to/PIPE-Cypher

# Existing env verified on June 1, 2026:
CONDA_ENV=pipe-rdf-arr CUDA_VISIBLE_DEVICES=2,3 bash scripts/serve_qwen_vllm.sh Qwen/Qwen3.5-9B
```

For the target model:

```bash
CONDA_ENV=pipe-rdf-arr CUDA_VISIBLE_DEVICES=2,3 bash scripts/serve_qwen_vllm.sh Qwen/Qwen3.5-35B-A3B
```

If the 35B-A3B model does not fit on two A5000s, try more GPUs or use the 9B model for generation and judge smoke experiments while recording the limitation.

From the local workstation, after syncing this repo to `/home/suraj/PIPE-Cypher` on `ds-serv6`, the helper script can start vLLM in tmux:

```bash
HOST=suraj@ds-serv6.ucsd.edu \
REMOTE_DIR=/home/suraj/PIPE-Cypher \
MODEL=Qwen/Qwen3.5-9B \
CUDA_VISIBLE_DEVICES=2,3 \
CONDA_ENV=pipe-rdf-arr \
scripts/launch_ds_serv6_vllm.sh
```

Working June 1, 2026 command for the cached 9B model on one idle A5000:

```bash
MODEL=Qwen/Qwen3.5-9B \
CUDA_VISIBLE_DEVICES=2 \
MAX_MODEL_LEN=2048 \
GPU_MEMORY_UTILIZATION=0.90 \
CONDA_ENV=pipe-rdf-arr \
EXTRA_VLLM_ARGS='--no-enable-flashinfer-autotune --enforce-eager --max-num-seqs 1 --max-num-batched-tokens 2048' \
scripts/launch_ds_serv6_vllm.sh
```

Why these flags are needed:

- Without `--enforce-eager`, 9B loaded but failed during CUDA graph/KV profiling with a 1.03 GiB OOM on a 24 GB A5000.
- FlashInfer sampling triggered a local JIT incompatibility, so `VLLM_USE_FLASHINFER_SAMPLER=0` is exported by `scripts/serve_qwen_vllm.sh`, and `--no-enable-flashinfer-autotune` is passed explicitly.
- `--max-num-seqs 1` and `--max-num-batched-tokens 2048` keep the smoke endpoint conservative. Increase these only after recording GPU memory headroom.
- A two-GPU tensor-parallel 9B attempt did not become usable during the smoke session; revisit with more time before relying on it for large runs.

Smoke-check the endpoint on `ds-serv6`:

```bash
curl http://localhost:8000/v1/models
python scripts/check_llm_endpoint.py --base-url http://localhost:8000/v1 --model Qwen/Qwen3.5-9B
```

Observed successful endpoint check:

```json
{
  "base_url": "http://localhost:8000/v1",
  "chat_text": "ok",
  "model": "Qwen/Qwen3.5-9B",
  "models": ["Qwen/Qwen3.5-9B"],
  "ok": true
}
```

The same Qwen3.5-9B endpoint was used for the June 1, 2026 live FinBench smoke run:

```bash
/home/suraj/pipecypher-tools/runtime-venv/bin/python scripts/run_pipeline.py \
  --config configs/finbench_live_smoke.yaml \
  --run-name live_finbench_qwen9b_defaultslots
```

That run accepted 4/4 examples with LLM-judge review over the loaded FinBench SF0.1 Neo4j graph.

It also served the June 1, 2026 live SNB smoke:

```bash
/home/suraj/pipecypher-tools/runtime-venv/bin/python scripts/run_pipeline.py \
  --config configs/snb_live_smoke.yaml \
  --run-name live_snb_qwen9b_ids_template
```

That run accepted 4/4 examples with LLM-judge review over the loaded SNB Cypher test-data graph. The judge uses schema slicing for SNB so the conservative 2k-token Qwen endpoint does not receive the full live schema in every review prompt.

## Full Generation Launch

Full 3,000-example generation can be launched in a detached tmux session. Use the fallback command while only the 9B model is served:

```bash
SESSION=pipecypher_full_qwen9b \
RUN_PREFIX=20260601_full_qwen9b \
GENERATION_MODEL=Qwen/Qwen3.5-9B \
JUDGE_MODEL=Qwen/Qwen3.5-9B \
scripts/launch_live_full_generation_tmux.sh
```

Observed June 1, 2026 fallback launch:

```text
started session=pipecypher_full_qwen9b run_prefix=20260601_full_qwen9b generation_model=Qwen/Qwen3.5-9B log=logs/20260601_full_qwen9b_full_generation.log
FinBench run dir: artifacts/runs/20260601_142318_20260601_full_qwen9b_finbench
```

Monitor progress:

```bash
tmux ls
tail -f logs/20260601_full_qwen9b_full_generation.log
python scripts/monitor_generation_run.py artifacts/runs/<run_dir>/records.jsonl --target-per-category 250
```

The current live status and follow-up export command are recorded in `knowledge_base/full_run_status.md`.

After staging and serving `Qwen/Qwen3.5-35B-A3B`, launch the target run by setting `GENERATION_MODEL` and `JUDGE_MODEL` to `Qwen/Qwen3.5-35B-A3B`.

The 35B-A3B staging helper is:

```bash
MODEL=Qwen/Qwen3.5-35B-A3B \
LOCAL_DIR=/home/suraj/pipecypher-models/Qwen3.5-35B-A3B \
bash scripts/stage_qwen35b_model.sh
```

The June 1, 2026 staging session completed successfully with 14 safetensor shards plus tokenizer/config files in `/home/suraj/pipecypher-models/Qwen3.5-35B-A3B` (67G observed). To serve the staged local path under the canonical model name used by the configs:

```bash
MODEL=/home/suraj/pipecypher-models/Qwen3.5-35B-A3B \
SERVED_MODEL_NAME=Qwen/Qwen3.5-35B-A3B \
CUDA_VISIBLE_DEVICES=<free_gpu_ids> \
TENSOR_PARALLEL_SIZE=<number_of_gpu_ids> \
MAX_MODEL_LEN=4096 \
GPU_MEMORY_UTILIZATION=0.90 \
CONDA_ENV=pipe-rdf-arr \
EXTRA_VLLM_ARGS='--no-enable-flashinfer-autotune --enforce-eager --max-num-seqs 1 --max-num-batched-tokens 4096' \
scripts/launch_ds_serv6_vllm.sh
```

Check feasibility before launching:

```bash
python scripts/check_vllm_capacity.py \
  --model-dir /home/suraj/pipecypher-models/Qwen3.5-35B-A3B \
  --gpu-memory-utilization 0.90 \
  --reserve-mib 2048 \
  --remote \
  --format json
```

The latest June 2, 2026 00:33 UTC remote snapshot reported 68,573 MiB of safetensor weights, four required A5000 GPUs under the conservative serving budget, and only GPU 3 safely free. The command exits with status 2 while `feasible=false`. Do not launch the 35B endpoint until at least four low-utilization GPUs are available, or update the serving plan with a tested quantized/CPU-offload configuration. The full capacity table is in `knowledge_base/qwen35b_capacity_snapshot_20260601.md`, the tracked JSON evidence is `experiments/snapshots/qwen35b_capacity_20260601_latest.json`, and `scripts/render_vllm_capacity_snapshot.py` regenerates the Markdown note from captured JSON.
