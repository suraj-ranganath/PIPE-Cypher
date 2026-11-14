# External Anchor Protocol: Text2Cypher-2024 sanity anchor (E3.4) and ranking agreement (E3.5)

Status (2026-11-11): **preparation only.** The dataset, dumps, converter, configs,
and commands below are verified offline. No graph has been loaded, no model has
been run, and nothing here is paper evidence. Promote results only after the
runs complete and pass the AGENTS.md readiness rules (complete cells, logs,
model IDs, code revision, failure analysis).

Reviewer question (C4 in `eacl_revision_plan.md`): *Is PIPE-Cypher hard, or is
the evaluation setup broken? Is a generated benchmark useful?*

- **E3.4 sanity anchor.** Score the same local downstream checkpoints, with the
  same prompt and the same evaluator, on curated Text2Cypher-2024 test rows whose
  databases load locally. Reasonable anchor scores plus low PIPE-Cypher scores
  indicate a transfer gap, not a broken harness. The oracle self-check (step 5)
  tests the harness directly.
- **E3.5 ranking agreement.** Onboard PIPE-Cypher onto the same public graphs,
  generate a benchmark for each, run the same models, and compute Kendall tau-b
  between the model ranking on the PIPE-generated benchmark and the ranking on
  the curated Text2Cypher-2024 rows for that graph.

## 1. Dataset facts (verified 2026-11-11)

| Item | Value |
| --- | --- |
| Hub id | `neo4j/text2cypher-2024v1`, cited as `text2cypher2024dataset` |
| Pinned revision | `d9f15541ab2f99a0f54797a0109b50663554f512` (repo lastModified 2025-08-06) |
| License (card) | apache-2.0 |
| Files | `data/train-00000-of-00001.parquet` (sha256 `12218000…c229bce`), `data/test-00000-of-00001.parquet` (sha256 `948ae94e…d8eb502f`). Full hashes are in `pipecypher/external_benchmarks.py:T2C2024_SHA256`. |
| Splits | train 39,554; test 4,833 (44,387 total) |
| Fields | `question`, `schema` (LangChain-style schema text), `cypher`, `data_source`, `instance_id` (e.g. `instance_id_44523`), `database_reference_alias` |
| Rows with a database alias | train 22,093; test 2,471. The companion paper reports the same counts. |

Sources: dataset card <https://huggingface.co/datasets/neo4j/text2cypher-2024v1>;
Hub API <https://huggingface.co/api/datasets/neo4j/text2cypher-2024v1>;
datasets-server <https://datasets-server.huggingface.co/info?dataset=neo4j/text2cypher-2024v1>;
companion paper: Ozsoy et al., "Text2Cypher: Bridging Natural Language and Graph
Databases", GenAIK 2025, <https://aclanthology.org/2025.genaik-1.11/> (already in
`paper_arxiv/references.bib` as `text2cypher2025`).

**What the sources claim about quality, verbatim in substance:**

- Dataset card: the dataset "brings together instances from publicly available
  datasets, cleaning and organizing them for smoother use". It notes the alias
  typo `neo4jlabs_demo_db_eoflix` (should be `neoflix`). The card says nothing
  about human verification or execution checks.
- Companion paper, Sec. 3.2: two cleaning steps. (1) "Manual checks and
  updates": removing unwanted characters such as back-ticks, removing irrelevant
  questions ("Lorem ipsum"), and de-duplicating on (`question`, `cypher`) pairs.
  (2) "Syntax validation": each query is run with `EXPLAIN` in a local Neo4j
  database, and queries with syntax errors are removed. Neither step checks that
  a query answers its question or returns rows.
- Companion paper, Sec. 3.3: test-specific source files went to test, train files
  to train, and the rest were split 90:10. Its limitations section says the same
  question can appear in train and test with different Cypher.
- Companion paper, Sec. 4.2: execution-based evaluation runs generated and
  reference queries "on the target databases", stringifies the outputs sorted
  lexicographically, and applies text metrics (Google-BLEU, Exact Match). The
  numbers are not comparable with PIPE-Cypher's set-based execution accuracy.

**Per-database row counts (test split; train in parentheses).** 17 aliases,
plus `None` for 2,362 test rows that cannot be executed.

| Alias (`neo4jlabs_demo_db_…`) | Test | Train | Public dump | Used |
| --- | ---: | ---: | --- | --- |
| companies | 275 | (2,422) | none (Crunchbase demo DB, no graph-examples repo) | no |
| eoflix (= neoflix) | 261 | (2,512) | none in neo4j-graph-examples | no |
| **recommendations** | **253** | (2,130) | `recommendations-50.dump` | **yes** |
| movies | 203 | (1,949) | `movies-50.dump` | alternate |
| **northwind** | **197** | (1,669) | `northwind-50.dump` | **yes** |
| twitch | 185 | (1,604) | `twitch-50.dump`, a 472 MB Git-LFS object, not inspected | no |
| grandstack | 182 | (1,492) | none | no |
| gameofthrones | 148 | (1,296) | none | no |
| twitter | 146 | (1,284) | `twitter-v2-50.dump` lacks AMPLIFIES / INTERACTS_WITH / RT_MENTIONS / SIMILAR_TO (about 14% of test queries) | no |
| **fincen** | **146** | (1,347) | `fincen-50.dump` | **yes** |
| buzzoverflow | 120 | (1,106) | none | no |
| offshoreleaks | 115 | (921) | `icij-offshoreleaks-50.dump`, a 340 MB Git-LFS object; its relation to the repo's ICIJ 5.13 dump is unverified | no |
| network | 109 | (1,094) | `network-management-50.dump` | alternate |
| stackoverflow2 | 91 | (867) | none; the `stackoverflow` repo dump has a different schema (Post/ACCEPTED/…) | no |
| bluesky | 39 | (388) | none | no |
| openstreetmap | 1 | (10) | not checked (1 row) | no |
| stackoverflow | 0 | (2) | n/a | no |

Test rows for the three chosen graphs come from: synthetic GPT-4o 185, GPT-4-turbo
182, Gemini 164, Claude Opus 62, crowdsourced 3. In other words they are almost
entirely LLM-generated.

## 2. Chosen graphs and verification

Recommendation: **recommendations (253 test rows), northwind (197), fincen
(146)**, 596 test rows in total. Together they cover retail/media, ERP-style
orders, and financial compliance. These are the three graphs with the most test
rows whose public dump loads on Neo4j Community 5.x and whose tokens cover the
test queries. Alternates: network-management (109 rows, all query tokens
present) and movies (203 rows, but 27 queries use a missing `votes` property and
the graph is too small for a balanced target-per-category PIPE run). The plan's
example of "stackoverflow" does not work: the T2C alias is `stackoverflow2`, and
its schema does not match the public `stackoverflow` dump.

| Graph | Dump (commit-pinned) | Bytes | sha256 | Store format | Bolt / HTTP |
| --- | --- | ---: | --- | --- | --- |
| recommendations | `neo4j-graph-examples/recommendations@f5a3f87b/data/recommendations-50.dump` | 9,552,166 | `c22134f5…34673453734` | record, standard | 7701 / 7501 |
| northwind | `neo4j-graph-examples/northwind@56ee0507/data/northwind-50.dump` | 160,712 | `3aef3fdf…7c1f66b9f` | record, standard | 7702 / 7502 |
| fincen | `neo4j-graph-examples/fincen@41c8ef89/data/fincen-50.dump` | 1,407,783 | `e0e8f0a5…e88119016b8` | record, standard | 7703 / 7503 |

Full URLs and hashes are in `pipecypher/external_benchmarks.py:EXAMPLE_GRAPHS` and
`scripts/fetch_neo4j_example_graphs.sh` (a test keeps the two in sync).

How each dump was verified, without running Neo4j:

1. The commit-pinned raw URL returns HTTP 200, and the byte size matches the
   GitHub contents API.
2. The sha256 of the downloaded file is recorded, and the script re-checks it.
3. The header is `DZV1` followed by a zstd frame, which is the Neo4j 5 dump
   format. The 4.3 dumps start directly with zstd.
4. The archive's `neostore` entry says `record`/`standard` (recommendations-50,
   northwind-50, fincen-50) or `record`/`aligned` (network, movies). Both are
   Community formats; none is `block`, which is Enterprise-only. Index
   directories are `range-1.0` and `token-lookup-1.0` (Neo4j 5).
5. Label, relationship-type, and property-key token stores were read from the
   archives as data. Every label, relationship type, and property key in the
   dataset's schema text for these three graphs exists in the dump. Matching the
   tokens of the 596 test queries against the dump gives recommendations 253/253
   and northwind 197/197 (the 3 regex misses were function names). For fincen,
   a few queries use `originator_country`, `originator_lat`, or `originator_lng`,
   which do not exist in the dump. The gold audit removes them.

Not used: `northwind-2026-05.dump` targets Neo4j 2026.05.
`recommendations-5.26.dump` was written by Neo4j 5.26.8; we avoid loading it
into 5.26.0. Use it only with `NEO4J_VERSION>=5.26.8`.

**Not verified (do on ds-serv6):** `neo4j-admin database load` and server start
on Neo4j Community 5.26.0. The -50 dumps come from early 5.x, and Neo4j 5 should
upgrade them automatically within the major version. Also unverified: live schema
introspection, and whether the demo-server data that the T2C questions were
written against matches these dumps value-for-value. The gold audit (step 4)
measures that last point.

## 3. Converted package (offline run on the pinned parquet)

`scripts/fetch_text2cypher2024.py convert --databases recommended` yields:

- test 596 (recommendations 253, northwind 197, fincen 146); train 4,630;
  dev 515. Dev is a hash-ordered 10% of upstream train per graph. Upstream test
  is kept unchanged as `test`.
- Read-only gate (`validate_cypher(...).read_only`): 0 test rows dropped. Across
  all databases, 5 train rows are dropped: one real `MATCH (n) DETACH DELETE n`,
  and 4 rows whose Stack Overflow title literal contains "Create". Those 4 are
  logged with `suspected_false_positive: true`, and the gate is not weakened.
  Every drop goes to `dropped.jsonl`.
- `id = t2c_<sha256(dataset, instance_id, alias, question, cypher)[:16]>`.
  `category = "external"`. `derived_category` is a structural heuristic, not a
  gold label: ranking_topk 311, simple_retrieval 130, complex_aggregation 87,
  complex_retrieval 41, simple_aggregation 22, negation_difference 5, and no
  boolean_existence or path_temporal rows. `difficulty = "unknown"`;
  `structural_difficulty` holds PIPE's feature-based value.
- Row flags and slices (`slices/*.jsonl`):

| Graph | Test | Question also in upstream train | LIMIT without ORDER BY | ORDER BY + LIMIT |
| --- | ---: | ---: | ---: | ---: |
| recommendations | 253 | 185 | 25 | 148 |
| northwind | 197 | 107 | 18 | 85 |
| fincen | 146 | 64 | 11 | 79 |
| **total** | 596 | 356 | 54 | 312 |

  Slices: `test_unseen_question` (240), `test_no_unordered_limit` (542),
  `test_unseen_question_no_unordered_limit` (227), and `test_t2c_<graph>`. Of the
  356 overlapping test rows, only 1 has whitespace-identical Cypher in train (5 if
  case is ignored).
- `configs/schema_t2c_<graph>_derived.json` is parsed from the most frequent
  `schema` string per graph and regenerates byte-for-byte from the pinned
  parquet. Example and "Available options" values are dropped because they are
  truncated upstream. These files are for offline checks and the schema-drift
  comparison only. Runs use the live `configs/schema_t2c_<graph>.json`.

## 4. Commands

Run in `tmux` on ds-serv6 from the repo root, and log `git rev-parse HEAD`,
GPU ids, model ids, and output paths in a status file
(`experiments/snapshots/<date>_external_anchor/status.md`).

```bash
REV=d9f1554
PKG_RAW=artifacts/external_benchmarks/t2c2024_${REV}_recommended_raw
PKG=artifacts/external_benchmarks/t2c2024_${REV}_recommended_audited
GRAPHS_T2C="recommendations northwind fincen"
SCHEMA_ARGS=""; CONFIG_ARGS=""
for g in ${GRAPHS_T2C}; do
  SCHEMA_ARGS+=" --schema t2c_${g}=configs/schema_t2c_${g}.json"
  CONFIG_ARGS+=" --config t2c_${g}=configs/t2c_${g}.yaml"
done
```

**Step 0, preflight.**
`python scripts/validate_config.py configs/t2c_recommendations.yaml configs/t2c_northwind.yaml configs/t2c_fincen.yaml`
must pass. Re-run it with `--check-paths` after step 2.

**Step 1, load graphs** (Neo4j Community 5.26.0; one instance and one database
per graph; refuses if the tmux session exists):

```bash
bash scripts/fetch_neo4j_example_graphs.sh ~/pipecypher-neo4j-example-graphs/downloads
# prints bolt://localhost:7701 (recommendations), :7702 (northwind), :7703 (fincen)
```

**Step 2, live schemas and drift check:**

```bash
for g in ${GRAPHS_T2C}; do
  python scripts/inspect_schema.py --config configs/t2c_${g}.yaml        # writes configs/schema_t2c_${g}.json
  python scripts/fetch_text2cypher2024.py schema-drift \
    --derived configs/schema_t2c_${g}_derived.json --live configs/schema_t2c_${g}.json
done
```

Record any missing labels, relationship types, properties, or patterns in the
status file.

**Step 3, convert** (downloads the pinned parquet into `external/`, which is
gitignored, and verifies sha256; needs `pyarrow`):

```bash
python scripts/fetch_text2cypher2024.py convert \
  --download-dir external/text2cypher-2024v1 --databases recommended --output-dir ${PKG_RAW}
```

**Step 4, gold audit.** Execute every test reference as written, read-only.
Keep only references that run and return rows, matching PIPE's
`require_non_empty`. Every drop is logged with its reason:

```bash
python scripts/fetch_text2cypher2024.py audit-gold --benchmark ${PKG_RAW} ${CONFIG_ARGS} \
  --splits test --output-dir ${PKG}
```

Report both counts (596, and the number kept after the audit) and the per-graph
drop reasons.

**Step 5, harness self-check (oracle).** Must pass before any model run:

```bash
python scripts/fetch_text2cypher2024.py oracle --benchmark ${PKG} --split test \
  --output ${PKG}/oracle_predictions.jsonl
python scripts/evaluate_benchmark_predictions.py --benchmark ${PKG} --split test \
  --predictions ${PKG}/oracle_predictions.jsonl ${CONFIG_ARGS} \
  --output ${PKG}/oracle_evaluation.jsonl --summary-output ${PKG}/oracle_summary.json \
  --disable-text-metrics
```

Expect `execution_accuracy = 1.0` on every row. A row below 1.0 is a harness
defect, not a model result. See 6.1: with the current evaluator, references that
fail PIPE governance are never executed. Do not run step 6 until the oracle
reaches 1.0, or until the failing ids are excluded and reported as
`harness_gated_reference`.

**Step 6, E3.4 downstream runs.** Use the E3.1 model list
(`configs/downstream_models_naacl2027.yaml`) with the same prompt conditions as
the PIPE runs (E3.2a standardized prompt; E3.2b model-native format where
recorded). Zero-shot is the headline. If `scripts/run_downstream_suite.py` exists,
point it at `${PKG}` with the `t2c_*` schema and config mappings. Otherwise, per
model:

```bash
OUT=artifacts/evaluations/<date>_t2c2024_anchor/${SLUG}
python scripts/generate_text2cypher_predictions.py --benchmark ${PKG} --split test ${SCHEMA_ARGS} \
  --output ${OUT}/zero_shot_predictions.jsonl --base-url ${BASE_URL} --model ${MODEL} \
  --few-shot-k 0 --system-message-mode ${SYSTEM_MESSAGE_MODE:-separate}
python scripts/evaluate_benchmark_predictions.py --benchmark ${PKG} --split test \
  --predictions ${OUT}/zero_shot_predictions.jsonl ${CONFIG_ARGS} \
  --output ${OUT}/zero_shot_evaluation.jsonl --summary-output ${OUT}/zero_shot_summary.json \
  --disable-text-metrics
# Slices are scored post hoc from the full-test rows (no model re-run):
for s in test_unseen_question test_no_unordered_limit test_t2c_recommendations test_t2c_northwind test_t2c_fincen; do
  python scripts/fetch_text2cypher2024.py subset --rows ${OUT}/zero_shot_evaluation.jsonl \
    --benchmark ${PKG}/slices/${s}.jsonl --output ${OUT}/zero_shot_evaluation__${s}.jsonl
done
```

Report per model: projected EX (headline), strict EX, answer F1, parse/schema
validity, and request-failure rate, which must be 0 and is enforced at 1%. Show
these next to the same model's PIPE v2 test scores. Use
`analyze_downstream_statistics.py models --exclude-invalid` for clustered CIs on
each benchmark and `paired` only within a benchmark. If few-shot is run at all,
draw demonstrations from `${PKG}/train.jsonl` with
`--few-shot-exclude-signature-match` and report only on `test_unseen_question`.

**Step 7, E3.5 PIPE generation per graph** (Qwen3.5-9B; v2 keys as in
`configs/finbench_v2.yaml`; target 50 per category, 8 categories, seed
20261111). Raise recommendations to target 100 if yield allows.

```bash
for g in ${GRAPHS_T2C}; do
  python scripts/run_pipeline.py --config configs/t2c_${g}.yaml \
    --run-name t2c_${g}_v2_t50_s20261111 --random-seed 20261111
  python scripts/export_benchmark.py --records artifacts/runs/<run_id_for_${g}> \
    --output-dir artifacts/benchmarks/<date>_t2c_${g}_v2_t50
  python scripts/summarize_enterprise_onboarding_run.py artifacts/runs/<run_id_for_${g}> \
    --target-per-category 50 --graph-profile t2c_${g}
done
```

**Step 8, E3.5 downstream on the PIPE benchmarks.** Same models and prompt as
step 6. Use `--split all`, because zero-shot models never train on these items:

```bash
python scripts/generate_text2cypher_predictions.py --benchmark artifacts/benchmarks/<date>_t2c_${g}_v2_t50 \
  --split all --schema t2c_${g}=configs/schema_t2c_${g}.json --output ${OUT_PIPE}/${g}/${SLUG}/zero_shot_predictions.jsonl \
  --base-url ${BASE_URL} --model ${MODEL} --few-shot-k 0
python scripts/evaluate_benchmark_predictions.py --benchmark artifacts/benchmarks/<date>_t2c_${g}_v2_t50 --split all \
  --predictions ${OUT_PIPE}/${g}/${SLUG}/zero_shot_predictions.jsonl --config t2c_${g}=configs/t2c_${g}.yaml \
  --output ${OUT_PIPE}/${g}/${SLUG}/zero_shot_evaluation.jsonl --disable-text-metrics
```

**Step 9, rank agreement** per graph, then pooled over the three graphs. Use the
E3.4 per-graph subset files as side B:

```bash
python scripts/analyze_downstream_statistics.py rank-agreement \
  --a qwen35_9b=${OUT_PIPE}/${g}/qwen35_9b/zero_shot_evaluation.jsonl --a <slug>=… \
  --b qwen35_9b=<E34_OUT>/qwen35_9b/zero_shot_evaluation__test_t2c_${g}.jsonl --b <slug>=… \
  --name-a pipe_t2c_${g} --name-b t2c2024_${g} \
  --benchmark-a artifacts/benchmarks/<date>_t2c_${g}_v2_t50/all.jsonl \
  --benchmark-b ${PKG}/slices/test_t2c_${g}.jsonl \
  --metric projected_execution_accuracy --metric execution_accuracy --metric answer_f1 \
  --output-dir artifacts/analysis/<date>_e35_rank_agreement/${g}
```

The tool needs at least 3 models and warns at 5 or fewer. Use the full E3.1 set
(10 or more). Report tau-b with its bootstrap interval and the permutation p.
Report it both with and without Qwen3.5-9B, because it generated and judged the
PIPE side (see E2.4). Also report tau on `test_unseen_question`, since
T2C-tuned checkpoints have seen 60% of the anchor questions.

## 5. Caveats to state in the paper

1. **The curated side is not human-verified gold.** For these graphs it is about
   99% LLM-synthesized. Upstream checks were manual surface fixes plus `EXPLAIN`
   syntax validation, which does not establish semantic correctness. The
   questions were written against `demo.neo4jlabs.com`, not these dumps. Call it
   "curated public reference", not "gold". The gold audit makes data mismatch
   visible but cannot detect a reference that runs and returns the wrong answer.
2. **Train/test question overlap.** 356 of 596 anchor questions also appear in
   upstream train, almost always paired with different Cypher (1 whitespace-identical
   pair; 5 if case is ignored). The companion paper
   acknowledges this. Checkpoints fine-tuned on Text2Cypher-2024 (Neo4j's own
   fine-tunes, and possibly community ones) are optimistic on the anchor. Report
   `test_unseen_question` for every model.
3. **Unstable references.** 54 references use LIMIT without ORDER BY, so their
   answers depend on storage order. 312 use ORDER BY + LIMIT, which can still
   cut through ties. Report `test_no_unordered_limit` as a robustness slice.
4. **Strict EX is alias-sensitive.** Multi-column rows are compared with their
   column names, and T2C references use arbitrary aliases. Headline projected
   EX, and report strict EX next to it.
5. **Category mix differs.** By the structural heuristic, the anchor is 52%
   ranking/top-k with no boolean or path items, while PIPE is balanced over 8
   categories. Compare overall rankings, and per category only where both sides
   have at least 30 items.
6. **Not comparable with the companion paper's numbers.** It reports
   Google-BLEU and stringified exact match. We report set-based execution
   accuracy from our own harness.
7. **Licensing.** The dataset is apache-2.0. The three graph-example repos had no
   license file detected by the GitHub API. Download for research use only, do
   not redistribute the dumps, and cite the repos.

## 6. Changes needed outside this protocol's files (not made here)

1. **`pipecypher/evaluation.py:evaluate_prediction` blocks E3.4.** It runs the
   gold query only `if gold_validation.ok`, that is, only if the reference passes
   full PIPE governance against the live schema. Against the derived schemas,
   26 of 596 anchor references fail governance: wrong_direction 13,
   unknown_property 8, undirected_relationship 5, missing_relationship_type 1.
   Every model then scores 0 on those rows. Wrong-direction and unknown-property
   references mostly fail or return nothing locally, so the audit drops them. The
   5 undirected-pattern references run fine and would still be scored 0 for all
   models. Fix: execute any read-only gold as written (`clean_cypher`) and keep
   governance as diagnostics, mirroring what prediction scoring already does. The
   oracle check in step 5 detects the problem.
2. **`pipecypher/graph_profiles.py:default_templates`** returns the FinBench seed
   templates for any unknown profile, including `t2c_*` and `enterprise_private`.
   With `template_source: mixed`, E3.5 runs try FinBench seeds (Account/Person
   slots) on these graphs. They fail with "slot bindings unavailable", which is
   audible but wastes attempts. Return `[]` for unknown profiles.
3. **`pipecypher/validator.py:structural_features`** sets `path_pattern` with
   `"*" in query`, so any `count(*)` counts as a path. That inflates the
   `path` strategy tag and `infer_difficulty` for PIPE's own benchmark too. The
   converter's `derived_category` uses a variable-length-relationship regex
   instead.

## 7. Files

- `pipecypher/external_benchmarks.py`: dataset and graph registry, converter,
  category heuristic, flags and slices, gold audit, oracle, schema-text parser,
  schema drift.
- `scripts/fetch_text2cypher2024.py`: CLI with `list`, `download`, `convert`,
  `audit-gold`, `oracle`, `subset`, and `schema-drift`.
- `scripts/fetch_neo4j_example_graphs.sh`: pinned, sha256-checked dump download
  and per-graph Community instance load and start.
- `configs/t2c_{recommendations,northwind,fincen}.yaml`: strict-valid run
  configs. `configs/schema_t2c_*_derived.json` are the derived schemas.
- `tests/test_external_benchmarks.py`: offline tests with a hand-written fixture.
