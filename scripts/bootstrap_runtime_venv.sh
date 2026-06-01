#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${VENV_DIR:-${HOME}/pipecypher-tools/runtime-venv}"
PYTHON_BIN="${PYTHON_BIN:-}"
INSTALL_DEV="${INSTALL_DEV:-false}"

if [[ -z "${PYTHON_BIN}" ]]; then
  if [[ -x "${HOME}/miniforge3/envs/pipe-rdf-arr/bin/python" ]]; then
    PYTHON_BIN="${HOME}/miniforge3/envs/pipe-rdf-arr/bin/python"
  else
    PYTHON_BIN="$(command -v python3)"
  fi
fi

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

"${VENV_DIR}/bin/python" -m pip install --upgrade pip
if [[ "${INSTALL_DEV}" == "true" ]]; then
  "${VENV_DIR}/bin/python" -m pip install -e "${PROJECT_ROOT}[dev]"
else
  "${VENV_DIR}/bin/python" -m pip install -e "${PROJECT_ROOT}"
fi

echo "runtime_venv=${VENV_DIR}"
