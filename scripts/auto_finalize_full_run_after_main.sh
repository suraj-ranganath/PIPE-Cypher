#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python}"
RUN_PREFIX="${RUN_PREFIX:-20260601_full_qwen9b}"
MAIN_SESSION="${MAIN_SESSION:-pipecypher_full_qwen9b}"
POLL_SEC="${POLL_SEC:-60}"
FINBENCH_CONFIG="${FINBENCH_CONFIG:-configs/finbench_full.yaml}"
SNB_CONFIG="${SNB_CONFIG:-configs/snb_full.yaml}"
WAIT_FOR_SESSION="${WAIT_FOR_SESSION:-1}"
FILL_TAG="${FILL_TAG:-$(date +%Y%m%d_%H%M%S)}"
FILL_PASSES="${FILL_PASSES:-3}"

latest_run_dir() {
  local suffix="$1"
  find artifacts/runs -maxdepth 1 -type d -name "*_${RUN_PREFIX}_${suffix}" | sort | tail -1
}

fill_dirs_for_prefix() {
  local fill_prefix="$1"
  find artifacts/runs -maxdepth 1 -type d -name "*_${fill_prefix}_*" | sort
}

if [[ "${WAIT_FOR_SESSION}" == "1" ]]; then
  echo "waiting for tmux session ${MAIN_SESSION} to finish"
  while tmux has-session -t "${MAIN_SESSION}" 2>/dev/null; do
    sleep "${POLL_SEC}"
  done
fi

FINBENCH_RUN="${FINBENCH_RUN:-$(latest_run_dir finbench)}"
SNB_RUN="${SNB_RUN:-$(latest_run_dir snb)}"

if [[ -z "${FINBENCH_RUN}" || ! -f "${FINBENCH_RUN}/records.jsonl" ]]; then
  echo "missing FinBench run for RUN_PREFIX=${RUN_PREFIX}" >&2
  exit 1
fi
if [[ -z "${SNB_RUN}" || ! -f "${SNB_RUN}/records.jsonl" ]]; then
  echo "missing SNB run for RUN_PREFIX=${RUN_PREFIX}" >&2
  exit 1
fi

FINBENCH_FILL_PREFIX="${RUN_PREFIX}_finbench_fill_${FILL_TAG}"
SNB_FILL_PREFIX="${RUN_PREFIX}_snb_fill_${FILL_TAG}"

echo "FinBench run: ${FINBENCH_RUN}"
echo "SNB run: ${SNB_RUN}"

"${PYTHON_BIN}" scripts/fill_missing_categories.py \
  --config "${FINBENCH_CONFIG}" \
  --records "${FINBENCH_RUN}" \
  --run-prefix "${FINBENCH_FILL_PREFIX}" \
  --passes "${FILL_PASSES}"

"${PYTHON_BIN}" scripts/fill_missing_categories.py \
  --config "${SNB_CONFIG}" \
  --records "${SNB_RUN}" \
  --run-prefix "${SNB_FILL_PREFIX}" \
  --passes "${FILL_PASSES}"

EXTRA_RECORDS="$(
  {
    fill_dirs_for_prefix "${FINBENCH_FILL_PREFIX}"
    fill_dirs_for_prefix "${SNB_FILL_PREFIX}"
  } | tr '\n' ' '
)"
EXTRA_RECORDS="${EXTRA_RECORDS%" "}"

echo "Extra top-up records: ${EXTRA_RECORDS:-<none>}"

RUN_PREFIX="${RUN_PREFIX}" \
PYTHON_BIN="${PYTHON_BIN}" \
EXTRA_RECORDS="${EXTRA_RECORDS}" \
  scripts/finalize_live_full_run.sh
