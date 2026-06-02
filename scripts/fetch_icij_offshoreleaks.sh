#!/usr/bin/env bash
set -euo pipefail

RUN_ROOT="${RUN_ROOT:-${HOME}/pipecypher-icij-offshoreleaks}"
DOWNLOAD_DIR="${DOWNLOAD_DIR:-${RUN_ROOT}/downloads}"
SUMMARY_DIR="${SUMMARY_DIR:-${RUN_ROOT}/summary}"
CSV_URL="${CSV_URL:-https://offshoreleaks-data.icij.org/offshoreleaks/csv/full-oldb.LATEST.zip}"
DUMP_URL="${DUMP_URL:-https://offshoreleaks-data.icij.org/offshoreleaks/neo4j/icij-offshoreleaks-5.13.0.dump}"
FETCH_DUMP="${FETCH_DUMP:-true}"

mkdir -p "${DOWNLOAD_DIR}" "${SUMMARY_DIR}"

download_to() {
  local url="$1"
  local out="$2"
  if [[ ! -f "${out}" ]]; then
    curl -fL -C - "${url}" -o "${out}"
  fi
}

CSV_ZIP="${DOWNLOAD_DIR}/full-oldb.LATEST.zip"
download_to "${CSV_URL}" "${CSV_ZIP}"

if [[ "${FETCH_DUMP}" == "true" ]]; then
  download_to "${DUMP_URL}" "${DOWNLOAD_DIR}/icij-offshoreleaks-5.13.0.dump"
fi

python - "${CSV_ZIP}" "${SUMMARY_DIR}/icij_offshoreleaks_summary.json" <<'PY'
import csv
import json
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

zip_path = Path(sys.argv[1])
out_path = Path(sys.argv[2])
node_files = {
    "Entity": "nodes-entities.csv",
    "Officer": "nodes-officers.csv",
    "Intermediary": "nodes-intermediaries.csv",
    "Address": "nodes-addresses.csv",
    "Other": "nodes-others.csv",
}
summary = {
    "csv_zip": str(zip_path),
    "files": {},
    "node_counts": {},
    "headers": {},
    "relationship_counts": {},
    "relationship_direction_counts": {},
}
with zipfile.ZipFile(zip_path) as archive:
    for info in archive.infolist():
        summary["files"][info.filename] = info.file_size

    id_to_label = {}
    for label, filename in node_files.items():
        with archive.open(filename) as handle:
            reader = csv.DictReader((line.decode("utf-8", errors="replace") for line in handle))
            summary["headers"][filename] = reader.fieldnames or []
            count = 0
            for row in reader:
                id_to_label[row["node_id"]] = label
                count += 1
            summary["node_counts"][label] = count

    rel_counts = Counter()
    direction_counts = defaultdict(Counter)
    with archive.open("relationships.csv") as handle:
        reader = csv.DictReader((line.decode("utf-8", errors="replace") for line in handle))
        summary["headers"]["relationships.csv"] = reader.fieldnames or []
        for row in reader:
            rel_type = row["rel_type"]
            rel_counts[rel_type] += 1
            start = id_to_label.get(row["node_id_start"], "Unknown")
            end = id_to_label.get(row["node_id_end"], "Unknown")
            direction_counts[rel_type][f"{start}->{end}"] += 1
    summary["relationship_counts"] = dict(rel_counts.most_common())
    summary["relationship_direction_counts"] = {
        rel: dict(counts.most_common(10)) for rel, counts in direction_counts.items()
    }

out_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
print(json.dumps(summary, indent=2, sort_keys=True))
print(f"summary={out_path}")
PY
