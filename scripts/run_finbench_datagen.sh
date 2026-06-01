#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATAGEN_DIR="${DATAGEN_DIR:-${PROJECT_ROOT}/external/ldbc_finbench_datagen}"
SCALE_FACTOR="${SCALE_FACTOR:-0.1}"
RUN_ROOT="${RUN_ROOT:-${HOME}/pipecypher-runs/finbench_sf${SCALE_FACTOR}}"
DATA_ROOT="${DATA_ROOT:-${RUN_ROOT}/data}"
TOOL_ROOT="${TOOL_ROOT:-${HOME}/pipecypher-tools}"
MAVEN_VERSION="${MAVEN_VERSION:-3.9.9}"
SPARK_VERSION="${SPARK_VERSION:-3.2.4}"
SPARK_HADOOP_PROFILE="${SPARK_HADOOP_PROFILE:-hadoop3.2}"
JDK8_URL="${JDK8_URL:-https://api.adoptium.net/v3/binary/latest/8/ga/linux/x64/jdk/hotspot/normal/eclipse}"
MAVEN_URL="${MAVEN_URL:-https://archive.apache.org/dist/maven/maven-3/${MAVEN_VERSION}/binaries/apache-maven-${MAVEN_VERSION}-bin.tar.gz}"
SPARK_URL="${SPARK_URL:-https://archive.apache.org/dist/spark/spark-${SPARK_VERSION}/spark-${SPARK_VERSION}-bin-${SPARK_HADOOP_PROFILE}.tgz}"
SPARK_DRIVER_MEMORY="${SPARK_DRIVER_MEMORY:-32g}"
SPARK_OFFHEAP_SIZE="${SPARK_OFFHEAP_SIZE:-8g}"
SPARK_CORES="${SPARK_CORES:-16}"
SPARK_PARALLELISM="${SPARK_PARALLELISM:-64}"
NUM_PARTITIONS="${NUM_PARTITIONS:-64}"
PYTHON_BIN="${PYTHON_BIN:-}"
CSV_BASE_URL="${CSV_BASE_URL:-file://${DATA_ROOT}/snapshot}"

if [[ ! -d "${DATAGEN_DIR}" ]]; then
  echo "Missing FinBench datagen source at ${DATAGEN_DIR}" >&2
  echo "Run: GIT_DEPTH=1 scripts/fetch_ldbc_sources.sh external" >&2
  exit 1
fi

mkdir -p "${RUN_ROOT}/logs" "${TOOL_ROOT}"

download_and_extract() {
  local url="$1"
  local archive="$2"
  local target_dir="$3"
  if [[ -d "${target_dir}" ]]; then
    return
  fi
  mkdir -p "$(dirname "${archive}")"
  if [[ ! -f "${archive}" ]]; then
    curl -fL -C - "${url}" -o "${archive}"
  fi
  tar -xzf "${archive}" -C "$(dirname "${target_dir}")"
}

JDK8_HOME="${TOOL_ROOT}/temurin8-jdk"
if [[ ! -x "${JDK8_HOME}/bin/javac" ]]; then
  rm -rf "${JDK8_HOME}"
  mkdir -p "${JDK8_HOME}"
  JDK8_ARCHIVE="${TOOL_ROOT}/temurin8-jdk.tar.gz"
  if [[ ! -f "${JDK8_ARCHIVE}" ]]; then
    curl -fL -C - "${JDK8_URL}" -o "${JDK8_ARCHIVE}"
  fi
  tar -xzf "${JDK8_ARCHIVE}" --strip-components=1 -C "${JDK8_HOME}"
fi

MAVEN_HOME="${TOOL_ROOT}/apache-maven-${MAVEN_VERSION}"
download_and_extract \
  "${MAVEN_URL}" \
  "${TOOL_ROOT}/apache-maven-${MAVEN_VERSION}-bin.tar.gz" \
  "${MAVEN_HOME}"

SPARK_HOME="${TOOL_ROOT}/spark-${SPARK_VERSION}-bin-${SPARK_HADOOP_PROFILE}"
download_and_extract \
  "${SPARK_URL}" \
  "${TOOL_ROOT}/spark-${SPARK_VERSION}-bin-${SPARK_HADOOP_PROFILE}.tgz" \
  "${SPARK_HOME}"

export JAVA_HOME="${JDK8_HOME}"
export PATH="${JAVA_HOME}/bin:${MAVEN_HOME}/bin:${SPARK_HOME}/bin:${PATH}"

pushd "${DATAGEN_DIR}" >/dev/null
mvn -q -DskipTests clean package 2>&1 | tee "${RUN_ROOT}/logs/maven_package.log"
JAR="${DATAGEN_DIR}/target/ldbc_finbench_datagen-0.2.0-SNAPSHOT-jar-with-dependencies.jar"
if [[ ! -f "${JAR}" ]]; then
  echo "Expected datagen jar not found: ${JAR}" >&2
  exit 1
fi

python3 scripts/run.py \
  --jar "${JAR}" \
  --cores "${SPARK_CORES}" \
  --memory "${SPARK_DRIVER_MEMORY}" \
  --parallelism "${SPARK_PARALLELISM}" \
  --conf "spark.memory.offHeap.size=${SPARK_OFFHEAP_SIZE}" "spark.sql.shuffle.partitions=${SPARK_PARALLELISM}" \
  -- \
  --scale-factor "${SCALE_FACTOR}" \
  --output-dir "${DATA_ROOT}" \
  --num-partitions "${NUM_PARTITIONS}" \
  --format csv \
  2>&1 | tee "${RUN_ROOT}/logs/datagen_sf${SCALE_FACTOR}.log"
popd >/dev/null

if [[ ! -d "${DATA_ROOT}/raw" ]]; then
  echo "FinBench datagen did not produce ${DATA_ROOT}/raw; see ${RUN_ROOT}/logs/datagen_sf${SCALE_FACTOR}.log" >&2
  exit 1
fi

if [[ -z "${PYTHON_BIN}" ]]; then
  if [[ -x "${HOME}/miniforge3/envs/pipe-rdf-arr/bin/python" ]]; then
    PYTHON_BIN="${HOME}/miniforge3/envs/pipe-rdf-arr/bin/python"
  else
    PYTHON_BIN="$(command -v python3)"
  fi
fi

TRANSFORM_VENV="${TOOL_ROOT}/finbench-transform-venv"
if [[ ! -x "${TRANSFORM_VENV}/bin/python" ]]; then
  "${PYTHON_BIN}" -m venv "${TRANSFORM_VENV}"
  "${TRANSFORM_VENV}/bin/python" -m pip install --upgrade pip
  "${TRANSFORM_VENV}/bin/python" -m pip install duckdb==0.7.1 pytz
fi

SHIM_ROOT="${TOOL_ROOT}/python-shims"
mkdir -p "${SHIM_ROOT}/backports"
printf "" > "${SHIM_ROOT}/backports/__init__.py"
printf "from zoneinfo import ZoneInfo\n" > "${SHIM_ROOT}/backports/zoneinfo.py"

pushd "${DATAGEN_DIR}/transformation" >/dev/null
PYTHONPATH="${SHIM_ROOT}:${PYTHONPATH:-}" "${TRANSFORM_VENV}/bin/python" convert_data.py \
  --raw_format csv \
  --raw_dir "${DATA_ROOT}" \
  --output_dir "${DATA_ROOT}" \
  2>&1 | tee "${RUN_ROOT}/logs/transform_sf${SCALE_FACTOR}.log"
popd >/dev/null

python3 "${PROJECT_ROOT}/scripts/generate_finbench_import_cypher.py" \
  --csv-base-url "${CSV_BASE_URL}" \
  --output "${DATA_ROOT}/finbench_load.cypher"

cat > "${RUN_ROOT}/manifest.txt" <<EOF
scale_factor=${SCALE_FACTOR}
data_root=${DATA_ROOT}
snapshot_dir=${DATA_ROOT}/snapshot
import_cypher=${DATA_ROOT}/finbench_load.cypher
csv_base_url=${CSV_BASE_URL}
maven_home=${MAVEN_HOME}
spark_home=${SPARK_HOME}
EOF

echo "FinBench snapshot ready: ${DATA_ROOT}/snapshot"
echo "Import Cypher: ${DATA_ROOT}/finbench_load.cypher"
echo "Manifest: ${RUN_ROOT}/manifest.txt"
