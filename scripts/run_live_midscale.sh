#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python}"
RUN_PREFIX="${RUN_PREFIX:-live_midscale_$(date +%Y%m%d_%H%M%S)}"

run_one() {
  local config="$1"
  local name="$2"
  "${PYTHON_BIN}" scripts/run_pipeline.py --config "${config}" --run-name "${RUN_PREFIX}_${name}"
}

run_one configs/finbench_live_midscale.yaml finbench
run_one configs/snb_live_midscale.yaml snb
