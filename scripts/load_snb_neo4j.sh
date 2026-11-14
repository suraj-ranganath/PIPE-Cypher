#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NEO4J_VERSION="${NEO4J_VERSION:-5.26.0}"
TOOL_ROOT="${TOOL_ROOT:-${HOME}/pipecypher-tools}"
RUN_ROOT="${RUN_ROOT:-${HOME}/pipecypher-neo4j-snb}"
NEO4J_HOME="${NEO4J_HOME:-${TOOL_ROOT}/neo4j-community-${NEO4J_VERSION}}"
JRE_HOME="${JRE_HOME:-${TOOL_ROOT}/temurin17-jre}"
IMPORT_DIR="${IMPORT_DIR:-${RUN_ROOT}/import}"
SNB_IMPL_DIR="${SNB_IMPL_DIR:-${PROJECT_ROOT}/external/ldbc_snb_interactive_v1_impls/cypher}"
VANILLA_DIR="${VANILLA_DIR:-${SNB_IMPL_DIR}/test-data/vanilla}"
CONVERTED_DIR="${CONVERTED_DIR:-${RUN_ROOT}/snb_converted}"
IMPORT_CYPHER="${IMPORT_CYPHER:-${RUN_ROOT}/snb_load.cypher}"
BOLT_URI="${BOLT_URI:-bolt://localhost:7688}"
NEO4J_DATABASE="${NEO4J_DATABASE:-neo4j}"
AUTH_ENABLED="${AUTH_ENABLED:-false}"
NEO4J_USER="${NEO4J_USER:-neo4j}"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-password}"
CLEAR_DB="${CLEAR_DB:-true}"

if [[ ! -x "${NEO4J_HOME}/bin/cypher-shell" ]]; then
  echo "Missing cypher-shell at ${NEO4J_HOME}/bin/cypher-shell" >&2
  echo "Run scripts/start_neo4j_community.sh first." >&2
  exit 1
fi
if [[ ! -d "${VANILLA_DIR}" ]]; then
  echo "Missing SNB vanilla CSV directory: ${VANILLA_DIR}" >&2
  exit 1
fi

mkdir -p "${CONVERTED_DIR}" "${IMPORT_DIR}/snb"

(
  cd "${SNB_IMPL_DIR}"
  NEO4J_VANILLA_CSV_DIR="${VANILLA_DIR}" \
  NEO4J_CONVERTED_CSV_DIR="${CONVERTED_DIR}" \
  scripts/convert-csvs.sh
)

ln -sfn "${CONVERTED_DIR}" "${IMPORT_DIR}/snb/converted"

python3 "${PROJECT_ROOT}/scripts/generate_snb_import_cypher.py" \
  --csv-base-url "file:///snb/converted" \
  --output "${IMPORT_CYPHER}"

export JAVA_HOME="${JRE_HOME}"
export PATH="${JRE_HOME}/bin:${PATH}"

CYPHER_SHELL=("${NEO4J_HOME}/bin/cypher-shell" -a "${BOLT_URI}" -d "${NEO4J_DATABASE}")
if [[ "${AUTH_ENABLED}" == "true" ]]; then
  CYPHER_SHELL+=(-u "${NEO4J_USER}" -p "${NEO4J_PASSWORD}")
fi

if [[ "${CLEAR_DB}" == "true" ]]; then
  printf "MATCH (n) DETACH DELETE n;\n" | "${CYPHER_SHELL[@]}"
fi

"${CYPHER_SHELL[@]}" -f "${IMPORT_CYPHER}"

printf "MATCH (n) RETURN labels(n) AS labels, count(*) AS count ORDER BY count DESC LIMIT 20;\n" |
  "${CYPHER_SHELL[@]}"
printf "MATCH ()-[r]->() RETURN type(r) AS relType, count(*) AS count ORDER BY count DESC LIMIT 20;\n" |
  "${CYPHER_SHELL[@]}"
