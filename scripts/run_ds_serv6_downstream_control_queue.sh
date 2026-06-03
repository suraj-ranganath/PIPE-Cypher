#!/usr/bin/env bash
set -euo pipefail

GPU_ID="${GPU_ID:-2}"
PORT="${PORT:-8000}"
BENCHMARK="${BENCHMARK:-artifacts/benchmarks/20260601_live_full_qwen9b}"
SPLIT="${SPLIT:-test}"
WAIT_SESSION="${WAIT_SESSION:-pipecypher_downstream_controls_qwen}"
KILL_SESSION_AFTER_WAIT="${KILL_SESSION_AFTER_WAIT:-pipecypher_vllm_controls_qwen}"
ENDPOINT_TAG="${ENDPOINT_TAG:-downstream_controls}"
MODEL_SET="${MODEL_SET:-all}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-4096}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.88}"
BASE_VLLM_ARGS="${BASE_VLLM_ARGS:---no-enable-flashinfer-autotune --enforce-eager --max-num-seqs 1 --max-num-batched-tokens 4096}"

wait_for_session() {
  local session="$1"
  if [[ -z "${session}" ]]; then
    return 0
  fi
  while tmux has-session -t "${session}" 2>/dev/null; do
    printf 'waiting_for_session=%s ' "${session}"
    date -u '+at_utc=%Y-%m-%dT%H:%M:%SZ'
    sleep 60
  done
}

wait_for_endpoint() {
  local url="$1"
  local max_wait_sec="${2:-900}"
  local start
  start="$(date +%s)"
  until curl -fsS "${url}/models" >/dev/null; do
    if (( "$(date +%s)" - start > max_wait_sec )); then
      echo "endpoint did not become healthy: ${url}" >&2
      return 1
    fi
    sleep 20
  done
}

run_fewshot_controls() {
  local slug="$1"
  local model_name="$2"
  local system_mode="$3"
  local base_url="http://localhost:${PORT}/v1"
  local prefix

  prefix="20260603_control_${slug}_ordered_logged"
  run_one_control "${prefix}" "${model_name}" "${system_mode}" ordered_same_category 13 false

  prefix="20260603_control_${slug}_scored_no_signature"
  run_one_control "${prefix}" "${model_name}" "${system_mode}" scored_no_signature 13 true

  for seed in 13 17 23; do
    prefix="20260603_control_${slug}_random_seed${seed}"
    run_one_control "${prefix}" "${model_name}" "${system_mode}" random_same_category "${seed}" false
  done
}

run_one_control() {
  local prefix="$1"
  local model_name="$2"
  local system_mode="$3"
  local mode="$4"
  local seed="$5"
  local exclude_signature="$6"
  local out_dir="artifacts/evaluations/${prefix}"

  if [[ -s "${out_dir}/few_shot_summary.json" ]] && [[ -s "${out_dir}/few_shot_selection.jsonl" ]]; then
    echo "skip_existing=${out_dir}"
    return 0
  fi

  RUN_PREFIX="${prefix}" \
  BENCHMARK="${BENCHMARK}" \
  SPLIT="${SPLIT}" \
  BASE_URL="http://localhost:${PORT}/v1" \
  MODEL="${model_name}" \
  FEW_SHOT_K=5 \
  FEW_SHOT_MODE="${mode}" \
  FEW_SHOT_SEED="${seed}" \
  FEW_SHOT_EXCLUDE_SIGNATURE_MATCH="${exclude_signature}" \
  FEW_SHOT_MAX_QUESTION_SIM=0.90 \
  SYSTEM_MESSAGE_MODE="${system_mode}" \
    bash scripts/run_downstream_fewshot_only_eval.sh
}

serve_vllm_and_run() {
  local slug="$1"
  local served_model_name="$2"
  local model_path="$3"
  local system_mode="$4"
  local extra_args="${5:-}"
  local endpoint_pid=""
  local log_path="logs/vllm_${PORT}_${slug}_${ENDPOINT_TAG}.log"

  echo "starting_model=${slug} served_model_name=${served_model_name} model_path=${model_path}"
  CUDA_VISIBLE_DEVICES="${GPU_ID}" \
  PORT="${PORT}" \
  SERVED_MODEL_NAME="${served_model_name}" \
  TENSOR_PARALLEL_SIZE=1 \
  MAX_MODEL_LEN="${MAX_MODEL_LEN}" \
  GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION}" \
  EXTRA_VLLM_ARGS="${BASE_VLLM_ARGS} ${extra_args}" \
    bash scripts/serve_qwen_vllm.sh "${model_path}" > "${log_path}" 2>&1 &
  endpoint_pid="$!"

  if ! wait_for_endpoint "http://localhost:${PORT}/v1"; then
    kill "${endpoint_pid}" 2>/dev/null || true
    wait "${endpoint_pid}" 2>/dev/null || true
    return 1
  fi

  run_fewshot_controls "${slug}" "${served_model_name}" "${system_mode}" || {
    kill "${endpoint_pid}" 2>/dev/null || true
    wait "${endpoint_pid}" 2>/dev/null || true
    return 1
  }

  kill "${endpoint_pid}" 2>/dev/null || true
  wait "${endpoint_pid}" 2>/dev/null || true
  sleep 30
}

run_transformers_controls() {
  local slug="stable_cypher_instruct3b_transformers"
  local model_name="ragraph-ai/stable-cypher-instruct-3b"
  local prefix

  for spec in \
    "ordered_same_category 13 false ordered_logged" \
    "scored_no_signature 13 true scored_no_signature" \
    "random_same_category 13 false random_seed13" \
    "random_same_category 17 false random_seed17" \
    "random_same_category 23 false random_seed23"; do
    read -r mode seed exclude suffix <<< "${spec}"
    prefix="20260603_control_${slug}_${suffix}"
    local out_dir="artifacts/evaluations/${prefix}"
    if [[ -s "${out_dir}/few_shot_summary.json" ]] && [[ -s "${out_dir}/few_shot_selection.jsonl" ]]; then
      echo "skip_existing=${out_dir}"
      continue
    fi
    mkdir -p "${out_dir}"
    {
      printf 'run_prefix=%s\n' "${prefix}"
      printf 'code_revision=%s\n' "$(git rev-parse HEAD 2>/dev/null || printf unknown)"
      printf 'benchmark=%s\n' "${BENCHMARK}"
      printf 'split=%s\n' "${SPLIT}"
      printf 'model=%s\n' "${model_name}"
      printf 'runner=transformers_bitsandbytes\n'
      printf 'few_shot_mode=%s\n' "${mode}"
      printf 'few_shot_seed=%s\n' "${seed}"
      printf 'few_shot_exclude_signature_match=%s\n' "${exclude}"
      date -u '+launched_at_utc=%Y-%m-%dT%H:%M:%SZ'
    } > "${out_dir}/run_metadata.txt"
    CUDA_VISIBLE_DEVICES="${GPU_ID}" python scripts/generate_text2cypher_predictions_transformers.py \
      --benchmark "${BENCHMARK}" \
      --split "${SPLIT}" \
      --schema finbench=configs/schema_finbench.json \
      --schema snb=configs/schema_snb.json \
      --output "${out_dir}/few_shot_predictions.jsonl" \
      --model "${model_name}" \
      --few-shot "${BENCHMARK}/train.jsonl" \
      --few-shot-k 5 \
      --few-shot-mode "${mode}" \
      --few-shot-seed "${seed}" \
      --few-shot-max-question-sim 0.90 \
      --few-shot-log "${out_dir}/few_shot_selection.jsonl" \
      --device-map single_cuda \
      --load-in-8bit \
      $(if [[ "${exclude}" == "true" ]]; then printf '%s' "--few-shot-exclude-signature-match"; fi)
    python scripts/evaluate_benchmark_predictions.py \
      --benchmark "${BENCHMARK}" \
      --split "${SPLIT}" \
      --predictions "${out_dir}/few_shot_predictions.jsonl" \
      --config finbench=configs/finbench_full.yaml \
      --config snb=configs/snb_full.yaml \
      --output "${out_dir}/few_shot_evaluation.jsonl" \
      --summary-output "${out_dir}/few_shot_summary.json"
  done
}

run_or_log() {
  local label="$1"
  shift
  "$@" && return 0
  local status=$?
  mkdir -p logs
  {
    date -u '+failed_at_utc=%Y-%m-%dT%H:%M:%SZ'
    printf 'label=%s\n' "${label}"
    printf 'status=%s\n' "${status}"
    printf 'command=%q' "$@"
    printf '\n'
  } >> "logs/20260603_downstream_control_queue_failures.log"
  echo "failed_label=${label} status=${status}; continuing"
  return 0
}

main() {
  mkdir -p logs artifacts/evaluations
  wait_for_session "${WAIT_SESSION}"
  if [[ -n "${KILL_SESSION_AFTER_WAIT}" ]]; then
    tmux kill-session -t "${KILL_SESSION_AFTER_WAIT}" 2>/dev/null || true
  fi
  sleep 30

  case "${MODEL_SET}" in
    all|direct)
      run_or_log qwen25_coder7b serve_vllm_and_run qwen25_coder7b "Qwen/Qwen2.5-Coder-7B-Instruct" "Qwen/Qwen2.5-Coder-7B-Instruct" separate
      run_or_log gemma2_9b_it serve_vllm_and_run gemma2_9b_it "google/gemma-2-9b-it" "google/gemma-2-9b-it" merge
      run_or_log tomasonjo_text2cypher8b serve_vllm_and_run tomasonjo_text2cypher8b "tomasonjo/text2cypher-demo-16bit" "tomasonjo/text2cypher-demo-16bit" separate
      run_or_log neo4j_gemma3_4b serve_vllm_and_run neo4j_gemma3_4b "neo4j/text-to-cypher-Gemma-3-4B-Instruct-2025.04.0" "neo4j/text-to-cypher-Gemma-3-4B-Instruct-2025.04.0" separate
      run_or_log azzedde_llama31_text2cypher serve_vllm_and_run azzedde_llama31_text2cypher "Azzedde/llama3.1-8b-text2cypher" "Azzedde/llama3.1-8b-text2cypher" separate
      ;;
  esac

  case "${MODEL_SET}" in
    all|lora|lora_stable|neo4j_gemma2_lora)
      run_or_log neo4j_gemma2_text2cypher_lora serve_vllm_and_run neo4j_gemma2_text2cypher_lora "neo4j_gemma2_text2cypher_lora" "google/gemma-2-9b-it" merge "--enable-lora --max-lora-rank 64 --lora-modules neo4j_gemma2_text2cypher_lora=neo4j/text2cypher-gemma-2-9b-it-finetuned-2024v1"
      ;;
  esac

  case "${MODEL_SET}" in
    all|lora|lora_stable)
      run_or_log aigentx_llama31_cypher_lora serve_vllm_and_run aigentx_llama31_cypher_lora "aigentx_llama31_cypher" "unsloth/meta-llama-3.1-8b-instruct-unsloth-bnb-4bit" separate "--enable-lora --lora-modules aigentx_llama31_cypher=aigentx/llama-3.1-8b-instruct-cypher"
      run_or_log aigentx_llama31_cypher_mixed_lora serve_vllm_and_run aigentx_llama31_cypher_mixed_lora "aigentx_llama31_cypher_mixed" "unsloth/meta-llama-3.1-8b-instruct-unsloth-bnb-4bit" separate "--enable-lora --lora-modules aigentx_llama31_cypher_mixed=aigentx/llama-3.1-8b-instruct-cypher-mixed-samples"
      run_or_log projectwilsen_llama31_text2cypher_lora serve_vllm_and_run projectwilsen_llama31_text2cypher_lora "projectwilsen_llama31_text2cypher_template" "unsloth/meta-llama-3.1-8b-bnb-4bit" separate "--enable-lora --lora-modules projectwilsen_llama31_text2cypher_template=projectwilsen/llama3.1-8b-text2cypher-neo4j-live --chat-template configs/chat_templates/plain_generation.jinja"
      run_or_log saiprasanth_llama31_text2cypher_lora serve_vllm_and_run saiprasanth_llama31_text2cypher_lora "saiprasanth_llama31_text2cypher_template" "unsloth/meta-llama-3.1-8b-bnb-4bit" separate "--enable-lora --lora-modules saiprasanth_llama31_text2cypher_template=Saiprasanth15/llama3.1-8b-text2cypher-neo4j-live --chat-template configs/chat_templates/plain_generation.jinja"
      ;;
  esac

  case "${MODEL_SET}" in
    all|stable|lora_stable)
      run_or_log stable_cypher_instruct3b_transformers run_transformers_controls
      ;;
    direct|lora|neo4j_gemma2_lora)
      ;;
    *)
      echo "unknown MODEL_SET=${MODEL_SET}" >&2
      return 2
      ;;
  esac
  date -u '+completed_at_utc=%Y-%m-%dT%H:%M:%SZ'
}

main "$@"
