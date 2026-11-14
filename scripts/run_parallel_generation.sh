#!/usr/bin/env bash
# Launch one PIPE-Cypher generation process per category, in parallel tmux
# windows, for a hosted-model config. Categories are independent in the
# pipeline (dedup, entity caps, and signature quotas are all per category), so
# this is equivalent to a sequential run but ~8x faster on API-bound models.
#
# Usage:
#   scripts/run_parallel_generation.sh CONFIG RUN_PREFIX [TARGET_PER_CATEGORY]
# Env:
#   PY             python interpreter (default ~/pipecypher-venv/bin/python)
#   ENV_FILE       secrets/spend env file (default ~/.pipecypher_env)
#   CATEGORIES     space-separated subset (default: all eight)
set -euo pipefail

CONFIG="$1"
RUN_PREFIX="$2"
TARGET="${3:-}"
PY="${PY:-$HOME/pipecypher-venv/bin/python}"
ENV_FILE="${ENV_FILE:-$HOME/.pipecypher_env}"
CATEGORIES="${CATEGORIES:-simple_retrieval complex_retrieval simple_aggregation complex_aggregation boolean_existence negation_difference path_temporal ranking_topk}"
# Optional sharding: SHARDS processes per category, each with its own seed,
# binding offset, and per-shard signature quota (SHARD_QUOTA). Global per-signature
# count is at most SHARDS*SHARD_QUOTA; export dedups identical questions.
SHARDS="${SHARDS:-1}"
SHARD_QUOTA="${SHARD_QUOTA:-}"
BASE_SEED="${BASE_SEED:-20261112}"
OFFSET_BASE="${OFFSET_BASE:-0}"
# Optional: accepted records whose questions the new processes must not repeat.
SEEN_RECORDS="${SEEN_RECORDS:-}"
SESSION="gen_${RUN_PREFIX}"
LOG_DIR="logs/${RUN_PREFIX}"

cd "$(dirname "${BASH_SOURCE[0]}")/.."
"${PY}" scripts/validate_config.py "${CONFIG}"
mkdir -p "${LOG_DIR}"
git_rev="$(git rev-parse HEAD 2>/dev/null || echo "no-git:$(date +%s)")"
{
  echo "config=${CONFIG}"
  echo "run_prefix=${RUN_PREFIX}"
  echo "target_override=${TARGET}"
  echo "categories=${CATEGORIES}"
  echo "shards=${SHARDS} shard_quota=${SHARD_QUOTA} base_seed=${BASE_SEED}"
  echo "code_revision=${git_rev}"
  echo "config_sha256=$(sha256sum "${CONFIG}" | cut -d' ' -f1)"
  # Uncommitted working trees still get a reproducible fingerprint.
  echo "code_tree_sha256=$(find pipecypher scripts -name '*.py' -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1)"
  echo "launched_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "${LOG_DIR}/launch_manifest.txt"

if tmux has-session -t "${SESSION}" 2>/dev/null; then
  echo "tmux session ${SESSION} already exists" >&2
  exit 1
fi
first=1
for category in ${CATEGORIES}; do
 for ((shard=0; shard<SHARDS; shard++)); do
  target_arg=""
  if [[ -n "${TARGET}" ]]; then target_arg="--target-per-category ${TARGET}"; fi
  shard_args=""
  name="${RUN_PREFIX}_${category}"
  win="${category}"
  if [[ "${SHARDS}" -gt 1 ]]; then
    shard_args="--random-seed $((BASE_SEED + shard)) --binding-offset $((OFFSET_BASE + shard * 53))"
    if [[ -n "${SHARD_QUOTA}" ]]; then shard_args="${shard_args} --max-examples-per-signature ${SHARD_QUOTA}"; fi
    name="${RUN_PREFIX}_${category}_s${shard}"
    win="${category:0:12}_s${shard}"
  fi
  if [[ -n "${SEEN_RECORDS}" ]]; then shard_args="${shard_args} --seen-records ${SEEN_RECORDS}"; fi
  cmd="source '${ENV_FILE}'; export PIPE_CYPHER_CALL_LABEL='${RUN_PREFIX}:${category}'; \
'${PY}' scripts/run_pipeline.py --config '${CONFIG}' --run-name '${name}' \
--categories '${category}' ${target_arg} ${shard_args} > '${LOG_DIR}/${name}.log' 2>&1; \
echo EXIT=\\\$? >> '${LOG_DIR}/${name}.log'"
  if [[ ${first} -eq 1 ]]; then
    tmux new-session -d -s "${SESSION}" -n "${win}" "bash -lc \"${cmd}\""
    first=0
  else
    tmux new-window -t "${SESSION}" -n "${win}" "bash -lc \"${cmd}\""
  fi
 done
done
echo "launched session=${SESSION} logs=${LOG_DIR}"
