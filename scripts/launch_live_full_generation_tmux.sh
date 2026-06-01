#!/usr/bin/env bash
set -euo pipefail

SESSION="${SESSION:-pipecypher_full_generation}"
PYTHON_BIN="${PYTHON_BIN:-/home/suraj/pipecypher-tools/runtime-venv/bin/python}"
RUN_PREFIX="${RUN_PREFIX:-live_full_$(date +%Y%m%d_%H%M%S)}"
GENERATION_MODEL="${GENERATION_MODEL:-Qwen/Qwen3.5-9B}"
JUDGE_MODEL="${JUDGE_MODEL:-${GENERATION_MODEL}}"
LOG_DIR="${LOG_DIR:-logs}"

mkdir -p "${LOG_DIR}"

if tmux has-session -t "${SESSION}" 2>/dev/null; then
  echo "tmux session ${SESSION} already exists"
  exit 0
fi

quote() {
  printf "%q" "$1"
}

LOG_PATH="${LOG_DIR}/${RUN_PREFIX}_full_generation.log"
CMD="PYTHON_BIN=$(quote "${PYTHON_BIN}") RUN_PREFIX=$(quote "${RUN_PREFIX}") GENERATION_MODEL=$(quote "${GENERATION_MODEL}") JUDGE_MODEL=$(quote "${JUDGE_MODEL}") bash scripts/run_live_full_generation.sh 2>&1 | tee $(quote "${LOG_PATH}")"
tmux new-session -d -s "${SESSION}" "${CMD}"
echo "started session=${SESSION} run_prefix=${RUN_PREFIX} generation_model=${GENERATION_MODEL} log=${LOG_PATH}"
