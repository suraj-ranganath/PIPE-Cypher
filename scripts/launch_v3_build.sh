#!/usr/bin/env bash
# Launch a v3 generation build: one process per (graph, seed, category) cell,
# each with its exact target, so cells never overshoot and nothing is discarded.
#
# Usage: scripts/launch_v3_build.sh PREFIX TARGET_FINBENCH TARGET_SNB "SEEDS" STAGE_CAP_USD [PARALLEL]
#   e.g. scripts/launch_v3_build.sh naacl_v3_pilot 10 10 "1" 1.0 16
#
# Env (keys come from the environment, never from files in the repo):
#   OPENROUTER_API_KEY      required
#   FINBENCH_URI / SNB_URI  bolt URIs (default bolt://localhost:7687 / :7688)
# Spend: one generation ledger per build with a stage cap; at the cap every worker
# pauses (PIPE_CYPHER_PAUSE_ON_CAP=1) until <ledger>.cap is raised.
set -euo pipefail
PREFIX=${1:?prefix}; T_FB=${2:?finbench target}; T_SNB=${3:?snb target}; SEEDS=${4:?seeds}; CAP=${5:?cap}; PAR=${6:-16}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PY=${PY:-python3}
LOGS="$ROOT/logs/$PREFIX"; mkdir -p "$LOGS" "$ROOT/artifacts/naacl_v3/ledgers"
export PIPE_CYPHER_USAGE_LEDGER="$ROOT/artifacts/naacl_v3/ledgers/${PREFIX}_generation_spend.jsonl"
export PIPE_CYPHER_MAX_COST_USD="$CAP"
export PIPE_CYPHER_PAUSE_ON_CAP=1
CATS="simple_retrieval complex_retrieval simple_aggregation complex_aggregation boolean_existence negation_difference path_temporal ranking_topk"
{
  echo "prefix=$PREFIX started=$(date -u +%FT%TZ) cap=$CAP seeds=$SEEDS targets=finbench:$T_FB snb:$T_SNB"
  echo "code_tree_sha256=$(cd "$ROOT" && find pipecypher scripts configs -type f \( -name '*.py' -o -name '*.yaml' -o -name '*.json' -o -name '*.sh' \) -print0 | sort -z | xargs -0 shasum -a 256 | shasum -a 256 | cut -d' ' -f1)"
  echo "git_head=$(cd "$ROOT" && git rev-parse HEAD) (uncommitted tree; see code_tree_sha256)"
} > "$LOGS/launch_manifest.txt"
jobs_file="$LOGS/jobs.txt"; : > "$jobs_file"
JOB_DIR="$LOGS/jobs"; rm -rf "$JOB_DIR"; mkdir -p "$JOB_DIR"
for graph in finbench snb; do
  if [ "$graph" = finbench ]; then target=$T_FB; uri=${FINBENCH_URI:-bolt://localhost:7687}; else target=$T_SNB; uri=${SNB_URI:-bolt://localhost:7688}; fi
  [ "$target" -gt 0 ] || continue
  for seed in $SEEDS; do
    idx=0
    for cat in $CATS; do
      idx=$((idx+1))
      name="${PREFIX}_${graph}_s${seed}_${cat}"
      cmd="cd '$ROOT' && PIPE_CYPHER_CALL_LABEL=${PREFIX}_${graph}_s${seed}:${cat} '$PY' scripts/run_pipeline.py --config configs/${graph}_v3.yaml --run-name $name --categories $cat --random-seed $seed --request-seed $((20261113 + seed*100 + idx)) --binding-offset $((seed*997)) --target-per-category $target --neo4j-uri $uri > '$LOGS/${graph}_s${seed}_${cat}.log' 2>&1; echo EXIT=\$? >> '$LOGS/${graph}_s${seed}_${cat}.log'"
      echo "$cmd" >> "$jobs_file"
      echo "$cmd" > "$JOB_DIR/${graph}_s${seed}_${cat}.sh"
    done
  done
done
cp "$jobs_file" "$LOGS/launch_commands.txt"
cd "$ROOT"
# One short script per job: macOS xargs -I caps the replacement length.
ls "$JOB_DIR"/*.sh | xargs -P "$PAR" -n 1 sh
echo "finished=$(date -u +%FT%TZ)" >> "$LOGS/launch_manifest.txt"
