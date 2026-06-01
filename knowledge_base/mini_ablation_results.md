# Live Mini-Ablation Results

Date: June 1, 2026.

These runs use local `Qwen/Qwen3.5-9B`, the live FinBench SF0.1 Neo4j graph on Bolt port 7687, and the live SNB Cypher test-data Neo4j graph on Bolt port 7688.

## Commands

```bash
/home/suraj/pipecypher-tools/runtime-venv/bin/python scripts/run_pipeline.py \
  --config configs/finbench_live_llm_only_probe.yaml \
  --run-name live_finbench_llm_only_probe

/home/suraj/pipecypher-tools/runtime-venv/bin/python scripts/run_pipeline.py \
  --config configs/finbench_live_mixed_mini.yaml \
  --run-name live_finbench_mixed_mini_full_coverage

/home/suraj/pipecypher-tools/runtime-venv/bin/python scripts/run_pipeline.py \
  --config configs/snb_live_mixed_mini.yaml \
  --run-name live_snb_mixed_mini_diverse

/home/suraj/pipecypher-tools/runtime-venv/bin/python scripts/run_pipeline.py \
  --config configs/snb_live_all_categories_smoke.yaml \
  --run-name live_snb_qwen9b_8cat_seeded_fixed
```

## Summary

| Run | Config | Records | Accepted | Accept Rate | Notes |
| --- | --- | ---: | ---: | ---: | --- |
| `20260601_133302_live_finbench_llm_only_probe_generic_scan_tag` | `configs/finbench_live_llm_only_probe.yaml` | 16 | 0 | 0.000 | Raw Qwen template/Cypher path collapsed to 16/16 generic node scans; no deterministic seed/fallback. |
| `20260601_132232_live_finbench_mixed_mini_full_coverage` | `configs/finbench_live_mixed_mini.yaml` | 29 | 16 | 0.552 | Mixed seeded+LLM run accepted two examples in every planned FinBench category after scalar-binding and duplicate-question gates. |
| `20260601_130456_live_snb_mixed_mini_diverse` | `configs/snb_live_mixed_mini.yaml` | 8 | 8 | 1.000 | Mixed seeded+LLM run accepted two examples per smoke category with duplicate-question protection. |
| `20260601_135706_live_snb_qwen9b_8cat_seeded_fixed` | `configs/snb_live_all_categories_smoke.yaml` | 8 | 8 | 1.000 | Seeded SNB run accepted one example in every planned category after adding clear complex aggregation and slotted scale seeds. |

## FinBench Mixed Category Coverage

| Category | Attempts | Accepted |
| --- | ---: | ---: |
| `simple_retrieval` | 6 | 2 |
| `complex_retrieval` | 2 | 2 |
| `simple_aggregation` | 7 | 2 |
| `complex_aggregation` | 6 | 2 |
| `boolean_existence` | 2 | 2 |
| `negation_difference` | 2 | 2 |
| `path_temporal` | 2 | 2 |
| `ranking_topk` | 2 | 2 |

The dominant FinBench rejection pattern was local Qwen generating `MATCH (n) RETURN DISTINCT n LIMIT 1` for ambitious LLM-proposed templates. This supports the paper's claim that deterministic seeding, scalar reverse-binding, duplicate-question control, fallback, execution validation, and judge review are necessary for useful private benchmark generation under local-model constraints.

The comparison table can be regenerated directly from artifacts:

```bash
python scripts/compare_runs.py \
  artifacts/runs/20260601_133302_live_finbench_llm_only_probe_generic_scan_tag \
  artifacts/runs/20260601_132232_live_finbench_mixed_mini_full_coverage \
  artifacts/runs/20260601_130456_live_snb_mixed_mini_diverse
```

## Live Mini Benchmark Export

Accepted FinBench mixed-run records and all-category SNB seeded records were exported as a downstream benchmark package:

```bash
python scripts/export_benchmark.py \
  --records \
    artifacts/runs/20260601_132232_live_finbench_mixed_mini_full_coverage \
    artifacts/runs/20260601_135706_live_snb_qwen9b_8cat_seeded_fixed \
  --output-dir artifacts/benchmarks/20260601_live_all_category_mini \
  --split-seed live-all-category-mini-v1
```

Export summary:

| Artifact | Examples | FinBench | SNB | Train | Dev | Test |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `artifacts/benchmarks/20260601_live_all_category_mini` | 24 | 16 | 8 | 15 | 1 | 8 |

All 24 exported examples passed read-only, syntax, schema, execution, and judge gates. The export contains three accepted examples in every planned category across the two graphs. The manifest hash is `32ee49f53a22930dacafdcfcfe159d447ab65a1fac398c56cf2f5af7996d5b46`.

## SNB Mixed Category Coverage

| Category | Attempts | Accepted |
| --- | ---: | ---: |
| `simple_retrieval` | 2 | 2 |
| `complex_retrieval` | 2 | 2 |
| `simple_aggregation` | 2 | 2 |
| `ranking_topk` | 2 | 2 |

The SNB mixed run originally exposed a duplicate no-slot ranking question. The pipeline now rejects duplicate accepted questions and the SNB seed set includes a second ranking template, `Which person liked the most posts?`.

## SNB All-Category Seeded Coverage

| Category | Attempts | Accepted |
| --- | ---: | ---: |
| `simple_retrieval` | 1 | 1 |
| `complex_retrieval` | 1 | 1 |
| `simple_aggregation` | 1 | 1 |
| `complex_aggregation` | 1 | 1 |
| `boolean_existence` | 1 | 1 |
| `negation_difference` | 1 | 1 |
| `path_temporal` | 1 | 1 |
| `ranking_topk` | 1 | 1 |

The first SNB all-category attempt exposed ambiguous complex-aggregation wording. The fixed template asks for a distinct post count over forums joined by a person and passed LLM-judge review.
