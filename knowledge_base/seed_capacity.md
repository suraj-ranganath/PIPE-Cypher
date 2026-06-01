# Seed Capacity Checks

Date: June 1, 2026.

Full PIPE-Cypher generation uses mixed mode: built-in workload seeds are tried before LLM-proposed templates. The built-in seeds must have enough graph-bound slot values to make the 3,000-example target plausible even when local LLM templates are weak.

## Scale Fixes

- Reverse slot binding now uses `generation.generated_query_limit` instead of a hard-coded 10-row execution cap.
- FinBench and SNB full configs use larger binding limits:
  - `configs/finbench_full.yaml`: `generated_query_limit: 300`
  - `configs/snb_full.yaml`: `generated_query_limit: 200`
- Added slotted negation and ranking seeds to avoid no-slot bottlenecks:
  - FinBench: account no-transfer questions scoped by person; top transfer sender scoped by person.
  - SNB: no-post-like members scoped by forum; most-member forum scoped by tag.
- Added all planned SNB categories as deterministic seeds.

## Commands

```bash
python scripts/estimate_seed_capacity.py --config configs/finbench_full.yaml
python scripts/estimate_seed_capacity.py --config configs/snb_full.yaml
```

## Results

FinBench full target: 250 accepted examples per category.

| Category | Target | Seeds | Slotted | No-slot | Binding limit | Est. capacity | Meets |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `simple_retrieval` | 250 | 1 | 1 | 0 | 300 | 300 | yes |
| `complex_retrieval` | 250 | 1 | 1 | 0 | 300 | 300 | yes |
| `simple_aggregation` | 250 | 1 | 1 | 0 | 300 | 300 | yes |
| `complex_aggregation` | 250 | 1 | 1 | 0 | 300 | 300 | yes |
| `boolean_existence` | 250 | 2 | 2 | 0 | 300 | 600 | yes |
| `negation_difference` | 250 | 6 | 4 | 2 | 300 | 1202 | yes |
| `path_temporal` | 250 | 2 | 2 | 0 | 300 | 600 | yes |
| `ranking_topk` | 250 | 6 | 4 | 2 | 300 | 1202 | yes |

SNB full target: 125 accepted examples per category.

| Category | Target | Seeds | Slotted | No-slot | Binding limit | Est. capacity | Meets |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `simple_retrieval` | 125 | 1 | 1 | 0 | 200 | 200 | yes |
| `complex_retrieval` | 125 | 1 | 1 | 0 | 200 | 200 | yes |
| `simple_aggregation` | 125 | 1 | 1 | 0 | 200 | 200 | yes |
| `complex_aggregation` | 125 | 1 | 1 | 0 | 200 | 200 | yes |
| `boolean_existence` | 125 | 1 | 1 | 0 | 200 | 200 | yes |
| `negation_difference` | 125 | 4 | 3 | 1 | 200 | 601 | yes |
| `path_temporal` | 125 | 1 | 1 | 0 | 200 | 200 | yes |
| `ranking_topk` | 125 | 3 | 1 | 2 | 200 | 202 | yes |

These are theoretical seed capacities, not accepted-example counts. Final examples still need deterministic validation, live execution, diversity checks, and LLM-judge acceptance.
