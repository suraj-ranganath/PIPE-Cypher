#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python}"
TARGET_PER_CATEGORY="${TARGET_PER_CATEGORY:-25}"
RUN_PREFIX="${RUN_PREFIX:-$(date +%Y%m%d_%H%M%S)_ablation${TARGET_PER_CATEGORY}}"
OUTPUT_ROOT="${OUTPUT_ROOT:-configs/generated_ablation${TARGET_PER_CATEGORY}}"
GENERATION_MODEL="${GENERATION_MODEL:-Qwen/Qwen3.5-9B}"
JUDGE_MODEL="${JUDGE_MODEL:-${GENERATION_MODEL}}"
RUN_SEED="${RUN_SEED:-}"
GRAPH_SET="${GRAPH_SET:-finbench snb}"
DEFAULT_VARIANTS="unconstrained_local_llm reverse_only validators_repair"
DEFAULT_VARIANTS+=" ablation_retrieval_topk_0 ablation_rewrite_false"
DEFAULT_VARIANTS+=" ablation_judge_false full_pipe_cypher"
VARIANT_SET="${VARIANT_SET:-${DEFAULT_VARIANTS}}"
LOG_DIR="${LOG_DIR:-logs}"
LOG_FILE="${LOG_FILE:-${LOG_DIR}/${RUN_PREFIX}.log}"
CODE_REVISION="${CODE_REVISION:-$(git rev-parse HEAD 2>/dev/null || printf 'unavailable')}"
SUMMARY_DIR="${SUMMARY_DIR:-experiments/snapshots/${RUN_PREFIX}}"

mkdir -p "${LOG_DIR}"

log() {
  printf '%s\n' "$*" | tee -a "${LOG_FILE}"
}

materialize_graph() {
  local graph="$1"
  local base_config="$2"
  local output_dir="${OUTPUT_ROOT}/${graph}"
  log "materialize graph=${graph} target_per_category=${TARGET_PER_CATEGORY} output=${output_dir}"
  "${PYTHON_BIN}" scripts/materialize_experiments.py \
    --base-config "${base_config}" \
    --output-dir "${output_dir}" \
    --target-per-category "${TARGET_PER_CATEGORY}" | tee -a "${LOG_FILE}"
}

config_for_graph() {
  local graph="$1"
  case "${graph}" in
    finbench) printf '%s\n' "configs/finbench_full.yaml" ;;
    snb) printf '%s\n' "configs/snb_full.yaml" ;;
    *)
      printf 'Unknown graph in GRAPH_SET: %s\n' "${graph}" >&2
      return 1
      ;;
  esac
}

run_variant() {
  local graph="$1"
  local variant="$2"
  local config="${OUTPUT_ROOT}/${graph}/${variant}.yaml"
  if [[ ! -f "${config}" ]]; then
    log "skip missing_config graph=${graph} variant=${variant} config=${config}"
    return 0
  fi
  log "run graph=${graph} variant=${variant} config=${config}"
  local seed_args=()
  if [[ -n "${RUN_SEED}" ]]; then
    seed_args+=(--random-seed "${RUN_SEED}")
  fi
  PIPE_CYPHER_LLM_MODEL="${GENERATION_MODEL}" \
  PIPE_CYPHER_RANDOM_SEED="${RUN_SEED}" \
  PIPE_CYPHER_JUDGE_MODEL="${JUDGE_MODEL}" \
    "${PYTHON_BIN}" scripts/run_pipeline.py \
      --config "${config}" \
      --run-name "${RUN_PREFIX}_${graph}_${variant}" \
      "${seed_args[@]}" 2>&1 | tee -a "${LOG_FILE}"
}

log "run_prefix=${RUN_PREFIX}"
log "target_per_category=${TARGET_PER_CATEGORY}"
log "generation_model=${GENERATION_MODEL}"
log "judge_model=${JUDGE_MODEL}"
log "run_seed=${RUN_SEED}"
log "graph_set=${GRAPH_SET}"
log "variant_set=${VARIANT_SET}"
log "code_revision=${CODE_REVISION}"
log "summary_dir=${SUMMARY_DIR}"

for graph in ${GRAPH_SET}; do
  materialize_graph "${graph}" "$(config_for_graph "${graph}")"
done

for graph in ${GRAPH_SET}; do
  for variant in ${VARIANT_SET}; do
    run_variant "${graph}" "${variant}"
  done
done

mkdir -p "${SUMMARY_DIR}"
summary_args=(
  --glob "artifacts/runs/*${RUN_PREFIX}*"
  --target-per-category "${TARGET_PER_CATEGORY}"
  --output-json "${SUMMARY_DIR}/ablation_suite_summary.json"
  --output-md "${SUMMARY_DIR}/ablation_suite_summary.md"
  --output-csv "${SUMMARY_DIR}/ablation_suite_summary.csv"
  --output-audit-json "${SUMMARY_DIR}/ablation_suite_audit.json"
  --output-audit-md "${SUMMARY_DIR}/ablation_suite_audit.md"
  --metadata "run_prefix=${RUN_PREFIX}"
  --metadata "generation_model=${GENERATION_MODEL}"
  --metadata "judge_model=${JUDGE_MODEL}"
  --metadata "run_seed=${RUN_SEED}"
  --metadata "code_revision=${CODE_REVISION}"
  --metadata "log_file=${LOG_FILE}"
)
for graph in ${GRAPH_SET}; do
  summary_args+=(--expected-graph "${graph}")
done
for variant in ${VARIANT_SET}; do
  summary_args+=(--expected-variant "${variant}")
done
"${PYTHON_BIN}" scripts/summarize_live_ablation_suite.py "${summary_args[@]}" 2>&1 | tee -a "${LOG_FILE}"

log "done run_prefix=${RUN_PREFIX}"
