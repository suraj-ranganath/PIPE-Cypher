#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-external}"
GIT_DEPTH="${GIT_DEPTH:-}"
mkdir -p "${ROOT}"
cd "${ROOT}"

clone_or_update() {
  local url="$1"
  local dir="$2"
  if [ -d "${dir}/.git" ]; then
    git -C "${dir}" fetch --all --tags --prune
  else
    if [ -n "${GIT_DEPTH}" ]; then
      git clone --depth "${GIT_DEPTH}" "${url}" "${dir}"
    else
      git clone "${url}" "${dir}"
    fi
  fi
  git -C "${dir}" rev-parse HEAD
}

echo "Fetching LDBC FinBench docs/spec..."
clone_or_update https://github.com/ldbc/ldbc_finbench_docs.git ldbc_finbench_docs

echo "Fetching LDBC FinBench datagen..."
clone_or_update https://github.com/ldbc/ldbc_finbench_datagen.git ldbc_finbench_datagen

echo "Fetching LDBC SNB datagen..."
clone_or_update https://github.com/ldbc/ldbc_snb_datagen_spark.git ldbc_snb_datagen_spark

echo "Fetching LDBC SNB interactive implementations..."
clone_or_update https://github.com/ldbc/ldbc_snb_interactive_v1_impls.git ldbc_snb_interactive_v1_impls
