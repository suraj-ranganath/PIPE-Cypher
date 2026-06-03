#!/usr/bin/env bash
set -euo pipefail

BENCHMARK="${BENCHMARK:-artifacts/benchmarks/20260601_live_full_qwen9b}"
SPLIT="${SPLIT:-test}"
RUN_PREFIX="${RUN_PREFIX:-$(date +%Y%m%d_%H%M%S)_downstream_zero_fewshot}"
BASE_URL="${BASE_URL:-http://localhost:8000/v1}"
MODEL="${MODEL:-Qwen/Qwen3.5-9B}"
FEW_SHOT_K="${FEW_SHOT_K:-5}"
FEW_SHOT_MODE="${FEW_SHOT_MODE:-ordered_same_category}"
FEW_SHOT_SEED="${FEW_SHOT_SEED:-13}"
FEW_SHOT_MAX_QUESTION_SIM="${FEW_SHOT_MAX_QUESTION_SIM:-0.90}"
FEW_SHOT_EXCLUDE_SIGNATURE_MATCH="${FEW_SHOT_EXCLUDE_SIGNATURE_MATCH:-false}"
OUTPUT_DIR="${OUTPUT_DIR:-artifacts/evaluations/${RUN_PREFIX}}"
SYSTEM_MESSAGE_MODE="${SYSTEM_MESSAGE_MODE:-separate}"

mkdir -p "${OUTPUT_DIR}"

python scripts/generate_text2cypher_predictions.py \
  --benchmark "${BENCHMARK}" \
  --split "${SPLIT}" \
  --schema finbench=configs/schema_finbench.json \
  --schema snb=configs/schema_snb.json \
  --output "${OUTPUT_DIR}/zero_shot_predictions.jsonl" \
  --base-url "${BASE_URL}" \
  --model "${MODEL}" \
  --system-message-mode "${SYSTEM_MESSAGE_MODE}" \
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
  --system-message-mode "${SYSTEM_MESSAGE_MODE}" \
  --few-shot "${BENCHMARK}/train.jsonl" \
  --few-shot-k "${FEW_SHOT_K}" \
  --few-shot-mode "${FEW_SHOT_MODE}" \
  --few-shot-seed "${FEW_SHOT_SEED}" \
  --few-shot-max-question-sim "${FEW_SHOT_MAX_QUESTION_SIM}" \
  --few-shot-log "${OUTPUT_DIR}/few_shot_selection.jsonl" \
  $(if [[ "${FEW_SHOT_EXCLUDE_SIGNATURE_MATCH}" == "true" ]]; then printf '%s' "--few-shot-exclude-signature-match"; fi)

python scripts/evaluate_benchmark_predictions.py \
  --benchmark "${BENCHMARK}" \
  --split "${SPLIT}" \
  --predictions "${OUTPUT_DIR}/few_shot_predictions.jsonl" \
  --config finbench=configs/finbench_full.yaml \
  --config snb=configs/snb_full.yaml \
  --output "${OUTPUT_DIR}/few_shot_evaluation.jsonl" \
  --summary-output "${OUTPUT_DIR}/few_shot_summary.json"

printf 'wrote downstream zero/few-shot outputs to %s\n' "${OUTPUT_DIR}"
cat > "${OUTPUT_DIR}/metadata.json" <<EOF
{
  "benchmark": "${BENCHMARK}",
  "split": "${SPLIT}",
  "model": "${MODEL}",
  "base_url": "${BASE_URL}",
  "few_shot_k": ${FEW_SHOT_K},
  "few_shot_mode": "${FEW_SHOT_MODE}",
  "few_shot_seed": ${FEW_SHOT_SEED},
  "few_shot_max_question_similarity": ${FEW_SHOT_MAX_QUESTION_SIM},
  "few_shot_exclude_signature_match": ${FEW_SHOT_EXCLUDE_SIGNATURE_MATCH}
}
EOF
