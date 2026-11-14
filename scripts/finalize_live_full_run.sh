#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python}"
RUN_PREFIX="${RUN_PREFIX:-20260601_full_qwen9b}"
OUTPUT_DIR="${OUTPUT_DIR:-artifacts/benchmarks/20260601_live_full_qwen9b}"
SPLIT_SEED="${SPLIT_SEED:-live-full-qwen9b-v1}"
AUDIT_N="${AUDIT_N:-80}"
AUDIT_OUTPUT="${AUDIT_OUTPUT:-artifacts/audits/${RUN_PREFIX}_judge_audit.csv}"
RUN_DOWNSTREAM="${RUN_DOWNSTREAM:-0}"
BASE_URL="${BASE_URL:-http://localhost:8000/v1}"
MODEL="${MODEL:-Qwen/Qwen3.5-9B}"
EXTRA_RECORDS="${EXTRA_RECORDS:-}"

latest_run_dir() {
  local suffix="$1"
  find artifacts/runs -maxdepth 1 -type d -name "*_${RUN_PREFIX}_${suffix}" | sort | tail -1
}

FINBENCH_RUN="${FINBENCH_RUN:-$(latest_run_dir finbench)}"
SNB_RUN="${SNB_RUN:-$(latest_run_dir snb)}"

if [[ -z "${FINBENCH_RUN}" || ! -f "${FINBENCH_RUN}/records.jsonl" ]]; then
  echo "missing FinBench records for RUN_PREFIX=${RUN_PREFIX}" >&2
  exit 1
fi
if [[ -z "${SNB_RUN}" || ! -f "${SNB_RUN}/records.jsonl" ]]; then
  echo "missing SNB records for RUN_PREFIX=${RUN_PREFIX}" >&2
  exit 1
fi

echo "FinBench run: ${FINBENCH_RUN}"
echo "SNB run: ${SNB_RUN}"

EXTRA_RECORD_ARGS=()
EXTRA_RECORD_FILE_ARGS=()
if [[ -n "${EXTRA_RECORDS}" ]]; then
  # Space-separated run directories or records.jsonl paths. Avoid spaces in artifact paths.
  read -r -a EXTRA_RECORD_ARGS <<< "${EXTRA_RECORDS}"
  printf 'Extra records: %s\n' "${EXTRA_RECORD_ARGS[@]}"
  for path in "${EXTRA_RECORD_ARGS[@]}"; do
    if [[ -d "${path}" ]]; then
      EXTRA_RECORD_FILE_ARGS+=("${path}/records.jsonl")
    else
      EXTRA_RECORD_FILE_ARGS+=("${path}")
    fi
  done
fi

"${PYTHON_BIN}" scripts/compare_runs.py "${FINBENCH_RUN}" "${SNB_RUN}" "${EXTRA_RECORD_ARGS[@]}" --format markdown

"${PYTHON_BIN}" scripts/export_benchmark.py \
  --records "${FINBENCH_RUN}" "${SNB_RUN}" "${EXTRA_RECORD_ARGS[@]}" \
  --output-dir "${OUTPUT_DIR}" \
  --split-seed "${SPLIT_SEED}"

mkdir -p "$(dirname "${AUDIT_OUTPUT}")"
"${PYTHON_BIN}" scripts/sample_judge_audit.py \
  --records "${FINBENCH_RUN}/records.jsonl" "${SNB_RUN}/records.jsonl" "${EXTRA_RECORD_FILE_ARGS[@]}" \
  --output "${AUDIT_OUTPUT}" \
  --n "${AUDIT_N}" \
  --seed 13

echo "exported benchmark: ${OUTPUT_DIR}"
echo "sampled judge audit: ${AUDIT_OUTPUT}"

if [[ "${RUN_DOWNSTREAM}" != "1" ]]; then
  echo "set RUN_DOWNSTREAM=1 to run Text2Cypher predictions and execution evaluation"
  exit 0
fi

PREDICTIONS="artifacts/predictions/${RUN_PREFIX}_test_predictions.jsonl"
EVAL_JSONL="artifacts/evaluations/${RUN_PREFIX}_test_eval.jsonl"
EVAL_SUMMARY="artifacts/evaluations/${RUN_PREFIX}_test_summary.json"
mkdir -p artifacts/predictions artifacts/evaluations

"${PYTHON_BIN}" scripts/generate_text2cypher_predictions.py \
  --benchmark "${OUTPUT_DIR}" \
  --split test \
  --schema finbench=configs/schema_finbench.json \
  --schema snb=configs/schema_snb.json \
  --output "${PREDICTIONS}" \
  --base-url "${BASE_URL}" \
  --model "${MODEL}" \
  --schema-max-items 45 \
  --max-tokens 512 \
  --timeout-sec 180

"${PYTHON_BIN}" scripts/evaluate_benchmark_predictions.py \
  --benchmark "${OUTPUT_DIR}" \
  --split test \
  --predictions "${PREDICTIONS}" \
  --config finbench=configs/finbench_full.yaml \
  --config snb=configs/snb_full.yaml \
  --output "${EVAL_JSONL}" \
  --summary-output "${EVAL_SUMMARY}"

echo "downstream predictions: ${PREDICTIONS}"
echo "downstream eval: ${EVAL_JSONL}"
echo "downstream summary: ${EVAL_SUMMARY}"
