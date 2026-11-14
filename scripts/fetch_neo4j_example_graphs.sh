#!/usr/bin/env bash
# Download public Neo4j example-graph dumps (github.com/neo4j-graph-examples) and
# load each into its own Neo4j Community 5.x instance, one database per instance.
#
# Usage:
#   scripts/fetch_neo4j_example_graphs.sh [DOWNLOAD_DIR]
#
# Environment (defaults in brackets):
#   GRAPHS          space-separated graph names [recommendations northwind fincen]
#                   (also available: network movies)
#   DOWNLOAD_DIR    dump directory; the first positional argument wins
#                   [${HOME}/pipecypher-neo4j-example-graphs/downloads]
#   RUN_ROOT_BASE   per-graph Neo4j run roots live in ${RUN_ROOT_BASE}/<graph>
#                   [${HOME}/pipecypher-neo4j-t2c]
#   DOWNLOAD_ONLY   true = download + verify dumps, do not load [false]
#   START           true = start each loaded instance in tmux via
#                   scripts/start_neo4j_community.sh [true]
#   VERIFY_SHA256   false = skip the pinned sha256 check (not recommended) [true]
#   NEO4J_VERSION, TOOL_ROOT, AUTH_ENABLED, HEAP_INITIAL, HEAP_MAX, PAGECACHE
#                   as in scripts/load_icij_neo4j_dump.sh
#
# Conventions mirror scripts/load_icij_neo4j_dump.sh: Temurin 17 JRE + Neo4j
# Community tarball under TOOL_ROOT, per-instance conf/data/import/logs/run dirs,
# `neo4j-admin database load` with --overwrite-destination, tmux session per
# instance, and a refusal to touch an instance whose tmux session is running.
#
# Dump URLs are pinned to repository commits and sha256-verified (checked
# 2026-11-11). Bolt ports match configs/t2c_<graph>.yaml and
# pipecypher/external_benchmarks.py:EXAMPLE_GRAPHS.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

GRAPHS="${GRAPHS:-recommendations northwind fincen}"
DOWNLOAD_DIR="${1:-${DOWNLOAD_DIR:-${HOME}/pipecypher-neo4j-example-graphs/downloads}}"
RUN_ROOT_BASE="${RUN_ROOT_BASE:-${HOME}/pipecypher-neo4j-t2c}"
DOWNLOAD_ONLY="${DOWNLOAD_ONLY:-false}"
START="${START:-true}"
VERIFY_SHA256="${VERIFY_SHA256:-true}"
NEO4J_VERSION="${NEO4J_VERSION:-5.26.0}"
TOOL_ROOT="${TOOL_ROOT:-${HOME}/pipecypher-tools}"
DATABASE="neo4j"
AUTH_ENABLED="${AUTH_ENABLED:-false}"
HEAP_INITIAL="${HEAP_INITIAL:-1G}"
HEAP_MAX="${HEAP_MAX:-2G}"
PAGECACHE="${PAGECACHE:-1G}"

# name -> "repo commit dump_path sha256 bolt_port http_port"
graph_spec() {
  case "$1" in
    recommendations)
      echo "neo4j-graph-examples/recommendations f5a3f87b9fa73461750eef564ce8b81f304d940b data/recommendations-50.dump c22134f5ef8e8239856003134bf746d77b705bc538e40bd7c1fa034673453734 7701 7501" ;;
    northwind)
      echo "neo4j-graph-examples/northwind 56ee0507d33eecd8ef2a9c960ec967cd432eb57e data/northwind-50.dump 3aef3fdf2f9e6a7e6e813d7fcd4e46a8ea7e75573ee7d4fb84f6884ec1f66b9f 7702 7502" ;;
    fincen)
      echo "neo4j-graph-examples/fincen 41c8ef891e0f7624294cbf6ff8c4b57eda8d9c15 data/fincen-50.dump e0e8f0a5616ef50fa9407a1ee02138f027df6e4a1c2c6d3585e25e88119016b8 7703 7503" ;;
    network)
      echo "neo4j-graph-examples/network-management 15d4a47c0f579d8f2c73ecd76d4e3d9c74f7ecea data/network-management-50.dump 0c54b653a56396191f37a2e0750a52abef649ad542ca6d73802496e46d30ed60 7704 7504" ;;
    movies)
      echo "neo4j-graph-examples/movies 51cf90d18c1a7f74bce7a77083543697dfb0139d data/movies-50.dump 806ea150f5ce7387173e4ba54a8e0054f282e2f2021d4245117807744933a886 7705 7505" ;;
    *)
      return 1 ;;
  esac
}

download_to() {
  local url="$1"
  local out="$2"
  if [[ ! -f "${out}" ]]; then
    curl -fL -C - "${url}" -o "${out}.part"
    mv "${out}.part" "${out}"
  fi
}

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

# Validate every requested graph before downloading or touching any instance.
for graph in ${GRAPHS}; do
  if ! graph_spec "${graph}" >/dev/null; then
    echo "unknown graph '${graph}'; choose from: recommendations northwind fincen network movies" >&2
    exit 2
  fi
  if [[ "${DOWNLOAD_ONLY}" != "true" ]] && tmux has-session -t "pipecypher_neo4j_t2c_${graph}" 2>/dev/null; then
    echo "tmux session pipecypher_neo4j_t2c_${graph} is running; stop it before loading a dump" >&2
    exit 1
  fi
done

mkdir -p "${DOWNLOAD_DIR}"

for graph in ${GRAPHS}; do
  read -r repo commit dump_path sha256 bolt_port http_port <<<"$(graph_spec "${graph}")"
  url="https://raw.githubusercontent.com/${repo}/${commit}/${dump_path}"
  graph_dir="${DOWNLOAD_DIR}/${graph}"
  mkdir -p "${graph_dir}"
  dump_file="${graph_dir}/$(basename "${dump_path}")"
  download_to "${url}" "${dump_file}"

  if [[ "${VERIFY_SHA256}" == "true" ]]; then
    actual="$(sha256_of "${dump_file}")"
    if [[ "${actual}" != "${sha256}" ]]; then
      echo "sha256 mismatch for ${dump_file}: ${actual} != ${sha256}" >&2
      exit 3
    fi
  fi
  if [[ "$(head -c 4 "${dump_file}")" != "DZV1" ]]; then
    echo "${dump_file} lacks the Neo4j 5 dump header (DZV1); refusing to load" >&2
    exit 3
  fi
  echo "verified graph=${graph} dump=${dump_file} url=${url}"
done

if [[ "${DOWNLOAD_ONLY}" == "true" ]]; then
  echo "DOWNLOAD_ONLY=true; dumps are in ${DOWNLOAD_DIR}"
  exit 0
fi

mkdir -p "${TOOL_ROOT}"

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

summary=()
for graph in ${GRAPHS}; do
  read -r _repo _commit dump_path _sha256 bolt_port http_port <<<"$(graph_spec "${graph}")"
  dump_file="${DOWNLOAD_DIR}/${graph}/$(basename "${dump_path}")"
  run_root="${RUN_ROOT_BASE}/${graph}"
  session="pipecypher_neo4j_t2c_${graph}"
  conf_dir="${run_root}/conf"
  data_dir="${run_root}/data"
  import_dir="${run_root}/import"
  log_dir="${run_root}/logs"
  run_dir="${run_root}/run"
  mkdir -p "${conf_dir}" "${data_dir}" "${import_dir}" "${log_dir}" "${run_dir}"

  cat > "${conf_dir}/neo4j.conf" <<EOF
server.default_listen_address=127.0.0.1
server.bolt.listen_address=:${bolt_port}
server.http.listen_address=:${http_port}
dbms.security.auth_enabled=${AUTH_ENABLED}
server.directories.data=${data_dir}
server.directories.import=${import_dir}
server.directories.logs=${log_dir}
server.directories.run=${run_dir}
server.memory.heap.initial_size=${HEAP_INITIAL}
server.memory.heap.max_size=${HEAP_MAX}
server.memory.pagecache.size=${PAGECACHE}
db.tx_log.rotation.retention_policy=1 files
EOF

  # neo4j-admin loads <database>.dump from --from-path.
  load_dump_dir="${run_root}/load_dumps"
  mkdir -p "${load_dump_dir}"
  ln -sf "${dump_file}" "${load_dump_dir}/${DATABASE}.dump"

  JAVA_HOME="${JRE_HOME}" PATH="${JRE_HOME}/bin:${PATH}" NEO4J_CONF="${conf_dir}" \
    "${NEO4J_HOME}/bin/neo4j-admin" database load "${DATABASE}" \
    --from-path="${load_dump_dir}" \
    --overwrite-destination=true
  echo "loaded graph=${graph} database=${DATABASE} run_root=${run_root}"

  if [[ "${START}" == "true" ]]; then
    RUN_ROOT="${run_root}" SESSION="${session}" BOLT_PORT="${bolt_port}" HTTP_PORT="${http_port}" \
      AUTH_ENABLED="${AUTH_ENABLED}" HEAP_INITIAL="${HEAP_INITIAL}" HEAP_MAX="${HEAP_MAX}" \
      PAGECACHE="${PAGECACHE}" NEO4J_VERSION="${NEO4J_VERSION}" TOOL_ROOT="${TOOL_ROOT}" \
      bash "${SCRIPT_DIR}/start_neo4j_community.sh"
  else
    echo "start command:"
    echo "RUN_ROOT='${run_root}' SESSION='${session}' BOLT_PORT='${bolt_port}' HTTP_PORT='${http_port}' AUTH_ENABLED='${AUTH_ENABLED}' HEAP_INITIAL='${HEAP_INITIAL}' HEAP_MAX='${HEAP_MAX}' PAGECACHE='${PAGECACHE}' scripts/start_neo4j_community.sh"
  fi
  summary+=("graph=${graph} bolt=bolt://localhost:${bolt_port} http=http://localhost:${http_port} session=${session} config=configs/t2c_${graph}.yaml")
done

echo "example-graph instances:"
for line in "${summary[@]}"; do
  echo "  ${line}"
done
echo "next: python scripts/inspect_schema.py --config configs/t2c_<graph>.yaml (writes configs/schema_t2c_<graph>.json)"
