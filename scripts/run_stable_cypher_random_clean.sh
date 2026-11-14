#!/usr/bin/env bash
set -euo pipefail

BENCHMARK="${BENCHMARK:-artifacts/benchmarks/20260604_live_full_qwen9b_reviewfix}"
SPLIT="${SPLIT:-test}"
MODEL="${MODEL:-ragraph-ai/stable-cypher-instruct-3b}"
GPU_ID="${GPU_ID:-3}"

export CUDA_VISIBLE_DEVICES="${GPU_ID}"

for seed in 13 17 23; do
  suffix="random_seed${seed}"
  out_dir="artifacts/evaluations/20260604_clean_control_stable_cypher_instruct3b_transformers_${suffix}"
  mkdir -p "${out_dir}"
  {
    printf 'run_prefix=20260604_clean_control_stable_cypher_instruct3b_transformers_%s\n' "${suffix}"
    printf 'code_revision=%s\n' "$(git rev-parse HEAD 2>/dev/null || printf unknown)"
    printf 'benchmark=%s\n' "${BENCHMARK}"
    printf 'split=%s\n' "${SPLIT}"
    printf 'model=%s\n' "${MODEL}"
    printf 'runner=transformers_bitsandbytes\n'
    printf 'few_shot_mode=random_same_category\n'
    printf 'few_shot_seed=%s\n' "${seed}"
    printf 'few_shot_exclude_signature_match=false\n'
    date -u '+launched_at_utc=%Y-%m-%dT%H:%M:%SZ'
    printf 'notes=clean rerun after overlapping stable random controls\n'
  } > "${out_dir}/run_metadata.txt"

  python scripts/generate_text2cypher_predictions_transformers.py \
    --benchmark "${BENCHMARK}" \
    --split "${SPLIT}" \
    --schema finbench=configs/schema_finbench.json \
    --schema snb=configs/schema_snb.json \
    --output "${out_dir}/few_shot_predictions.jsonl" \
    --model "${MODEL}" \
    --few-shot "${BENCHMARK}/train.jsonl" \
    --few-shot-k 5 \
    --few-shot-mode random_same_category \
    --few-shot-seed "${seed}" \
    --few-shot-max-question-sim 0.90 \
    --few-shot-log "${out_dir}/few_shot_selection.jsonl" \
    --device-map single_cuda \
    --load-in-8bit

  python scripts/evaluate_benchmark_predictions.py \
    --benchmark "${BENCHMARK}" \
    --split "${SPLIT}" \
    --predictions "${out_dir}/few_shot_predictions.jsonl" \
    --config finbench=configs/finbench_full.yaml \
    --config snb=configs/snb_full.yaml \
    --output "${out_dir}/few_shot_evaluation.jsonl" \
    --summary-output "${out_dir}/few_shot_summary.json"
done

date -u '+completed_at_utc=%Y-%m-%dT%H:%M:%SZ'
