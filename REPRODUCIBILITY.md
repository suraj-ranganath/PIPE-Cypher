# Reproducibility Checklist

For every experiment run, record:

- git commit hash;
- config file path;
- generated schema file hash;
- graph source, scale factor, and import command;
- FinBench datagen/docs commit hashes and generated `LOAD CSV` import script hash;
- Neo4j version and database name;
- model ID and serving command;
- GPU IDs and `nvidia-smi` snapshot;
- generation command;
- output artifact directory;
- counts of accepted and rejected examples;
- validation, execution, and judge metrics.

Recommended command pattern:

```bash
git rev-parse HEAD | tee artifacts/current_commit.txt
python scripts/check_gpu_host.py | tee artifacts/gpu_snapshot.txt
python scripts/generate_finbench_import_cypher.py --output artifacts/import/finbench_load.cypher
python scripts/run_pipeline.py --config configs/finbench_full.yaml --run-name finbench_full 2>&1 | tee artifacts/finbench_full.log
```

June 1, 2026 live FinBench smoke evidence is in:

```text
artifacts/runs/20260601_122841_live_finbench_qwen9b_defaultslots/
```

That run used `configs/finbench_live_smoke.yaml`, FinBench SF0.1 loaded into Neo4j Community's default `neo4j` database, and local `Qwen/Qwen3.5-9B` served with vLLM on `ds-serv6`.

The all-category FinBench smoke is in:

```text
artifacts/runs/20260601_124531_live_finbench_qwen9b_8cat_seeded/
```

That run used `configs/finbench_live_categories_smoke.yaml` and accepted one example for each planned category.

June 1, 2026 live SNB smoke evidence is in:

```text
artifacts/runs/20260601_124201_live_snb_qwen9b_ids_template/
```

That run used `configs/snb_live_smoke.yaml`, the official SNB Cypher test-data loaded into a second Neo4j Community instance on Bolt port 7688, and the same local `Qwen/Qwen3.5-9B` vLLM endpoint.

June 1, 2026 mini-ablation evidence is summarized in:

```text
knowledge_base/mini_ablation_results.md
```

The source run directories are:

```text
artifacts/runs/20260601_133302_live_finbench_llm_only_probe_generic_scan_tag/
artifacts/runs/20260601_132232_live_finbench_mixed_mini_full_coverage/
artifacts/runs/20260601_130456_live_snb_mixed_mini_diverse/
artifacts/runs/20260601_135706_live_snb_qwen9b_8cat_seeded_fixed/
artifacts/runs/20260601_140632_20260601_midscale_finbench/
artifacts/runs/20260601_140855_20260601_midscale_snb/
```

The accepted live mid-scale benchmark export is in:

```text
artifacts/benchmarks/20260601_live_midscale/
```

It can be regenerated with:

```bash
python scripts/export_benchmark.py \
  --records \
    artifacts/runs/20260601_140632_20260601_midscale_finbench \
    artifacts/runs/20260601_140855_20260601_midscale_snb \
  --output-dir artifacts/benchmarks/20260601_live_midscale \
  --split-seed live-midscale-v1
```

The full-run seed-capacity checks are:

```bash
python scripts/estimate_seed_capacity.py --config configs/finbench_full.yaml
python scripts/estimate_seed_capacity.py --config configs/snb_full.yaml
```

The model availability check is:

```bash
python scripts/check_model_availability.py \
  --model Qwen/Qwen3.5-35B-A3B \
  --model Qwen/Qwen3.5-9B \
  --model BAAI/bge-m3 \
  --remote
```

The detached full-generation fallback launch command is:

```bash
SESSION=pipecypher_full_qwen9b \
RUN_PREFIX=20260601_full_qwen9b \
GENERATION_MODEL=Qwen/Qwen3.5-9B \
JUDGE_MODEL=Qwen/Qwen3.5-9B \
scripts/launch_live_full_generation_tmux.sh
```

The June 1, 2026 launched fallback run is:

```text
tmux session: pipecypher_full_qwen9b
log: logs/20260601_full_qwen9b_full_generation.log
FinBench run dir: artifacts/runs/20260601_142318_20260601_full_qwen9b_finbench/
status notes: knowledge_base/full_run_status.md
```

After both FinBench and SNB full-run directories exist, finalize the benchmark export and judge-audit packet with:

```bash
RUN_PREFIX=20260601_full_qwen9b \
PYTHON_BIN=/home/suraj/pipecypher-tools/runtime-venv/bin/python \
scripts/finalize_live_full_run.sh
```

If a long run exits before all categories reach target, create category-specific top-up configs and commands from the existing records:

```bash
python scripts/fill_missing_categories.py \
  --config configs/finbench_full.yaml \
  --records artifacts/runs/<finbench_run_dir> \
  --run-prefix 20260601_full_qwen9b_finbench_fill \
  --passes 3 \
  --dry-run
```

Remove `--dry-run` to launch the missing-category runs. Pass every original run and top-up run to `scripts/export_benchmark.py` or `scripts/finalize_live_full_run.sh` after completion.
The generated top-up commands include `--seen-records` so accepted questions from the original run and earlier fill passes are treated as duplicates during recovery.
When finalizing a recovered run, append top-up run directories with `EXTRA_RECORDS`:

```bash
RUN_PREFIX=20260601_full_qwen9b \
EXTRA_RECORDS="artifacts/runs/<topup_run_1> artifacts/runs/<topup_run_2>" \
PYTHON_BIN=/home/suraj/pipecypher-tools/runtime-venv/bin/python \
scripts/finalize_live_full_run.sh
```

To automate that recovery/finalization sequence after the main sequential tmux run exits:

```bash
RUN_PREFIX=20260601_full_qwen9b \
MAIN_SESSION=pipecypher_full_qwen9b \
FILL_PASSES=3 \
PYTHON_BIN=/home/suraj/pipecypher-tools/runtime-venv/bin/python \
scripts/auto_finalize_full_run_after_main.sh
```

To also run downstream Text2Cypher prediction and live execution evaluation:

```bash
RUN_PREFIX=20260601_full_qwen9b \
PYTHON_BIN=/home/suraj/pipecypher-tools/runtime-venv/bin/python \
RUN_DOWNSTREAM=1 \
scripts/finalize_live_full_run.sh
```

The downstream Text2Cypher smoke artifacts are:

```text
artifacts/predictions/20260601_qwen9b_midscale_test_predictions.jsonl
artifacts/evaluations/20260601_qwen9b_midscale_test_eval.jsonl
artifacts/evaluations/20260601_qwen9b_midscale_test_summary.json
```

The mid-scale judge calibration packet is:

```text
artifacts/audits/20260601_midscale_judge_audit.csv
```
