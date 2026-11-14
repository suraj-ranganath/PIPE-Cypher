#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python}"
RUN_PREFIX="${RUN_PREFIX:-live_full_$(date +%Y%m%d_%H%M%S)}"
GENERATION_MODEL="${GENERATION_MODEL:-}"
JUDGE_MODEL="${JUDGE_MODEL:-${GENERATION_MODEL}}"

run_one() {
  local config="$1"
  local name="$2"
  if [[ -n "${GENERATION_MODEL}" ]]; then
    PIPE_CYPHER_LLM_MODEL="${GENERATION_MODEL}" \
    PIPE_CYPHER_JUDGE_MODEL="${JUDGE_MODEL}" \
      "${PYTHON_BIN}" scripts/run_pipeline.py --config "${config}" --run-name "${RUN_PREFIX}_${name}"
  else
    "${PYTHON_BIN}" scripts/run_pipeline.py --config "${config}" --run-name "${RUN_PREFIX}_${name}"
  fi
}

run_one configs/finbench_full.yaml finbench
run_one configs/snb_full.yaml snb
