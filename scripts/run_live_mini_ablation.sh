#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python}"
RUN_PREFIX="${RUN_PREFIX:-live_mini_$(date +%Y%m%d_%H%M%S)}"

run_one() {
  local config="$1"
  local name="$2"
  "${PYTHON_BIN}" scripts/run_pipeline.py --config "${config}" --run-name "${RUN_PREFIX}_${name}"
}

run_one configs/finbench_live_llm_only_probe.yaml finbench_llm_only_probe
run_one configs/finbench_live_mixed_mini.yaml finbench_mixed_mini
run_one configs/snb_live_mixed_mini.yaml snb_mixed_mini
