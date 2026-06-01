#!/usr/bin/env bash
set -euo pipefail

HOST="${HOST:-suraj@ds-serv6.ucsd.edu}"
REMOTE_DIR="${REMOTE_DIR:-/home/suraj/PIPE-Cypher}"
SESSION="${SESSION:-pipecypher_vllm}"
MODEL="${MODEL:-Qwen/Qwen3.5-9B}"
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-${MODEL}}"
PORT="${PORT:-8000}"
CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-2,3}"
CONDA_ENV="${CONDA_ENV:-pipe-rdf-arr}"
TENSOR_PARALLEL_SIZE="${TENSOR_PARALLEL_SIZE:-}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-8192}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.88}"
EXTRA_VLLM_ARGS="${EXTRA_VLLM_ARGS:-}"

quote() {
  printf "%q" "$1"
}

ssh "${HOST}" bash -s <<REMOTE
set -euo pipefail

REMOTE_DIR=$(quote "${REMOTE_DIR}")
SESSION=$(quote "${SESSION}")
MODEL=$(quote "${MODEL}")
SERVED_MODEL_NAME=$(quote "${SERVED_MODEL_NAME}")
PORT=$(quote "${PORT}")
CUDA_VISIBLE_DEVICES=$(quote "${CUDA_VISIBLE_DEVICES}")
CONDA_ENV=$(quote "${CONDA_ENV}")
TENSOR_PARALLEL_SIZE=$(quote "${TENSOR_PARALLEL_SIZE}")
MAX_MODEL_LEN=$(quote "${MAX_MODEL_LEN}")
GPU_MEMORY_UTILIZATION=$(quote "${GPU_MEMORY_UTILIZATION}")
EXTRA_VLLM_ARGS=$(quote "${EXTRA_VLLM_ARGS}")

cd "\${REMOTE_DIR}"
mkdir -p logs
if tmux has-session -t "\${SESSION}" 2>/dev/null; then
  echo "tmux session \${SESSION} already exists"
  exit 0
fi

remote_quote() {
  printf "%q" "\$1"
}

LOG_PATH="logs/vllm_\${PORT}.log"
TMUX_CMD="CONDA_ENV=\$(remote_quote "\${CONDA_ENV}") CUDA_VISIBLE_DEVICES=\$(remote_quote "\${CUDA_VISIBLE_DEVICES}") PORT=\$(remote_quote "\${PORT}") SERVED_MODEL_NAME=\$(remote_quote "\${SERVED_MODEL_NAME}") TENSOR_PARALLEL_SIZE=\$(remote_quote "\${TENSOR_PARALLEL_SIZE}") MAX_MODEL_LEN=\$(remote_quote "\${MAX_MODEL_LEN}") GPU_MEMORY_UTILIZATION=\$(remote_quote "\${GPU_MEMORY_UTILIZATION}") EXTRA_VLLM_ARGS=\$(remote_quote "\${EXTRA_VLLM_ARGS}") bash scripts/serve_qwen_vllm.sh \$(remote_quote "\${MODEL}") 2>&1 | tee \$(remote_quote "\${LOG_PATH}")"
tmux new-session -d -s "\${SESSION}" "\${TMUX_CMD}"
echo "started session=\${SESSION} model=\${MODEL} served_model_name=\${SERVED_MODEL_NAME} port=\${PORT} gpus=\${CUDA_VISIBLE_DEVICES}"
REMOTE
