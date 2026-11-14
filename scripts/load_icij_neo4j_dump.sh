#!/usr/bin/env bash
set -euo pipefail

NEO4J_VERSION="${NEO4J_VERSION:-5.26.0}"
TOOL_ROOT="${TOOL_ROOT:-${HOME}/pipecypher-tools}"
RUN_ROOT="${RUN_ROOT:-${HOME}/pipecypher-neo4j-icij}"
DOWNLOAD_DIR="${DOWNLOAD_DIR:-${HOME}/pipecypher-icij-offshoreleaks/downloads}"
DUMP_URL="${DUMP_URL:-https://offshoreleaks-data.icij.org/offshoreleaks/neo4j/icij-offshoreleaks-5.13.0.dump}"
DUMP_FILE="${DUMP_FILE:-${DOWNLOAD_DIR}/icij-offshoreleaks-5.13.0.dump}"
DATABASE="${DATABASE:-neo4j}"
SESSION="${SESSION:-pipecypher_neo4j_icij}"
BOLT_PORT="${BOLT_PORT:-7689}"
HTTP_PORT="${HTTP_PORT:-7476}"
AUTH_ENABLED="${AUTH_ENABLED:-false}"
HEAP_INITIAL="${HEAP_INITIAL:-6G}"
HEAP_MAX="${HEAP_MAX:-12G}"
PAGECACHE="${PAGECACHE:-8G}"

if tmux has-session -t "${SESSION}" 2>/dev/null; then
  echo "tmux session ${SESSION} is running; stop it before loading a dump" >&2
  exit 1
fi

mkdir -p "${TOOL_ROOT}" "${RUN_ROOT}" "${DOWNLOAD_DIR}"

download_to() {
  local url="$1"
  local out="$2"
  if [[ ! -f "${out}" ]]; then
    curl -fL -C - "${url}" -o "${out}"
  fi
}

JRE_HOME="${TOOL_ROOT}/temurin17-jre"
if [[ ! -x "${JRE_HOME}/bin/java" ]]; then
  rm -rf "${JRE_HOME}"
  mkdir -p "${JRE_HOME}"
  JRE_ARCHIVE="${TOOL_ROOT}/temurin17-jre.tar.gz"
  download_to "https://api.adoptium.net/v3/binary/latest/17/ga/linux/x64/jre/hotspot/normal/eclipse" "${JRE_ARCHIVE}"
  tar -xzf "${JRE_ARCHIVE}" --strip-components=1 -C "${JRE_HOME}"
fi

NEO4J_HOME="${TOOL_ROOT}/neo4j-community-${NEO4J_VERSION}"
if [[ ! -x "${NEO4J_HOME}/bin/neo4j-admin" ]]; then
  NEO4J_ARCHIVE="${TOOL_ROOT}/neo4j-community-${NEO4J_VERSION}-unix.tar.gz"
  download_to "https://dist.neo4j.org/neo4j-community-${NEO4J_VERSION}-unix.tar.gz" "${NEO4J_ARCHIVE}"
  tar -xzf "${NEO4J_ARCHIVE}" -C "${TOOL_ROOT}"
fi

download_to "${DUMP_URL}" "${DUMP_FILE}"

CONF_DIR="${RUN_ROOT}/conf"
DATA_DIR="${RUN_ROOT}/data"
IMPORT_DIR="${RUN_ROOT}/import"
LOG_DIR="${RUN_ROOT}/logs"
RUN_DIR="${RUN_ROOT}/run"
mkdir -p "${CONF_DIR}" "${DATA_DIR}" "${IMPORT_DIR}" "${LOG_DIR}" "${RUN_DIR}"

cat > "${CONF_DIR}/neo4j.conf" <<EOF
server.default_listen_address=0.0.0.0
server.bolt.listen_address=:${BOLT_PORT}
server.http.listen_address=:${HTTP_PORT}
dbms.security.auth_enabled=${AUTH_ENABLED}
server.directories.data=${DATA_DIR}
server.directories.import=${IMPORT_DIR}
server.directories.logs=${LOG_DIR}
server.directories.run=${RUN_DIR}
server.memory.heap.initial_size=${HEAP_INITIAL}
server.memory.heap.max_size=${HEAP_MAX}
server.memory.pagecache.size=${PAGECACHE}
db.tx_log.rotation.retention_policy=1 files
EOF

LOAD_DUMP_DIR="${RUN_ROOT}/load_dumps"
mkdir -p "${LOAD_DUMP_DIR}"
LOAD_DUMP_FILE="${LOAD_DUMP_DIR}/${DATABASE}.dump"
if [[ "$(readlink -f "${DUMP_FILE}")" != "$(readlink -f "${LOAD_DUMP_FILE}" 2>/dev/null || true)" ]]; then
  ln -sf "${DUMP_FILE}" "${LOAD_DUMP_FILE}"
fi

JAVA_HOME="${JRE_HOME}" PATH="${JRE_HOME}/bin:${PATH}" NEO4J_CONF="${CONF_DIR}" \
  "${NEO4J_HOME}/bin/neo4j-admin" database load "${DATABASE}" \
  --from-path="${LOAD_DUMP_DIR}" \
  --overwrite-destination=true

echo "loaded database=${DATABASE}"
echo "run_root=${RUN_ROOT}"
echo "dump_file=${DUMP_FILE}"
echo "start command:"
echo "RUN_ROOT='${RUN_ROOT}' SESSION='${SESSION}' BOLT_PORT='${BOLT_PORT}' HTTP_PORT='${HTTP_PORT}' AUTH_ENABLED='${AUTH_ENABLED}' HEAP_INITIAL='${HEAP_INITIAL}' HEAP_MAX='${HEAP_MAX}' PAGECACHE='${PAGECACHE}' scripts/start_neo4j_community.sh"
