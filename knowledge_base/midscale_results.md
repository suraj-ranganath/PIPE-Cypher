# Live Mid-Scale Generation Results

Date: June 1, 2026.

These runs use local `Qwen/Qwen3.5-9B`, FinBench SF0.1 on Bolt port 7687, and SNB Cypher test-data on Bolt port 7688. The goal was to verify that the updated seed capacity, reverse-binding limits, deterministic fallback, execution validation, and LLM judge can move beyond small smoke runs.

## Commands

```bash
RUN_PREFIX=20260601_midscale \
PYTHON_BIN=/home/suraj/pipecypher-tools/runtime-venv/bin/python \
  scripts/run_live_midscale.sh
```

Equivalent direct commands:

```bash
/home/suraj/pipecypher-tools/runtime-venv/bin/python scripts/run_pipeline.py \
  --config configs/finbench_live_midscale.yaml \
  --run-name 20260601_midscale_finbench

/home/suraj/pipecypher-tools/runtime-venv/bin/python scripts/run_pipeline.py \
  --config configs/snb_live_midscale.yaml \
  --run-name 20260601_midscale_snb
```

## Generation Summary

| Run | Config | Records | Accepted | Accept Rate | Notes |
| --- | --- | ---: | ---: | ---: | --- |
| `20260601_140632_20260601_midscale_finbench` | `configs/finbench_live_midscale.yaml` | 46 | 40 | 0.870 | Accepted five examples in every planned category. |
| `20260601_140855_20260601_midscale_snb` | `configs/snb_live_midscale.yaml` | 47 | 40 | 0.851 | Accepted five examples in every planned category. |

Both runs passed read-only, syntax, schema, and execution gates for every generated record. Rejections were from LLM-judge review or duplicate/diversity controls, not from deterministic validity failures.

## Benchmark Export

```bash
python scripts/export_benchmark.py \
  --records \
    artifacts/runs/20260601_140632_20260601_midscale_finbench \
    artifacts/runs/20260601_140855_20260601_midscale_snb \
  --output-dir artifacts/benchmarks/20260601_live_midscale \
  --split-seed live-midscale-v1
```

| Artifact | Examples | FinBench | SNB | Train | Dev | Test | SHA256 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `artifacts/benchmarks/20260601_live_midscale` | 80 | 40 | 40 | 48 | 16 | 16 | `543d99ad3cffde902bedc107811c4b3105285f4921804353f479028742909408` |

The export contains ten accepted examples in every planned category, with five per graph and category.

## Downstream Text2Cypher Smoke

```bash
/home/suraj/pipecypher-tools/runtime-venv/bin/python scripts/generate_text2cypher_predictions.py \
  --benchmark artifacts/benchmarks/20260601_live_midscale \
  --split test \
  --schema finbench=configs/schema_finbench.json \
  --schema snb=configs/schema_snb.json \
  --output artifacts/predictions/20260601_qwen9b_midscale_test_predictions.jsonl \
  --base-url http://localhost:8000/v1 \
  --model Qwen/Qwen3.5-9B \
  --schema-max-items 45 \
  --max-tokens 512 \
  --timeout-sec 180

/home/suraj/pipecypher-tools/runtime-venv/bin/python scripts/evaluate_benchmark_predictions.py \
  --benchmark artifacts/benchmarks/20260601_live_midscale \
  --split test \
  --predictions artifacts/predictions/20260601_qwen9b_midscale_test_predictions.jsonl \
  --config finbench=configs/finbench_live_midscale.yaml \
  --config snb=configs/snb_live_midscale.yaml \
  --output artifacts/evaluations/20260601_qwen9b_midscale_test_eval.jsonl \
  --summary-output artifacts/evaluations/20260601_qwen9b_midscale_test_summary.json
```

| Split | Examples | Parse Valid | Read-Only | Schema Valid | Execution Success | Execution Accuracy | Answer F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `test` | 16 | 0.938 | 1.000 | 0.813 | 0.688 | 0.250 | 0.250 |

By graph:

| Graph | Examples | Execution Success | Execution Accuracy | Answer F1 |
| --- | ---: | ---: | ---: | ---: |
| FinBench | 8 | 0.875 | 0.250 | 0.250 |
| SNB | 8 | 0.500 | 0.250 | 0.250 |

## Judge Audit Packet

```bash
python scripts/sample_judge_audit.py \
  --records \
    artifacts/runs/20260601_140632_20260601_midscale_finbench/records.jsonl \
    artifacts/runs/20260601_140855_20260601_midscale_snb/records.jsonl \
  --output artifacts/audits/20260601_midscale_judge_audit.csv \
  --n 40 \
  --seed 13
```

The CSV contains 40 unique accepted/rejected candidates with blank `human_accept` and `human_notes` columns for post-hoc calibration.
