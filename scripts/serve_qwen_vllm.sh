#!/usr/bin/env bash
set -euo pipefail

MODEL="${1:-Qwen/Qwen3.5-9B}"
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-${MODEL}}"
PORT="${PORT:-8000}"
GPU_IDS="${CUDA_VISIBLE_DEVICES:-2,3}"
CONDA_ENV="${CONDA_ENV:-}"
CONDA_ROOT="${CONDA_ROOT:-$HOME/miniforge3}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.88}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-8192}"
EXTRA_VLLM_ARGS="${EXTRA_VLLM_ARGS:-}"

if [[ -n "${CONDA_ENV}" ]]; then
  if [[ -f "${CONDA_ROOT}/etc/profile.d/conda.sh" ]]; then
    # shellcheck disable=SC1091
    source "${CONDA_ROOT}/etc/profile.d/conda.sh"
  else
    eval "$("${CONDA_ROOT}/bin/conda" shell.bash hook)"
  fi
  conda activate "${CONDA_ENV}"
fi

export CUDA_VISIBLE_DEVICES="${GPU_IDS}"
export VLLM_USE_FLASHINFER_SAMPLER="${VLLM_USE_FLASHINFER_SAMPLER:-0}"
if [[ -z "${TENSOR_PARALLEL_SIZE:-}" ]]; then
  TENSOR_PARALLEL_SIZE="$(python - <<'PY'
import os
ids = [x for x in os.environ.get("CUDA_VISIBLE_DEVICES", "").split(",") if x.strip()]
print(max(1, len(ids)))
PY
)"
fi

python -m vllm.entrypoints.openai.api_server \
  --host 0.0.0.0 \
  --port "${PORT}" \
  --model "${MODEL}" \
  --served-model-name "${SERVED_MODEL_NAME}" \
  --tensor-parallel-size "${TENSOR_PARALLEL_SIZE}" \
  --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION}" \
  --max-model-len "${MAX_MODEL_LEN}" \
  --trust-remote-code \
  ${EXTRA_VLLM_ARGS} \
  "${@:2}"
