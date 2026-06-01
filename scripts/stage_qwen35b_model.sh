#!/usr/bin/env bash
set -euo pipefail

MODEL="${MODEL:-Qwen/Qwen3.5-35B-A3B}"
LOCAL_DIR="${LOCAL_DIR:-/home/suraj/pipecypher-models/Qwen3.5-35B-A3B}"
CONDA_ENV="${CONDA_ENV:-pipe-rdf-arr}"
MAX_WORKERS="${MAX_WORKERS:-4}"

if [[ -f "${HOME}/miniforge3/etc/profile.d/conda.sh" ]]; then
  # shellcheck disable=SC1091
  source "${HOME}/miniforge3/etc/profile.d/conda.sh"
  conda activate "${CONDA_ENV}"
fi

mkdir -p "${LOCAL_DIR}"

hf download "${MODEL}" \
  --local-dir "${LOCAL_DIR}" \
  --max-workers "${MAX_WORKERS}" \
  --include "*.safetensors" \
  --include "*.json" \
  --include "*.model" \
  --include "*.txt" \
  --include "*.py" \
  --include "tokenizer*" \
  --exclude "*.bin" \
  --exclude "*.h5" \
  --exclude "*.msgpack"

echo "staged ${MODEL} at ${LOCAL_DIR}"
