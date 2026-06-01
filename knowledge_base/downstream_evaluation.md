# Downstream Text2Cypher Evaluation Smoke

Date: June 1, 2026.

This note records local `Qwen/Qwen3.5-9B` Text2Cypher baseline evaluations on exported PIPE-Cypher benchmark test splits, including the final full-test run and earlier wiring smokes.

## Full Benchmark Evaluation

The full 3,000-example export is available at:

```text
artifacts/benchmarks/20260601_live_full_qwen9b/
```

Artifacts:

```text
predictions: artifacts/predictions/20260601_full_qwen9b_test_predictions.jsonl
evaluation: artifacts/evaluations/20260601_full_qwen9b_test_eval.jsonl
summary: artifacts/evaluations/20260601_full_qwen9b_test_summary.json
log: logs/20260601_full_qwen9b_downstream.log
```

Overall result:

| Split | Examples | Parse Valid | Read-Only | Schema Valid | Execution Success | Execution Accuracy | Answer F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `test` | 296 | 0.959 | 1.000 | 0.905 | 0.622 | 0.189 | 0.189 |

By graph:

| Graph | Examples | Parse Valid | Schema Valid | Execution Success | Execution Accuracy | Answer F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| FinBench | 200 | 1.000 | 0.990 | 0.655 | 0.160 | 0.160 |
| SNB | 96 | 0.875 | 0.729 | 0.552 | 0.250 | 0.250 |

By difficulty:

| Difficulty | Examples | Parse Valid | Schema Valid | Execution Success | Execution Accuracy | Answer F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Easy | 147 | 1.000 | 0.925 | 0.850 | 0.381 | 0.381 |
| Medium | 149 | 0.919 | 0.886 | 0.396 | 0.000 | 0.000 |

By category:

| Category | Examples | Execution Success | Execution Accuracy | Answer F1 |
| --- | ---: | ---: | ---: | ---: |
| `simple_aggregation` | 37 | 1.000 | 1.000 | 1.000 |
| `simple_retrieval` | 37 | 1.000 | 0.324 | 0.324 |
| `boolean_existence` | 37 | 0.189 | 0.189 | 0.189 |
| `complex_retrieval` | 37 | 0.703 | 0.000 | 0.000 |
| `negation_difference` | 37 | 0.892 | 0.000 | 0.000 |
| `path_temporal` | 37 | 0.865 | 0.000 | 0.000 |
| `ranking_topk` | 37 | 0.324 | 0.000 | 0.000 |
| `complex_aggregation` | 37 | 0.000 | 0.000 | 0.000 |

## Current Mid-Scale Benchmark

Export artifact:

```text
artifacts/benchmarks/20260601_live_midscale/
```

Test split size: 16 examples.

## Prediction Command

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
```

## Evaluation Command

```bash
/home/suraj/pipecypher-tools/runtime-venv/bin/python scripts/evaluate_benchmark_predictions.py \
  --benchmark artifacts/benchmarks/20260601_live_midscale \
  --split test \
  --predictions artifacts/predictions/20260601_qwen9b_midscale_test_predictions.jsonl \
  --config finbench=configs/finbench_live_midscale.yaml \
  --config snb=configs/snb_live_midscale.yaml \
  --output artifacts/evaluations/20260601_qwen9b_midscale_test_eval.jsonl \
  --summary-output artifacts/evaluations/20260601_qwen9b_midscale_test_summary.json
```

The evaluator compares execution result sets and treats single-column scalar outputs as alias-insensitive, so `COUNT(...) AS count` can match `COUNT(...) AS PostCount` when the scalar value is the same.

## Overall Result

| Split | Examples | Parse Valid | Read-Only | Schema Valid | Execution Success | Execution Accuracy | Answer F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `test` | 16 | 0.938 | 1.000 | 0.813 | 0.688 | 0.250 | 0.250 |

## By Graph

| Graph | Examples | Execution Success | Execution Accuracy | Answer F1 |
| --- | ---: | ---: | ---: | ---: |
| FinBench | 8 | 0.875 | 0.250 | 0.250 |
| SNB | 8 | 0.500 | 0.250 | 0.250 |

## By Category

| Category | Examples | Execution Success | Execution Accuracy | Answer F1 |
| --- | ---: | ---: | ---: | ---: |
| `simple_aggregation` | 2 | 1.000 | 1.000 | 1.000 |
| `boolean_existence` | 2 | 0.500 | 0.500 | 0.500 |
| `simple_retrieval` | 2 | 1.000 | 0.500 | 0.500 |
| `complex_retrieval` | 2 | 0.500 | 0.000 | 0.000 |
| `ranking_topk` | 2 | 1.000 | 0.000 | 0.000 |
| `complex_aggregation` | 2 | 0.000 | 0.000 | 0.000 |
| `negation_difference` | 2 | 0.500 | 0.000 | 0.000 |
| `path_temporal` | 2 | 1.000 | 0.000 | 0.000 |

## Previous Live-Mini Result

The previous `artifacts/benchmarks/20260601_live_mini` 12-example test split reached 0.250 execution accuracy, 0.250 answer F1, and 0.667 execution success. The mid-scale split supersedes it as the primary downstream smoke because it contains two test examples in each planned category.

## Takeaway

The smoke confirms that exported PIPE-Cypher benchmarks can be used for downstream model evaluation against live property graphs. The local 9B zero-shot baseline is strong enough on simple aggregation but weak on more operational categories, which supports the paper's need for category- and difficulty-aware benchmark reporting.
