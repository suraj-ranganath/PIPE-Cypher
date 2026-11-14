#!/usr/bin/env bash
# Generic per-cell launcher: one process per (config, seed, category) with its exact target.
# Usage: scripts/launch_cells.sh PREFIX CAP_USD PARALLEL SPEC [SPEC ...]
#   SPEC = CONFIG|NEO4J_URI|TARGET|SEEDS   e.g. "configs/t2c_northwind_v3.yaml|bolt://127.0.0.1:17702|20|1"
# Spend: one ledger per prefix; workers pause at the cap until <ledger>.cap is raised.
set -euo pipefail
PREFIX=${1:?prefix}; CAP=${2:?cap}; PAR=${3:?parallel}; shift 3
ROOT=$(cd "$(dirname "$0")/.." && pwd); PY=${PY:-python3}
LOGS="$ROOT/logs/$PREFIX"; JOB_DIR="$LOGS/jobs"; rm -rf "$JOB_DIR"; mkdir -p "$JOB_DIR" "$ROOT/artifacts/naacl_v3/ledgers"
export PIPE_CYPHER_USAGE_LEDGER="$ROOT/artifacts/naacl_v3/ledgers/${PREFIX}_spend.jsonl"
export PIPE_CYPHER_MAX_COST_USD="$CAP" PIPE_CYPHER_PAUSE_ON_CAP=1
{
  echo "prefix=$PREFIX started=$(date -u +%FT%TZ) cap=$CAP specs=$*"
  echo "code_tree_sha256=$(cd "$ROOT" && find pipecypher scripts configs -type f \( -name '*.py' -o -name '*.yaml' -o -name '*.json' -o -name '*.sh' \) -print0 | sort -z | xargs -0 shasum -a 256 | shasum -a 256 | cut -d' ' -f1)"
  echo "git_head=$(cd "$ROOT" && git rev-parse HEAD) (uncommitted tree; see code_tree_sha256)"
} > "$LOGS/launch_manifest.txt"
for spec in "$@"; do
  IFS='|' read -r cfg uri target seeds <<< "$spec"
  name=$(basename "$cfg" .yaml)
  cats=$("$PY" -c "import sys; sys.path.insert(0,'$ROOT'); from pipecypher.config import load_config; print(' '.join(load_config('$ROOT/$cfg').generation.categories))")
  for seed in $seeds; do
    idx=0
    for cat in $cats; do
      idx=$((idx+1)); cell="${name}_s${seed}_${cat}"
      echo "cd '$ROOT' && PIPE_CYPHER_CALL_LABEL=${PREFIX}_${name}_s${seed}:${cat} '$PY' scripts/run_pipeline.py --config $cfg --run-name ${PREFIX}_${cell} --categories $cat --random-seed $seed --request-seed $((20261113 + seed*100 + idx)) --binding-offset $((seed*997)) --target-per-category $target --neo4j-uri $uri > '$LOGS/$cell.log' 2>&1; echo EXIT=\$? >> '$LOGS/$cell.log'" > "$JOB_DIR/$cell.sh"
    done
  done
done
cat "$JOB_DIR"/*.sh > "$LOGS/launch_commands.txt"
cd "$ROOT"; ls "$JOB_DIR"/*.sh | xargs -P "$PAR" -n 1 sh
echo "finished=$(date -u +%FT%TZ)" >> "$LOGS/launch_manifest.txt"
