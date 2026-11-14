#!/usr/bin/env bash
# Run the downstream suite for several hosted models in parallel as background
# processes (no tmux, no env file). API keys are inherited from the calling
# shell's environment and never written to disk. Each model gets the same
# released-precision routing as scripts/run_hosted_downstream.sh.
#
# Usage:
#   scripts/run_downstream_parallel.sh BENCHMARK SPLIT PREFIX CONDITIONS "slug1 slug2 ..." [EXTRA_SUITE_ARGS...]
# Environment:
#   PY                       python with the project deps (default python3)
#   PIPE_CYPHER_USAGE_LEDGER spend ledger shared by all models of this launch
#   PIPE_CYPHER_MAX_COST_USD cap for that ledger (workers pause at the cap)
#   PRED_CONCURRENCY         requests in flight per model (default 8)
set -euo pipefail

BENCHMARK="$1"; SPLIT="$2"; PREFIX="$3"; CONDITIONS="$4"; MODELS="$5"; shift 5
PY="${PY:-python3}"
MANIFEST="${MANIFEST:-configs/downstream_models_hosted_naacl2027.yaml}"
export PIPE_CYPHER_PAUSE_ON_CAP="${PIPE_CYPHER_PAUSE_ON_CAP:-1}"
cd "$(dirname "${BASH_SOURCE[0]}")/.."
LOG_DIR="logs/${PREFIX}"
mkdir -p "${LOG_DIR}"

BF16='{"quantizations":["bf16","fp16","fp32"],"sort":"price","allow_fallbacks":true}'
FP8='{"quantizations":["fp8"],"sort":"price","allow_fallbacks":true}'
GLM_PIN='{"order":["novita/fp8"],"allow_fallbacks":false,"require_parameters":true}'
routing_for() {
  case "$1" in
    glm53_flash) echo "${GLM_PIN}" ;;
    qwen3_coder_30b_a3b) echo "${FP8}" ;;
    gpt6_luna) echo "" ;;
    *) echo "${BF16}" ;;
  esac
}

{
  echo "prefix=${PREFIX} started=$(date -u +%FT%TZ) benchmark=${BENCHMARK} split=${SPLIT} conditions=${CONDITIONS} models=${MODELS}"
  echo "ledger=${PIPE_CYPHER_USAGE_LEDGER:-none} cap=${PIPE_CYPHER_MAX_COST_USD:-none} extra=$*"
} >> "${LOG_DIR}/launch_manifest.txt"

for slug in ${MODELS}; do
  (
    export PIPE_CYPHER_CALL_LABEL="${PREFIX}:${slug}"
    export PIPE_CYPHER_OPENROUTER_ROUTING="$(routing_for "${slug}")"
    export PIPE_CYPHER_PRED_CONCURRENCY="${PRED_CONCURRENCY:-8}"
    rc=0
    "${PY}" scripts/run_downstream_suite.py --manifest "${MANIFEST}" --benchmark "${BENCHMARK}" --split "${SPLIT}" \
      --models "${slug}" --conditions "${CONDITIONS}" --prefix "${PREFIX}" --python "${PY}" --max-tokens 1024 \
      --skip-existing "$@" > "${LOG_DIR}/${slug}.log" 2>&1 || rc=$?
    echo "EXIT=${rc}" >> "${LOG_DIR}/${slug}.log"
  ) &
done
wait
echo "finished=$(date -u +%FT%TZ)" >> "${LOG_DIR}/launch_manifest.txt"
