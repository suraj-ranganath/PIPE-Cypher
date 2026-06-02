# PIPE-Cypher

PIPE-Cypher is a research pipeline for automatic generation of enterprise-specific NL-to-Cypher benchmarks over property graphs. It is designed as a Cypher-focused successor to PIPE-KG, with stronger schema constraints, deterministic validation, execution feedback, diversity control, and LLM-judge review.

The target paper is EMNLP Industry Track. The system is framed around property graph and Cypher workloads; Neo4j is used as the experimental backend.

## What Is Implemented

- Cypher client and schema introspection for Neo4j-compatible backends.
- Schema-aware validation for labels, explicit relationship types, Cypher arrow direction, undirected-pattern rejection, properties, categorical property values, and read-only safety.
- BalkanID-inspired query normalization and constraint prompts.
- Contextual return-column warnings for industry-useful result surfaces.
- Generic unlabeled node-scan warnings for diagnosing weak local-model generations.
- Category and difficulty metadata for benchmark generation.
- Local-model LLM interfaces for OpenAI-compatible servers such as vLLM.
- Deterministic and LLM-backed judge interfaces.
- Retrieval and diversity utilities.
- LDBC FinBench snapshot profile and Neo4j `LOAD CSV` import-script generator.
- Deterministic seeded templates and graph-backed slot binding for reproducible live smoke runs.
- Deterministic Cypher fallback that instantiates seed queries with bound graph values when an LLM proposal fails.
- LLM-judge schema slicing so local Qwen smoke models judge candidates without needing the full live schema in context.
- Pipeline runner scripts, configs, experiment matrix, paper outline, and literature notes.

## Quick Start

```bash
python -m pip install -e ".[dev]"
pytest
```

Inspect a graph schema:

```bash
python scripts/inspect_schema.py --config configs/local_smoke.yaml
```

Run a small generation pass:

```bash
python scripts/run_pipeline.py --config configs/local_smoke.yaml --run-name smoke
```

Run an offline smoke pass without Neo4j or an LLM server:

```bash
python scripts/run_pipeline.py --config configs/local_smoke.yaml --offline-smoke --run-name offline_smoke
python scripts/summarize_run.py artifacts/runs/<run_id>/records.jsonl
```

Run the secondary SNB reference smoke:

```bash
python scripts/run_pipeline.py --config configs/snb_smoke.yaml --offline-smoke --run-name snb_smoke
```

Materialize experiment configs:

```bash
python scripts/materialize_experiments.py \
  --matrix configs/experiment_matrix.yaml \
  --base-config configs/finbench_full.yaml \
  --output-dir configs/generated/finbench \
  --target-per-category 25

python scripts/materialize_experiments.py \
  --matrix configs/experiment_matrix.yaml \
  --base-config configs/snb_full.yaml \
  --output-dir configs/generated/snb \
  --target-per-category 25
```

The materialized suite includes baselines plus retrieval, judge, rewrite, model, and graph-mix ablations. Rewrite ablations use `generation.normalize_cypher`; `false` disables the normalization pass that adds `RETURN DISTINCT` and canonicalizes generated Cypher.

Sample judge calibration records:

```bash
python scripts/sample_judge_audit.py \
  --records artifacts/runs/<run_id>/records.jsonl \
  --output artifacts/audits/<run_id>_judge_audit.csv \
  --n 100
```

By default, audit sampling is stratified by graph profile, category, and judge
accept/reject outcome when those fields are present. Use `--no-stratify` only
for legacy global accept/reject sampling.

Analyze label coverage and calibration metrics after filling every `human_accept`:

```bash
python scripts/analyze_judge_audit.py \
  --audit artifacts/audits/20260601_full_qwen9b_judge_audit_v2.csv \
  --require-complete-labels
```

Use `--require-labels` only for local diagnostics that need at least one
completed row. Paper-facing calibration must require complete labels unless an
exclusion rule is documented before analysis.

Render a local browser packet for human calibration labeling:

```bash
python scripts/render_judge_audit_packet.py \
  --audit artifacts/audits/20260601_full_qwen9b_judge_audit_v2.csv \
  --output-html artifacts/audits/20260601_full_qwen9b_judge_audit_v2.html \
  --output-json experiments/snapshots/20260601_live_full_qwen9b/judge_audit_packet_v2.json \
  --output-tex paper_emnlp2026_industry/tables_judge_audit_coverage.tex
```

The labeling rubric is in `knowledge_base/judge_audit_protocol.md`.

Render appendix prompt contracts and representative accepted examples:

```bash
python scripts/render_appendix_material.py \
  --claim-map knowledge_base/claim_evidence_map.yaml \
  --output-claims paper_emnlp2026_industry/appendix_claim_evidence.tex \
  --examples experiments/snapshots/20260601_live_full_qwen9b/sample_examples.json \
  --output-prompts paper_emnlp2026_industry/appendix_prompt_contracts.tex \
  --output-examples paper_emnlp2026_industry/appendix_example_cards.tex \
  --max-examples 16
```

Check the GPU host:

```bash
python scripts/check_gpu_host.py
```

Sync the repo and launch the local Qwen/vLLM service on `ds-serv6`:

```bash
scripts/sync_to_ds_serv6.sh
MODEL=Qwen/Qwen3.5-9B \
CUDA_VISIBLE_DEVICES=2 \
MAX_MODEL_LEN=2048 \
GPU_MEMORY_UTILIZATION=0.90 \
CONDA_ENV=pipe-rdf-arr \
EXTRA_VLLM_ARGS='--no-enable-flashinfer-autotune --enforce-eager --max-num-seqs 1 --max-num-batched-tokens 2048' \
scripts/launch_ds_serv6_vllm.sh
ssh suraj@ds-serv6.ucsd.edu \
  'cd /home/suraj/PIPE-Cypher && source ~/miniforge3/etc/profile.d/conda.sh && conda activate pipe-rdf-arr && python scripts/check_llm_endpoint.py --base-url http://localhost:8000/v1 --model Qwen/Qwen3.5-9B'
```

Fetch LDBC sources:

```bash
GIT_DEPTH=1 scripts/fetch_ldbc_sources.sh external
```

Generate the FinBench Neo4j import script after producing snapshot CSVs:

```bash
SCALE_FACTOR=0.1 scripts/run_finbench_datagen.sh
python scripts/generate_finbench_import_cypher.py \
  --csv-base-url file:///finbench/snapshot \
  --output artifacts/import/finbench_load.cypher
```

The generated script preserves FinBench transaction multiedges by using `CREATE` for relationships. Clear the target Neo4j database before re-running relationship imports.

Start and load a user-space Neo4j Community smoke instance:

```bash
scripts/start_neo4j_community.sh
SNAPSHOT_DIR=/home/suraj/pipecypher-runs/finbench_sf0.1/data/snapshot \
  scripts/load_finbench_neo4j.sh
```

Run the live FinBench smoke after Neo4j and vLLM are running:

```bash
/home/suraj/pipecypher-tools/runtime-venv/bin/python scripts/inspect_schema.py \
  --config configs/finbench_live_smoke.yaml \
  --output configs/schema_finbench.json
/home/suraj/pipecypher-tools/runtime-venv/bin/python scripts/run_pipeline.py \
  --config configs/finbench_live_smoke.yaml \
  --run-name live_finbench_qwen9b_defaultslots
```

Schema inspection also infers low-cardinality string properties as categorical
values by default. Use `--categorical-max-values 0` to disable that pass.

The June 1, 2026 live smoke over FinBench SF0.1 accepted 4/4 examples with Qwen3.5-9B judge review and non-empty Neo4j execution.

For an all-category seeded FinBench smoke:

```bash
/home/suraj/pipecypher-tools/runtime-venv/bin/python scripts/run_pipeline.py \
  --config configs/finbench_live_categories_smoke.yaml \
  --run-name live_finbench_qwen9b_8cat_seeded
```

The June 1, 2026 all-category run accepted 8/8 examples across the full planned category set.

Start and load the bundled SNB Cypher test-data into a second user-space Neo4j instance:

```bash
RUN_ROOT=/home/suraj/pipecypher-neo4j-snb \
SESSION=pipecypher_neo4j_snb \
BOLT_PORT=7688 \
HTTP_PORT=7475 \
AUTH_ENABLED=false \
scripts/start_neo4j_community.sh
RUN_ROOT=/home/suraj/pipecypher-neo4j-snb \
BOLT_URI=bolt://localhost:7688 \
scripts/load_snb_neo4j.sh
```

Run the live SNB smoke:

```bash
/home/suraj/pipecypher-tools/runtime-venv/bin/python scripts/inspect_schema.py \
  --config configs/snb_live_smoke.yaml \
  --output configs/schema_snb.json
/home/suraj/pipecypher-tools/runtime-venv/bin/python scripts/run_pipeline.py \
  --config configs/snb_live_smoke.yaml \
  --run-name live_snb_qwen9b_ids_template
```

The June 1, 2026 live smoke over SNB test-data accepted 4/4 examples with Qwen3.5-9B judge JSON and non-empty Neo4j execution.

Run the live mini-ablation suite:

```bash
PYTHON_BIN=/home/suraj/pipecypher-tools/runtime-venv/bin/python \
  scripts/run_live_mini_ablation.sh
```

The June 1, 2026 mini-ablation evidence is summarized in `knowledge_base/mini_ablation_results.md`: FinBench LLM-only accepted 0/16, FinBench mixed accepted 16/29, and SNB mixed accepted 8/8.

The mini-ablation, target-five, and target-25 artifacts are development or interim scaled checkpoints only. Do not report them in the paper as experimental evidence. Paper ablations should use audited target-50-or-larger suites at minimum, preferably target-100 or repeated target-50 runs, with explicit run logs and both graph workloads when the claim is not graph-specific.

Run a larger bounded live ablation suite when the Qwen3.5-9B endpoint and both Neo4j databases are up on `ds-serv6`:

```bash
source ~/miniforge3/etc/profile.d/conda.sh
conda activate pipe-rdf-arr
cd /home/suraj/PIPE-Cypher
TARGET_PER_CATEGORY=50 \
PYTHON_BIN=/home/suraj/pipecypher-tools/runtime-venv/bin/python \
GENERATION_MODEL=Qwen/Qwen3.5-9B \
JUDGE_MODEL=Qwen/Qwen3.5-9B \
RUN_PREFIX=20260601_ablation50_qwen9b \
  scripts/run_live_ablation_suite.sh
```

The target-50 suite runs the intended paper-ablation variants: strict unconstrained LLM, reverse-only, validators+repair, no retrieval, no rewrite, no LLM judge, and full PIPE-Cypher, for both FinBench and SNB. Treat target-50 as the minimum paper-readiness threshold, not the ideal scale; increase to target-100 or repeat target-50 runs after checking runtime and endpoint stability.

For repeated suites, set `RUN_SEED` and keep it in the run prefix. The launcher
passes the seed through `run_pipeline.py --random-seed`, records it in each
run's `summary.txt`, and includes it in ablation summary metadata so repeated
target-50 or target-100 evidence can be audited as repeated-seed evidence rather
than uncontrolled reruns.

For long runs, prefer the tmux launcher. It can queue a larger suite behind an
active run and still preserve model IDs, revision metadata, and logs:

```bash
SESSION=pipecypher_ablation50_qwen9b \
WAIT_FOR_SESSION=pipecypher_ablation25_qwen9b \
TARGET_PER_CATEGORY=50 \
RUN_PREFIX=20260601_ablation50_qwen9b \
PYTHON_BIN=/home/suraj/pipecypher-tools/runtime-venv/bin/python \
GENERATION_MODEL=Qwen/Qwen3.5-9B \
JUDGE_MODEL=Qwen/Qwen3.5-9B \
  scripts/launch_live_ablation_suite_tmux.sh
```

For stronger reviewer-facing evidence, keep a target-100 suite running or queued
after target-50 completes. If the active remote root is not a Git checkout, stage
a separate code snapshot and collect from that root later. The current
target-100 run uses the exact-session-wait checkout below:

```bash
cd /home/suraj/PIPE-Cypher-150f596-target100-exact
CODE_REVISION=150f596f68dd530869efb497250610a40d3570ee \
SESSION=pipecypher_ablation100_qwen9b \
WAIT_FOR_SESSION=pipecypher_ablation50_qwen9b \
TARGET_PER_CATEGORY=100 \
RUN_PREFIX=20260601_ablation100_qwen9b \
PYTHON_BIN=/home/suraj/pipecypher-tools/runtime-venv/bin/python \
GENERATION_MODEL=Qwen/Qwen3.5-9B \
JUDGE_MODEL=Qwen/Qwen3.5-9B \
  bash scripts/launch_live_ablation_suite_tmux.sh
```

To queue a repeated target-50 suite behind a completed target-100 suite from a
fresh staged checkout:

```bash
cd /home/suraj/PIPE-Cypher-<commit>-target50-seed17
CODE_REVISION=<commit> \
SESSION=pipecypher_ablation50_qwen9b_seed17 \
WAIT_FOR_SESSION=pipecypher_ablation100_qwen9b \
TARGET_PER_CATEGORY=50 \
RUN_PREFIX=20260601_ablation50_qwen9b_seed17 \
RUN_SEED=17 \
PYTHON_BIN=/home/suraj/pipecypher-tools/runtime-venv/bin/python \
GENERATION_MODEL=Qwen/Qwen3.5-9B \
JUDGE_MODEL=Qwen/Qwen3.5-9B \
  bash scripts/launch_live_ablation_suite_tmux.sh
```

Completed ablation suites now write an audit packet under
`experiments/snapshots/<run_prefix>/`. To summarize an already-finished suite
without rerunning generation:

```bash
python scripts/summarize_live_ablation_suite.py \
  --glob 'artifacts/runs/*20260601_ablation50_qwen9b*' \
  --target-per-category 50 \
  --output-json experiments/snapshots/20260601_ablation50_qwen9b/ablation_suite_summary.json \
  --output-md experiments/snapshots/20260601_ablation50_qwen9b/ablation_suite_summary.md
```

The summarizer refuses to render a LaTeX paper table from incomplete suites
unless explicitly overridden for internal diagnostics.

Render an appendix-ready ablation figure only after the suite summary is
complete:

```bash
python scripts/render_ablation_suite_figure.py \
  --suite-summary experiments/snapshots/20260601_ablation50_qwen9b/ablation_suite_summary.json \
  --output paper_emnlp2026_industry/figures/ablation_suite_target50.pdf
```

For the staged target-100 run, use the staged remote root when collecting:

```bash
python scripts/collect_remote_ablation_suite.py \
  --remote-root /home/suraj/PIPE-Cypher-150f596-target100-exact \
  --run-prefix 20260601_ablation100_qwen9b \
  --target-per-category 100 \
  --wait-session pipecypher_ablation100_qwen9b \
  --poll-seconds 60
```

After two or more suites have completed and passed their individual readiness
audits, compare target-size or repeated-seed sensitivity from the collected
summary JSON files:

```bash
python scripts/compare_ablation_suites.py \
  experiments/snapshots/20260601_ablation50_qwen9b/ablation_suite_summary.json \
  experiments/snapshots/20260601_ablation100_qwen9b/ablation_suite_summary.json \
  experiments/snapshots/20260601_ablation50_qwen9b_seed17/ablation_suite_summary.json \
  --output-json experiments/snapshots/ablation_suite_comparison.json \
  --output-md experiments/snapshots/ablation_suite_comparison.md \
  --output-csv experiments/snapshots/ablation_suite_comparison.csv
```

To monitor the completed target-50 suite, active target-100 suite, and any
queued repeated-seed suites in one read-only command, including each suite's
`next_action` and safe `collection_command`. Already collected paper-ready
suites report `collection_command=not_applicable` so they are not fetched twice:

```bash
python scripts/monitor_remote_ablation_queue.py \
  --queue experiments/remote_ablation_queue.yaml
```

Estimate whether the built-in seeds can support the full category targets before launching long runs:

```bash
python scripts/estimate_seed_capacity.py --config configs/finbench_full.yaml
python scripts/estimate_seed_capacity.py --config configs/snb_full.yaml
```

Both full configs currently meet their per-category targets under the configured reverse-binding limits.

Check local model/cache availability on `ds-serv6`:

```bash
python scripts/check_model_availability.py \
  --model Qwen/Qwen3.5-35B-A3B \
  --model Qwen/Qwen3.5-9B \
  --model BAAI/bge-m3 \
  --remote
```

The June 1, 2026 check found `Qwen/Qwen3.5-35B-A3B` available remotely; it has since been staged under `/home/suraj/pipecypher-models/Qwen3.5-35B-A3B`. `Qwen/Qwen3.5-9B` and `BAAI/bge-m3` are cached.

Before serving the staged 35B target, check whether enough GPUs are safely free:

```bash
python scripts/check_vllm_capacity.py \
  --model-dir /home/suraj/pipecypher-models/Qwen3.5-35B-A3B \
  --gpu-memory-utilization 0.90 \
  --reserve-mib 2048 \
  --remote \
  --format json
```

This command exits with status 2 when serving is not currently feasible. The latest tracked snapshot is `experiments/snapshots/qwen35b_capacity_20260601_latest.json`: the staged 35B weights require four A5000 GPUs under this vLLM budget, while only GPU 3 is safely free. The full live benchmark therefore uses the documented 9B fallback.

Launch a detached full-generation fallback run with the currently served 9B endpoint:

```bash
SESSION=pipecypher_full_qwen9b \
RUN_PREFIX=20260601_full_qwen9b \
GENERATION_MODEL=Qwen/Qwen3.5-9B \
JUDGE_MODEL=Qwen/Qwen3.5-9B \
scripts/launch_live_full_generation_tmux.sh
```

Run the all-category SNB seeded smoke:

```bash
/home/suraj/pipecypher-tools/runtime-venv/bin/python scripts/run_pipeline.py \
  --config configs/snb_live_all_categories_smoke.yaml \
  --run-name live_snb_qwen9b_8cat_seeded_fixed
```

The June 1, 2026 all-category SNB run accepted 8/8 examples across the full planned category set.

Run the old live mid-scale suite for engineering diagnostics only:

```bash
RUN_PREFIX=20260601_midscale \
PYTHON_BIN=/home/suraj/pipecypher-tools/runtime-venv/bin/python \
  scripts/run_live_midscale.sh
```

The June 1, 2026 mid-scale runs accepted 40/46 FinBench candidates and 40/47 SNB candidates, reaching five accepted examples in every planned graph/category cell. These runs are too small for paper reporting and should not be used as publication evidence.

Export accepted mid-scale records into a benchmark package with stable IDs, splits, stats, and a manifest hash:

```bash
python scripts/export_benchmark.py \
  --records \
    artifacts/runs/20260601_140632_20260601_midscale_finbench \
    artifacts/runs/20260601_140855_20260601_midscale_snb \
  --output-dir artifacts/benchmarks/20260601_live_midscale \
  --split-seed live-midscale-v1
```

The current full live export contains 3,000 accepted examples: 2,000 FinBench, 1,000 SNB, and 375 accepted examples in every planned category across the two graphs.

The full JSONL export remains under ignored `artifacts/` paths, but the repo includes a tracked lightweight snapshot with checksums, aggregate stats, and one representative example per graph/category cell:

```text
experiments/snapshots/20260601_live_full_qwen9b/
```

Regenerate that snapshot from a local full export with:

```bash
python scripts/snapshot_benchmark_artifact.py \
  --export-dir artifacts/benchmarks/20260601_live_full_qwen9b \
  --output-dir experiments/snapshots/20260601_live_full_qwen9b \
  --source-export-dir artifacts/benchmarks/20260601_live_full_qwen9b
```

Generate and evaluate local Text2Cypher predictions on the exported test split:

```bash
python scripts/generate_text2cypher_predictions.py \
  --benchmark artifacts/benchmarks/20260601_live_full_qwen9b \
  --split test \
  --schema finbench=configs/schema_finbench.json \
  --schema snb=configs/schema_snb.json \
  --output artifacts/predictions/20260601_full_qwen9b_test_predictions.jsonl \
  --base-url http://localhost:8000/v1 \
  --model Qwen/Qwen3.5-9B

python scripts/evaluate_benchmark_predictions.py \
  --benchmark artifacts/benchmarks/20260601_live_full_qwen9b \
  --split test \
  --predictions artifacts/predictions/20260601_full_qwen9b_test_predictions.jsonl \
  --config finbench=configs/finbench_full.yaml \
  --config snb=configs/snb_full.yaml \
  --output artifacts/evaluations/20260601_full_qwen9b_test_eval.jsonl \
  --summary-output artifacts/evaluations/20260601_full_qwen9b_test_summary.json
```

The June 1, 2026 downstream evaluation over the 296-example full test split reached 0.189 execution accuracy, 0.189 answer F1, and 0.622 execution success with local Qwen3.5-9B.

Regenerate artifact-derived paper tables:

```bash
python scripts/render_paper_artifact_tables.py \
  --benchmark-dir artifacts/benchmarks/20260601_live_full_qwen9b \
  --evaluation-summary artifacts/evaluations/20260601_full_qwen9b_test_summary.json \
  --paper-dir paper_emnlp2026_industry
```

Compute diversity diagnostics and render the appendix table/figures:

```bash
python scripts/analyze_benchmark_diversity.py \
  --benchmark artifacts/benchmarks/20260601_live_full_qwen9b/all.jsonl \
  --schema configs/schema_finbench.json \
  --schema configs/schema_snb.json \
  --output-json experiments/snapshots/20260601_live_full_qwen9b/diversity_report.json \
  --output-tex paper_emnlp2026_industry/tables_diversity.tex

python scripts/analyze_failure_taxonomy.py \
  --records \
    artifacts/runs/20260601_142318_20260601_full_qwen9b_finbench \
    artifacts/runs/20260601_165047_20260601_full_qwen9b_snb \
    artifacts/runs/20260601_173836_20260601_full_qwen9b_finbench_fill_20260601_173235_negation_difference \
    artifacts/runs/20260601_173838_20260601_full_qwen9b_snb_fill_20260601_173235_negation_difference \
    artifacts/runs/20260601_173842_20260601_full_qwen9b_snb_fill_20260601_173235_path_temporal \
    artifacts/runs/20260601_173848_20260601_full_qwen9b_snb_fill_20260601_173235_ranking_topk \
  --output-json experiments/snapshots/20260601_live_full_qwen9b/failure_taxonomy.json \
  --output-tex paper_emnlp2026_industry/tables_failure_taxonomy.tex

python scripts/render_paper_figures.py \
  --diversity-report experiments/snapshots/20260601_live_full_qwen9b/diversity_report.json \
  --failure-taxonomy experiments/snapshots/20260601_live_full_qwen9b/failure_taxonomy.json \
  --benchmark-stats artifacts/benchmarks/20260601_live_full_qwen9b/stats.json \
  --downstream-summary artifacts/evaluations/20260601_full_qwen9b_test_summary.json \
  --output-dir paper_emnlp2026_industry/figures
```

The full-run raw `records.jsonl` files are ignored locally and can be copied from
`ds-serv6:/home/suraj/PIPE-Cypher/artifacts/runs/` when regenerating failure
taxonomy summaries. The tracked snapshot stores only the derived JSON/table/figure.

Compare completed run artifacts for ablation paper tables:

```bash
python scripts/compare_runs.py \
  artifacts/runs/20260601_133302_live_finbench_llm_only_probe_generic_scan_tag \
  artifacts/runs/20260601_132232_live_finbench_mixed_mini_full_coverage \
  artifacts/runs/20260601_130456_live_snb_mixed_mini_diverse
```

If a long full run exits with an underfilled category, generate exact top-up configs and commands from the existing records:

```bash
python scripts/fill_missing_categories.py \
  --config configs/finbench_full.yaml \
  --records artifacts/runs/<finbench_run_dir> \
  --run-prefix finbench_fill \
  --dry-run
```

The generated top-up commands pass the original records through `--seen-records`, so previously accepted questions are rejected as duplicates during recovery.
Pass completed top-up run directories to final export with `EXTRA_RECORDS="artifacts/runs/<topup_1> artifacts/runs/<topup_2>"`.

## Environment

The code reads configuration from YAML and environment variables. Common variables:

```bash
PIPE_CYPHER_NEO4J_URI=bolt://localhost:7687
PIPE_CYPHER_NEO4J_USER=neo4j
PIPE_CYPHER_NEO4J_PASSWORD=password
PIPE_CYPHER_NEO4J_DATABASE=neo4j
PIPE_CYPHER_LLM_BASE_URL=http://localhost:8000/v1
PIPE_CYPHER_LLM_MODEL=Qwen/Qwen3.5-9B
```

Generation knobs in YAML:

- `template_source: default` uses built-in seed templates only; this is best for reproducible smoke runs.
- `template_source: mixed` prepends seed templates to LLM-generated templates; this is the intended full-run setting.
- `deterministic_cypher_fallback: true` lets seed templates recover from failed LLM Cypher proposals by using graph-bound deterministic Cypher.

## Paper Positioning

PIPE-Cypher differs from static Text2Cypher datasets by focusing on repeatable benchmark creation for private enterprise graphs. The pipeline generates, validates, repairs, judges, and logs benchmark candidates under local-model and data-governance constraints.

Paper citation provenance is tracked in `knowledge_base/citation_verification.md`, and artifact-derived paper tables can be regenerated from the exported benchmark and downstream evaluation summaries.

For long-running Codex work, the reusable `/goal` prompt is in `knowledge_base/codex_goal_prompt.md`.
