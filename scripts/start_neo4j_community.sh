#!/usr/bin/env bash
set -euo pipefail

NEO4J_VERSION="${NEO4J_VERSION:-5.26.0}"
TOOL_ROOT="${TOOL_ROOT:-${HOME}/pipecypher-tools}"
RUN_ROOT="${RUN_ROOT:-${HOME}/pipecypher-neo4j}"
SESSION="${SESSION:-pipecypher_neo4j}"
BOLT_PORT="${BOLT_PORT:-7687}"
HTTP_PORT="${HTTP_PORT:-7474}"
AUTH_ENABLED="${AUTH_ENABLED:-false}"
HEAP_INITIAL="${HEAP_INITIAL:-4G}"
HEAP_MAX="${HEAP_MAX:-8G}"
PAGECACHE="${PAGECACHE:-4G}"

mkdir -p "${TOOL_ROOT}" "${RUN_ROOT}"

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
if [[ ! -x "${NEO4J_HOME}/bin/neo4j" ]]; then
  NEO4J_ARCHIVE="${TOOL_ROOT}/neo4j-community-${NEO4J_VERSION}-unix.tar.gz"
  download_to "https://dist.neo4j.org/neo4j-community-${NEO4J_VERSION}-unix.tar.gz" "${NEO4J_ARCHIVE}"
  tar -xzf "${NEO4J_ARCHIVE}" -C "${TOOL_ROOT}"
fi

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

if tmux has-session -t "${SESSION}" 2>/dev/null; then
  echo "tmux session ${SESSION} already exists"
  exit 0
fi

tmux new-session -d -s "${SESSION}" \
  "JAVA_HOME='${JRE_HOME}' PATH='${JRE_HOME}/bin:${PATH}' NEO4J_CONF='${CONF_DIR}' '${NEO4J_HOME}/bin/neo4j' console 2>&1 | tee '${LOG_DIR}/neo4j_console.log'"

echo "started session=${SESSION}"
echo "neo4j_home=${NEO4J_HOME}"
echo "conf_dir=${CONF_DIR}"
echo "import_dir=${IMPORT_DIR}"
echo "bolt=bolt://localhost:${BOLT_PORT}"
echo "http=http://localhost:${HTTP_PORT}"
