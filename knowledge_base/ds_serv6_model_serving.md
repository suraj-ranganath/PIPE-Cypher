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
- `Qwen/Qwen3.5-9B` and `BAAI/bge-m3` are the standard local model/cache targets for the current reported study. Historical larger-model staging notes are internal operations history, not paper-facing fallback evidence.

## Suggested Setup

```bash
ssh suraj@ds-serv6.ucsd.edu
tmux new -s pipecypher

mkdir -p ~/pipecypher-models
cd /path/to/PIPE-Cypher

# Existing env verified on June 1, 2026:
CONDA_ENV=pipe-rdf-arr CUDA_VISIBLE_DEVICES=2,3 bash scripts/serve_qwen_vllm.sh Qwen/Qwen3.5-9B
```

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

Full 3,000-example generation can be launched in a detached tmux session with the standard 9B endpoint:

```bash
SESSION=pipecypher_full_qwen9b \
RUN_PREFIX=20260601_full_qwen9b \
GENERATION_MODEL=Qwen/Qwen3.5-9B \
JUDGE_MODEL=Qwen/Qwen3.5-9B \
scripts/launch_live_full_generation_tmux.sh
```

Observed June 1, 2026 launch:

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

Historical larger-model staging and capacity notes remain in `knowledge_base/qwen35b_capacity_snapshot_20260601.md` and `experiments/snapshots/qwen35b_capacity_20260602_latest.json` for internal operations only. They should not be used as manuscript evidence or as fallback framing for the current Qwen3.5-9B study.
