# Benchmark Refresh Experiment Protocol (E4.1)

Status: harness implemented and unit-tested offline (no Neo4j, no GPU). No live
numbers exist yet. Nothing from this protocol may enter the paper until every
scenario below has a complete (non-`--limit`) audit, the M0 control is done, and
the artifacts are recorded in the status/evidence documents.

## Claim under test

Reviewers asked us to *demonstrate* the "refreshable private benchmark" claim.
E4.1 measures, for realistic schema migrations and data drift on LDBC FinBench:

1. how many accepted benchmark items break loudly (schema-invalid), break
   silently (same query, different or empty answer), or survive unchanged;
2. how well a schema diff predicts that impact *before* executing anything;
3. how much of a refresh can be carried forward without LLM generation
   (reuse, answer refresh, rename-aware token rewrite) versus regenerated;
4. the GPU cost of incremental versus full refresh; and
5. how wrong a downstream model's accuracy is when scored against stale
   references on the migrated graph ("accuracy misestimate").

## Scenarios

Each scenario is applied to a fresh copy of FinBench (reset from the same
pristine dump), so effects are attributable to one change.

| ID | Kind | Change | Expected signal |
|---|---|---|---|
| M0 | control | none (primary vs pristine copy) | noise floor; ~100% unchanged |
| M1 | schema | rename `TRANSFER_TO` to `SENDS_FUNDS` | many `broken_schema`, all rename-rewritable |
| M2 | schema | rename `Account.isBlocked` to `Account.blocked` | many `broken_schema`, rewritable; Neo4j returns null columns silently |
| M3 | schema | relabel hash-selected 15% of `Company` as `Merchant`, add `(:Merchant)-[:SETTLES_TO]->(:Account)` | no validator errors; silent answer changes on Company patterns |
| M4 | schema | drop `GUARANTEE` | only GUARANTEE items break (not rewritable) |
| D1 | drift | delete hash-selected 10% of `TRANSFER_TO` edges | silent changes / now-empty on transfer queries |
| D2 | drift | insert 5% synthetic `TRANSFER_TO` edges after the latest timestamp | silent changes, especially negation/aggregation |

Migration definitions live in `configs/migrations/finbench/`: one `<id>.cypher`
(write statements) plus one `<id>.meta.yaml` (description, read-only pre/post
conditions, deterministic selection or generator, `expected_schema_diff`,
expected benchmark impact). Metadata keys are validated strictly; the
`.meta.yaml` files are not run configs. The run config for the copy instance is
`configs/migrations/finbench/finbench_copy.run.yaml` (strict-valid, Bolt 7697).

Determinism: subsets are chosen by a salted SHA-256 of element *properties*
(`companyId`; transfer endpoints + `orderNum` + `createTime` + `amount`), never
by internal element ids or randomness. Synthetic transfers are derived from a
salted hash of the edge ordinal. The migration ledger records a digest of the
selected/generated rows, so two copies loaded from the same import must show
identical digests.

## Safety model

`scripts/apply_graph_migration.py` is the only PIPE-Cypher script that writes:

- `--target-bolt-uri` and `--confirm-copy-database <name>` are required, and the
  confirmation must equal `--target-database` (never overridable).
- The target endpoint+database is compared with `configs/finbench_full.yaml`,
  `configs/snb_full.yaml`, and `configs/icij_offshoreleaks_full.yaml` (raw YAML,
  so `PIPE_CYPHER_NEO4J_*` env overrides cannot mask them); a match is refused
  unless `--i-know-this-is-a-copy` is passed. Loopback names and the host's own
  name normalize to `localhost`.
- Dry run is the default (no connection). `--inspect-target` connects
  read-only. Only `--apply` writes.
- With `--apply`/`--inspect-target`, `db.info()` store ids of the target and every
  reachable protected graph are compared; equal ids are refused (overridable
  only with the explicit flag).
- Preconditions run before any write, so re-applying a migration or pointing at
  an unexpected graph stops with exit code 3 before mutating anything.

The audit (`scripts/audit_benchmark_refresh.py`) is read-only on both graphs
(`READ` sessions plus the governance read-only token check), refuses identical
original/migrated configs, and refuses to start while `PIPE_CYPHER_NEO4J_URI`
or `PIPE_CYPHER_NEO4J_DATABASE` are set.

Neo4j Community has exactly one user database per DBMS, so the migrated graph
must be a **second Neo4j instance** (own run root, data dir, Bolt/HTTP ports)
loaded from the same FinBench import as the primary. Resets use
`neo4j-admin database dump/load`, which requires that copy instance to be
stopped. Always pass the copy's `NEO4J_CONF`; never run `load
--overwrite-destination` with the primary's configuration.

## Step-by-step commands (remote GPU server, repo root)

### 0. Environment and preflight

```bash
cd "${PIPE_CYPHER_REPO:-${HOME}/PIPE-Cypher}"
export PY="${HOME}/pipecypher-tools/runtime-venv/bin/python"
unset PIPE_CYPHER_NEO4J_URI PIPE_CYPHER_NEO4J_DATABASE
export NEO4J_VERSION=5.26.0
export NEO4J_HOME="${HOME}/pipecypher-tools/neo4j-community-${NEO4J_VERSION}"
export JAVA_HOME="${HOME}/pipecypher-tools/temurin17-jre"
export COPY_RUN_ROOT="${HOME}/pipecypher-neo4j-refresh"
export COPY_SESSION=pipecypher_neo4j_refresh
export COPY_BOLT=bolt://localhost:7697
export COPY_CFG=configs/migrations/finbench/finbench_copy.run.yaml
export BENCH=artifacts/benchmarks/20260604_live_full_qwen9b_reviewfix
export R=artifacts/refresh
mkdir -p "$R"
git rev-parse HEAD | tee "$R/code_revision.txt"

"$PY" -m pytest -q tests/test_refresh_audit.py   # if pytest is installed in the runtime venv
"$PY" scripts/validate_config.py configs/finbench_full.yaml "$COPY_CFG"
"$PY" scripts/apply_graph_migration.py --list
```

### 1. Start the second Neo4j instance and load the same import

```bash
RUN_ROOT="$COPY_RUN_ROOT" SESSION="$COPY_SESSION" BOLT_PORT=7697 HTTP_PORT=7484 \
HEAP_INITIAL=2G HEAP_MAX=4G PAGECACHE=2G AUTH_ENABLED=false \
scripts/start_neo4j_community.sh

wait_copy() { until "$NEO4J_HOME/bin/cypher-shell" -a "$COPY_BOLT" "RETURN 1" >/dev/null 2>&1; do sleep 5; done; }
wait_copy

# load_finbench_neo4j.sh CLEARS the database at BOLT_URI first. Triple-check it is 7697.
SNAPSHOT_DIR="${HOME}/pipecypher-runs/finbench_sf0.1/data/snapshot" \
RUN_ROOT="$COPY_RUN_ROOT" BOLT_URI="$COPY_BOLT" \
scripts/load_finbench_neo4j.sh
```

Confirm the copy matches the primary (expect 10,006 nodes and identical
per-type relationship counts, e.g. `TRANSFER_TO` 13,385, `GUARANTEE` 1,225):

```bash
for port in 7687 7697; do
  printf "MATCH (n) RETURN count(n) AS nodes;\nMATCH ()-[r]->() RETURN type(r) AS t, count(*) AS c ORDER BY t;\n" |
    "$NEO4J_HOME/bin/cypher-shell" -a "bolt://localhost:${port}" --format plain > "$R/counts_${port}.txt"
done
diff "$R/counts_7687.txt" "$R/counts_7697.txt" && echo "copy matches primary"
```

If port binding fails, check for collisions with the SNB (7688) and ICIJ
(7689) instances and pick another free Bolt/HTTP pair; update
`finbench_copy.run.yaml` and `COPY_BOLT` together.

### 2. Snapshot the pristine copy (reset point)

```bash
stop_copy() {
  tmux send-keys -t "$COPY_SESSION" C-c 2>/dev/null || true
  sleep 30
  tmux kill-session -t "$COPY_SESSION" 2>/dev/null || true
}
start_copy() {
  RUN_ROOT="$COPY_RUN_ROOT" SESSION="$COPY_SESSION" BOLT_PORT=7697 HTTP_PORT=7484 \
  HEAP_INITIAL=2G HEAP_MAX=4G PAGECACHE=2G AUTH_ENABLED=false \
  scripts/start_neo4j_community.sh
  wait_copy
}
copy_admin() { NEO4J_CONF="$COPY_RUN_ROOT/conf" "$NEO4J_HOME/bin/neo4j-admin" "$@"; }

stop_copy
mkdir -p "$COPY_RUN_ROOT/dumps/pristine"
copy_admin database dump neo4j --to-path="$COPY_RUN_ROOT/dumps/pristine"
sha256sum "$COPY_RUN_ROOT/dumps/pristine/neo4j.dump" | tee "$R/pristine_dump.sha256"
start_copy

reset_copy() {
  stop_copy
  copy_admin database load neo4j --from-path="$COPY_RUN_ROOT/dumps/pristine" --overwrite-destination=true
  start_copy
}
```

### 3. Introspect the pristine copy and the primary

```bash
mkdir -p "$R/finbench_copy" "$R/m0_identity_control"
"$PY" scripts/inspect_schema.py --config "$COPY_CFG" --output "$R/finbench_copy/schema_before.json"
"$PY" scripts/inspect_schema.py --config configs/finbench_full.yaml --output "$R/m0_identity_control/primary_schema_now.json"
"$PY" scripts/audit_benchmark_refresh.py diff \
  --before-schema "$R/m0_identity_control/primary_schema_now.json" \
  --after-schema "$R/finbench_copy/schema_before.json" \
  --output "$R/m0_identity_control/schema_diff.json"
```

The M0 diff must be empty (`summary_counts` all zero). If not, stop: the copy is
not equivalent to the primary.

### 4. M0 identity control (noise floor)

```bash
"$PY" scripts/audit_benchmark_refresh.py audit \
  --benchmark "$BENCH" --migration-id m0_identity_control --graph-profile finbench \
  --original-config configs/finbench_full.yaml --migrated-config "$COPY_CFG" \
  --original-schema "$R/finbench_copy/schema_before.json" \
  --migrated-schema "$R/finbench_copy/schema_before.json" \
  --output-dir "$R/m0_identity_control/audit"
```

Expected: about 100% `unchanged_answer`. Every non-unchanged item must be
explained (check `nondeterminism.silently_changed_with_unordered_truncated_limit`
and the per-item `nondeterminism_risk` flag: `LIMIT` without `ORDER BY` that
truncates). Report the residual as the noise floor for D1/D2.

### 5. Per-scenario loop (apply, re-introspect, verify, audit)

Use one of the complete clean downstream prediction sets as the stale-schema
predictions, e.g. `artifacts/evaluations/20260604_clean_downstream_qwen35_9b_zero_fewshot/zero_shot_predictions.jsonl`
(296 rows, 200 FinBench, no empty predictions). Check the failure rate of any
other prediction file first; some clean prediction files are entirely empty.

```bash
PRED=artifacts/evaluations/20260604_clean_downstream_qwen35_9b_zero_fewshot/zero_shot_predictions.jsonl
for MIG in m1_rename_transfer_to m2_rename_account_isblocked m3_relabel_merchant_companies \
           m4_drop_guarantee d1_delete_transfer_sample d2_insert_synthetic_transfers; do
  OUT="$R/$MIG"; mkdir -p "$OUT"
  reset_copy
  "$PY" scripts/apply_graph_migration.py --migration "$MIG" \
    --target-bolt-uri "$COPY_BOLT" --confirm-copy-database neo4j \
    --inspect-target --ledger-out "$OUT/inspect_ledger.json"
  "$PY" scripts/apply_graph_migration.py --migration "$MIG" \
    --target-bolt-uri "$COPY_BOLT" --confirm-copy-database neo4j \
    --apply --ledger-out "$OUT/migration_ledger.json"
  "$PY" scripts/inspect_schema.py --config "$COPY_CFG" --output "$OUT/schema_after.json"
  # Must exit 0: the observed schema diff contains the declared expected diff.
  "$PY" scripts/audit_benchmark_refresh.py diff \
    --before-schema "$R/finbench_copy/schema_before.json" --after-schema "$OUT/schema_after.json" \
    --migration "$MIG" --benchmark "$BENCH" --output "$OUT/schema_diff_check.json" \
    || { echo "expected schema diff mismatch for $MIG; stopping" >&2; break; }

  start=$(date +%s)
  "$PY" scripts/audit_benchmark_refresh.py audit \
    --benchmark "$BENCH" --migration "$MIG" \
    --original-config configs/finbench_full.yaml --migrated-config "$COPY_CFG" \
    --original-schema "$R/finbench_copy/schema_before.json" --migrated-schema "$OUT/schema_after.json" \
    --migration-ledger "$OUT/migration_ledger.json" --output-dir "$OUT/audit" \
    --regeneration-base-config "$COPY_CFG" --predictions "$PRED"
  end=$(date +%s); printf "audit\t%s\t%s\n" "$start" "$end" > "$OUT/audit_timing.tsv"

  # Baseline without the rename-aware rewrite (every broken item is regenerated).
  "$PY" scripts/audit_benchmark_refresh.py audit \
    --benchmark "$BENCH" --migration "$MIG" \
    --original-config configs/finbench_full.yaml --migrated-config "$COPY_CFG" \
    --original-schema "$R/finbench_copy/schema_before.json" --migrated-schema "$OUT/schema_after.json" \
    --migration-ledger "$OUT/migration_ledger.json" --output-dir "$OUT/audit_no_rewrite" \
    --no-rename-rewrite

  # Keep the migrated state so GPU stages can be rerun without re-applying.
  stop_copy
  mkdir -p "$COPY_RUN_ROOT/dumps/$MIG"
  copy_admin database dump neo4j --to-path="$COPY_RUN_ROOT/dumps/$MIG"
  start_copy
done
```

Per-scenario outputs in `$R/<MIG>/audit/`: `refresh_audit_summary.json`
(class counts and rates by category/difficulty/split/signature/template family,
Neo4j runtime outcomes of schema-broken references, static-impact precision and
recall, incremental plan, rename-rewrite outcomes, misestimate, provenance with
checksums and git revision), `refresh_audit_items.jsonl` (ids, atoms, classes,
no question text; validator and Neo4j error messages can still quote literal
values, so treat it as internal), `carried_forward_export.jsonl` (internal:
contains questions, Cypher literals, and result samples), `reusable_seen_records.jsonl`, `schema_diff.json`, and
`regeneration/` (one strict-valid config per stale category, a full-refresh
config, and `regenerate.sh` / `full_refresh.sh` that log epoch timings).

### 6. GPU stages for each scenario (copy must hold that scenario's state)

```bash
load_state() {  # $1 = migration id
  stop_copy
  copy_admin database load neo4j --from-path="$COPY_RUN_ROOT/dumps/$1" --overwrite-destination=true
  start_copy
}
export PIPE_CYPHER_LLM_BASE_URL=http://localhost:8000/v1   # local vLLM serving Qwen/Qwen3.5-9B
export N_GPU=1                                             # tensor-parallel size of that endpoint

for MIG in m1_rename_transfer_to m2_rename_account_isblocked m3_relabel_merchant_companies \
           m4_drop_guarantee d1_delete_transfer_sample d2_insert_synthetic_transfers; do
  OUT="$R/$MIG"
  load_state "$MIG"
  # Incremental refresh: only stale categories, deduplicated against carried-forward questions.
  PY="$PY" bash "$OUT/audit/regeneration/regenerate.sh" 2>&1 | tee "$OUT/regenerate.log"
  # Full refresh baseline: regenerate every category at the original per-category size.
  PY="$PY" bash "$OUT/audit/regeneration/full_refresh.sh" 2>&1 | tee "$OUT/full_refresh.log"
  # Predictions prompted with the migrated schema (second misestimate variant).
  "$PY" scripts/generate_text2cypher_predictions.py --benchmark "$BENCH" --split test \
    --schema finbench="$OUT/schema_after.json" --schema snb=configs/schema_snb.json \
    --model Qwen/Qwen3.5-9B --base-url "$PIPE_CYPHER_LLM_BASE_URL" \
    --output "$OUT/predictions_migrated_schema.jsonl"
  "$PY" scripts/audit_benchmark_refresh.py misestimate \
    --benchmark "$BENCH" --refreshed-export "$OUT/audit/carried_forward_export.jsonl" \
    --predictions "$OUT/predictions_migrated_schema.jsonl" --graph-profile finbench \
    --migrated-config "$COPY_CFG" --audit-items "$OUT/audit/refresh_audit_items.jsonl" \
    --output-dir "$OUT/misestimate_migrated_schema"
done
```

Use the same prediction flags (prompt profile, few-shot settings) as the clean
downstream run being compared. If `regeneration_targets` is empty (for example
M4 when no item uses `GUARANTEE`), `regenerate.sh` is a no-op and incremental
GPU cost is zero; still run the full-refresh baseline. If compute is tight, run
the full-refresh baseline at least for M1 and D2 and state which scenarios
reuse that measurement.

GPU-hours = wall-clock hours from the `*_timing.tsv` files x `N_GPU`. Also
report hardware-independent cost from the run ledgers:

```bash
"$PY" scripts/summarize_runtime_accounting.py \
  --records artifacts/runs/*_refresh_${MIG}_*/records.jsonl \
  --output-json "$R/$MIG/incremental_runtime.json"
"$PY" scripts/summarize_runtime_accounting.py \
  --records artifacts/runs/*_refresh_full_${MIG}/records.jsonl \
  --output-json "$R/$MIG/full_runtime.json"
```

### 7. Assemble the refreshed benchmark package

```bash
"$PY" scripts/export_benchmark.py --records artifacts/runs/*_refresh_${MIG}_* \
  --output-dir "$R/$MIG/regenerated_export" --split-seed "refresh-${MIG}"
"$PY" scripts/audit_benchmark_refresh.py assemble \
  --original-benchmark "$BENCH" --audit-dir "$R/$MIG/audit" \
  --regenerated-export "$R/$MIG/regenerated_export" \
  --output-dir "artifacts/benchmarks/refresh_${MIG}"
```

Carried-forward rows keep their original split; regenerated rows fill the
per-category, per-split deficits (held-out splits first) in id order; SNB rows
pass through unchanged. The command fails if any deficit stays unfilled. The
refreshed package has new split hashes, so downstream and few-shot results must
be rerun on it (AGENTS.md) before any refreshed-benchmark accuracy is reported.
Rename-rewritten rows carry `refresh.judge_recheck_required: true`.

### 8. Paper table

Write `$R/refresh_timings.json`:

```json
{"m1_rename_transfer_to": {"full_refresh_gpu_hours": 0.0, "incremental_refresh_gpu_hours": 0.0, "audit_wall_minutes": 0.0}}
```

(one entry per scenario, computed from the timing TSVs; leave a key out rather
than guessing), then:

```bash
"$PY" scripts/audit_benchmark_refresh.py table \
  --summaries "$R"/m0_identity_control/audit/refresh_audit_summary.json \
              "$R"/{m1,m2,m3,m4,d1,d2}_*/audit/refresh_audit_summary.json \
  --timings "$R/refresh_timings.json" \
  --output-md "$R/refresh_table.md" --output-csv "$R/refresh_table.csv"
```

`table` refuses partial (`--limit`) audits.

## What the paper gets

Main paper (one compact table): per scenario, N items, % broken schema, %
execution error, % now empty, % silently changed, % unchanged, % carried
forward, and full vs incremental refresh GPU-hours (M0 row = noise floor).
Takeaway sentence candidates (only once numbers exist): "Neo4j silently returned
empty or different rows for X% of schema-broken references; static re-validation
caught all of them" and "incremental refresh regenerated Y% of items at Z% of
full-refresh GPU cost".

Appendix: per-category and per-difficulty breakdowns, Neo4j runtime outcomes of
`broken_schema` items, static-impact precision/recall (schema-diff-only planning
vs execution-verified outcome; drift that only changes node counts or property
values is invisible to the static plan by construction), rename-rewrite versus
no-rewrite regeneration load, top affected template signatures and stale schema
atoms, and the accuracy misestimate for (a) stale-schema predictions and (b)
migrated-schema predictions, with paired discordant counts and
`stale_correct_on_empty_gold` (empty stale gold matching an empty prediction).

## Readiness checklist before promotion

- All seven scenarios (M0 to D2) have complete audits; none used `--limit`.
- Every `schema_diff_check.json` has no `expected_diff_problems`.
- Migration ledgers show `status: applied`, passing postconditions, and selection
  or generation digests; rerunning a scenario reproduces the same digest.
- M0 non-unchanged items are explained by nondeterminism flags.
- Code revision, model id, endpoint, graph backend, dump checksums, and all
  output checksums are recorded in the run status document and claim/evidence map.
- Rename-rewritten items are re-judged or reported as a separate, unjudged slice.

## Known limitations and follow-ups

- FinBench seed templates and deterministic fallback Cypher in
  `pipecypher/graph_profiles.py` hard-code `TRANSFER_TO` and `isBlocked`. On the
  M1/M2 copies the validator rejects them, so regeneration relies on
  schema-derived and LLM templates and wastes some attempts; report yield.
- `CONTEXTUAL_RETURN_PROPERTIES` in `pipecypher/validator.py` hard-codes
  `Account.accountId -> (accountType, isBlocked)`. After M2, new Account queries
  get `missing_context_column` warnings (warning-level only), and the evaluation
  context-column policy will not recognize `blocked`. A schema-derived or
  config-driven context policy would remove this.
- `SchemaSummary` carries relationship-pattern counts but no node-label counts,
  so pure node insertions/deletions are visible only to the execution audit.
- `db.schema.relTypeProperties()` can keep listing a relationship type whose
  edges were all deleted; the diff and audit prune these ghost entries (logged in
  `pruned_ghost_entries`).
- No standalone re-judge CLI exists for carried-forward rewritten items.
