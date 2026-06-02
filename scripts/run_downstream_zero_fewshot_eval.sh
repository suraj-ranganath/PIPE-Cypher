#!/usr/bin/env bash
set -euo pipefail

BENCHMARK="${BENCHMARK:-artifacts/benchmarks/20260601_live_full_qwen9b}"
SPLIT="${SPLIT:-test}"
RUN_PREFIX="${RUN_PREFIX:-$(date +%Y%m%d_%H%M%S)_downstream_zero_fewshot}"
BASE_URL="${BASE_URL:-http://localhost:8000/v1}"
MODEL="${MODEL:-Qwen/Qwen3.5-9B}"
FEW_SHOT_K="${FEW_SHOT_K:-5}"
OUTPUT_DIR="${OUTPUT_DIR:-artifacts/evaluations/${RUN_PREFIX}}"

mkdir -p "${OUTPUT_DIR}"

python scripts/generate_text2cypher_predictions.py \
  --benchmark "${BENCHMARK}" \
  --split "${SPLIT}" \
  --schema finbench=configs/schema_finbench.json \
  --schema snb=configs/schema_snb.json \
  --output "${OUTPUT_DIR}/zero_shot_predictions.jsonl" \
  --base-url "${BASE_URL}" \
  --model "${MODEL}" \
  --few-shot-k 0

python scripts/evaluate_benchmark_predictions.py \
  --benchmark "${BENCHMARK}" \
  --split "${SPLIT}" \
  --predictions "${OUTPUT_DIR}/zero_shot_predictions.jsonl" \
  --config finbench=configs/finbench_full.yaml \
  --config snb=configs/snb_full.yaml \
  --output "${OUTPUT_DIR}/zero_shot_evaluation.jsonl" \
  --summary-output "${OUTPUT_DIR}/zero_shot_summary.json"

python scripts/generate_text2cypher_predictions.py \
  --benchmark "${BENCHMARK}" \
  --split "${SPLIT}" \
  --schema finbench=configs/schema_finbench.json \
  --schema snb=configs/schema_snb.json \
  --output "${OUTPUT_DIR}/few_shot_predictions.jsonl" \
  --base-url "${BASE_URL}" \
  --model "${MODEL}" \
  --few-shot "${BENCHMARK}/train.jsonl" \
  --few-shot-k "${FEW_SHOT_K}"

python scripts/evaluate_benchmark_predictions.py \
  --benchmark "${BENCHMARK}" \
  --split "${SPLIT}" \
  --predictions "${OUTPUT_DIR}/few_shot_predictions.jsonl" \
  --config finbench=configs/finbench_full.yaml \
  --config snb=configs/snb_full.yaml \
  --output "${OUTPUT_DIR}/few_shot_evaluation.jsonl" \
  --summary-output "${OUTPUT_DIR}/few_shot_summary.json"

printf 'wrote downstream zero/few-shot outputs to %s\n' "${OUTPUT_DIR}"
