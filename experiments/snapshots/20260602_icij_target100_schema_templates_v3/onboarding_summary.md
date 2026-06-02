# Enterprise Onboarding Run: 20260602_192926_20260602_icij_target100_schema_templates_v3

This is a sanitized aggregate snapshot. It intentionally excludes raw questions, Cypher, entity values, and execution result samples.

## Run

- Graph profile: `icij_offshoreleaks`
- Target per category: `100`
- Records: `983`
- Accepted: `800`
- Accept rate: `0.814`
- Categories at target: `8/8`
- Ready for paper promotion: `true`

## Metadata

- `code_revision`: `afa1791`
- `config`: `configs/icij_offshoreleaks_full.yaml`
- `generation_model`: `Qwen/Qwen3.5-9B`
- `graph_labels`: `5`
- `graph_nodes`: `2016523`
- `graph_relationship_types`: `14`
- `graph_relationships`: `3339267`
- `judge_model`: `Qwen/Qwen3.5-9B`
- `log_file`: `logs/20260602_icij_target100_schema_templates_v3.log`
- `run_prefix`: `20260602_icij_target100_schema_templates_v3`
- `run_seed`: `31`

## Category Coverage

| Category | Accepted | Target | At Target |
|---|---:|---:|---|
| simple_retrieval | 100 | 100 | true |
| complex_retrieval | 100 | 100 | true |
| simple_aggregation | 100 | 100 | true |
| complex_aggregation | 100 | 100 | true |
| boolean_existence | 100 | 100 | true |
| negation_difference | 100 | 100 | true |
| path_temporal | 100 | 100 | true |
| ranking_topk | 100 | 100 | true |

## Gate Rates

| Gate | Count | Rate |
|---|---:|---:|
| execution_success | 800 | 0.814 |
| judge_pass | 800 | 0.814 |
| non_empty_execution | 800 | 0.814 |
| read_only | 983 | 1.000 |
| schema_valid | 983 | 1.000 |
| syntax_valid | 983 | 1.000 |

## Failure Taxonomy

| Category | Failure | Count |
|---|---|---:|
| complex_aggregation | slot bindings unavailable | 61 |
| complex_aggregation | slot bindings exhausted | 14 |
| negation_difference | slot bindings unavailable | 23 |
| negation_difference | slot bindings exhausted | 15 |
| ranking_topk | slot bindings unavailable | 57 |
| ranking_topk | slot bindings exhausted | 13 |

## Legacy Schema-Derived Template Inference

This run predates template metadata logging, so these counts are inferred from the deterministic schema-derived question style and should be treated as diagnostic provenance rather than a row-level metadata field: `{"complex_aggregation": 97, "negation_difference": 28, "ranking_topk": 98}`.
