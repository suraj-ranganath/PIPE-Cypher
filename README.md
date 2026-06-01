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

Analyze label coverage and calibration metrics after filling `human_accept`:

```bash
python scripts/analyze_judge_audit.py \
  --audit artifacts/audits/20260601_full_qwen9b_judge_audit.csv \
  --require-labels
```

The labeling rubric is in `knowledge_base/judge_audit_protocol.md`.

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

The materialized FinBench+SNB target-five ablation suite is summarized in `knowledge_base/target5_ablation_results.md` and rendered into `paper_emnlp2026_industry/tables_ablation5_results.tex`.

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

Run the live mid-scale suite:

```bash
RUN_PREFIX=20260601_midscale \
PYTHON_BIN=/home/suraj/pipecypher-tools/runtime-venv/bin/python \
  scripts/run_live_midscale.sh
```

The June 1, 2026 mid-scale runs accepted 40/46 FinBench candidates and 40/47 SNB candidates, reaching five accepted examples in every planned graph/category cell.

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

python scripts/render_paper_figures.py \
  --diversity-report experiments/snapshots/20260601_live_full_qwen9b/diversity_report.json \
  --benchmark-stats artifacts/benchmarks/20260601_live_full_qwen9b/stats.json \
  --downstream-summary artifacts/evaluations/20260601_full_qwen9b_test_summary.json \
  --output-dir paper_emnlp2026_industry/figures
```

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
