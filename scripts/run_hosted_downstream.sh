#!/usr/bin/env bash
# Run the downstream suite for hosted models in parallel (one tmux window per
# model), each with its own OpenRouter routing (released precision only).
#
# Usage:
#   scripts/run_hosted_downstream.sh BENCHMARK SPLIT PREFIX CONDITIONS "slug1 slug2 ..." [EXTRA_SUITE_ARGS...]
# Example:
#   scripts/run_hosted_downstream.sh artifacts/benchmarks/naacl_v2_heldout test naacl_v2 \
#     zero_pipe_standard,zero_pipe_governed,fewshot_ordered "qwen35_9b gemma3_12b gpt6_luna"
set -euo pipefail

BENCHMARK="$1"; SPLIT="$2"; PREFIX="$3"; CONDITIONS="$4"; MODELS="$5"; shift 5
EXTRA_ARGS="$*"
PY="${PY:-$HOME/pipecypher-venv/bin/python}"
ENV_FILE="${ENV_FILE:-$HOME/.pipecypher_env}"
# Spend: give every downstream build its own ledger and cap; workers pause at the cap.
export PIPE_CYPHER_PAUSE_ON_CAP="${PIPE_CYPHER_PAUSE_ON_CAP:-1}"
MANIFEST="${MANIFEST:-configs/downstream_models_hosted_naacl2027.yaml}"
SESSION="ds_${PREFIX}"
LOG_DIR="logs/${PREFIX}"
cd "$(dirname "${BASH_SOURCE[0]}")/.."
mkdir -p "${LOG_DIR}"

BF16='{"quantizations":["bf16","fp16","fp32"],"sort":"price","allow_fallbacks":true}'
FP8='{"quantizations":["fp8"],"sort":"price","allow_fallbacks":true}'
# v2 pinned Z.ai's FP8 endpoint; v3 (owner decision 2026-11-12) pins Novita's FP8 endpoint.
GLM_PIN="${GLM_PIN:-{\"order\":[\"novita/fp8\"],\"allow_fallbacks\":false,\"require_parameters\":true}}"
routing_for() {
  case "$1" in
    glm53_flash) echo "${GLM_PIN}" ;;
    qwen3_coder_30b_a3b) echo "${FP8}" ;;
    gpt6_luna) echo "" ;;
    *) echo "${BF16}" ;;
  esac
}

if tmux has-session -t "${SESSION}" 2>/dev/null; then
  echo "tmux session ${SESSION} already exists" >&2
  exit 1
fi
first=1
for slug in ${MODELS}; do
  routing="$(routing_for "${slug}")"
  runner="${LOG_DIR}/${slug}.run.sh"
  {
    echo "#!/usr/bin/env bash"
    echo "source '${ENV_FILE}'"
    echo "export PIPE_CYPHER_CALL_LABEL='${PREFIX}:${slug}'"
    echo "export PIPE_CYPHER_OPENROUTER_ROUTING='${routing}'"
    echo "export PIPE_CYPHER_PRED_CONCURRENCY='${PRED_CONCURRENCY:-8}'"
    echo "'${PY}' scripts/run_downstream_suite.py --manifest '${MANIFEST}' --benchmark '${BENCHMARK}' --split '${SPLIT}' --models '${slug}' --conditions '${CONDITIONS}' --prefix '${PREFIX}' --python '${PY}' --max-tokens 1024 --skip-existing ${EXTRA_ARGS} > '${LOG_DIR}/${slug}.log' 2>&1"
    echo "echo EXIT=\$? >> '${LOG_DIR}/${slug}.log'"
  } > "${runner}"
  chmod +x "${runner}"
  if [[ ${first} -eq 1 ]]; then
    tmux new-session -d -s "${SESSION}" -n "${slug}" "bash '${runner}'"
    first=0
  else
    tmux new-window -t "${SESSION}" -n "${slug}" "bash '${runner}'"
  fi
done
echo "launched session=${SESSION} logs=${LOG_DIR}"
