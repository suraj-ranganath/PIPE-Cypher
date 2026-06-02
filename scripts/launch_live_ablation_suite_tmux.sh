#!/usr/bin/env bash
set -euo pipefail

SESSION="${SESSION:-pipecypher_ablation_suite}"
PYTHON_BIN="${PYTHON_BIN:-/home/suraj/pipecypher-tools/runtime-venv/bin/python}"
TARGET_PER_CATEGORY="${TARGET_PER_CATEGORY:-25}"
RUN_PREFIX="${RUN_PREFIX:-$(date +%Y%m%d_%H%M%S)_ablation${TARGET_PER_CATEGORY}}"
GENERATION_MODEL="${GENERATION_MODEL:-Qwen/Qwen3.5-9B}"
JUDGE_MODEL="${JUDGE_MODEL:-${GENERATION_MODEL}}"
LLM_BASE_URL="${PIPE_CYPHER_LLM_BASE_URL:-}"
RUN_SEED="${RUN_SEED:-}"
GRAPH_SET="${GRAPH_SET:-finbench snb}"
VARIANT_SET="${VARIANT_SET:-}"
WAIT_FOR_SESSION="${WAIT_FOR_SESSION:-}"
LOG_DIR="${LOG_DIR:-logs}"
CODE_REVISION="${CODE_REVISION:-$(git rev-parse HEAD 2>/dev/null || printf 'unavailable')}"

mkdir -p "${LOG_DIR}"

if tmux has-session -t "${SESSION}" 2>/dev/null; then
  echo "tmux session ${SESSION} already exists"
  exit 0
fi

quote() {
  printf "%q" "$1"
}

LOG_PATH="${LOG_DIR}/${RUN_PREFIX}.log"
CMD=""
if [[ -n "${WAIT_FOR_SESSION}" ]]; then
  CMD+="while tmux has-session -t $(quote "=${WAIT_FOR_SESSION}") 2>/dev/null; do date; echo waiting_for_session=$(quote "${WAIT_FOR_SESSION}"); sleep 60; done; "
fi
CMD+="PYTHON_BIN=$(quote "${PYTHON_BIN}") "
CMD+="TARGET_PER_CATEGORY=$(quote "${TARGET_PER_CATEGORY}") "
CMD+="RUN_PREFIX=$(quote "${RUN_PREFIX}") "
CMD+="GENERATION_MODEL=$(quote "${GENERATION_MODEL}") "
CMD+="JUDGE_MODEL=$(quote "${JUDGE_MODEL}") "
if [[ -n "${LLM_BASE_URL}" ]]; then
  CMD+="PIPE_CYPHER_LLM_BASE_URL=$(quote "${LLM_BASE_URL}") "
fi
CMD+="RUN_SEED=$(quote "${RUN_SEED}") "
CMD+="GRAPH_SET=$(quote "${GRAPH_SET}") "
CMD+="CODE_REVISION=$(quote "${CODE_REVISION}") "
if [[ -n "${VARIANT_SET}" ]]; then
  CMD+="VARIANT_SET=$(quote "${VARIANT_SET}") "
fi
CMD+="bash scripts/run_live_ablation_suite.sh 2>&1 | tee $(quote "${LOG_PATH}")"

tmux new-session -d -s "${SESSION}" "${CMD}"
echo "started session=${SESSION} run_prefix=${RUN_PREFIX} target_per_category=${TARGET_PER_CATEGORY} generation_model=${GENERATION_MODEL} log=${LOG_PATH}"
if [[ -n "${RUN_SEED}" ]]; then
  echo "run_seed=${RUN_SEED}"
fi
if [[ -n "${WAIT_FOR_SESSION}" ]]; then
  echo "waiting_for_session=${WAIT_FOR_SESSION}"
fi
