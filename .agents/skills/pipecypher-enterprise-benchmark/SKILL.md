---
name: pipecypher-enterprise-benchmark
description: Use when helping a user onboard a proprietary or hosted property graph into PIPE-Cypher, configure read-only Cypher access, set privacy/value-sampling policy, generate synthetic NL-to-Cypher benchmark data, or turn accepted examples into agent eval, few-shot/RAG, or training data.
---

# PIPE-Cypher Enterprise Benchmark Skill

Goal: help a user create a private, executable, diverse NL-to-Cypher benchmark
for their own graph, suitable for evaluating AI agents and improving
schema-specific Text2Cypher behavior.

## First Questions

Ask only for missing blockers:

- graph endpoint type and read-only connection details;
- whether value samples may enter prompts;
- local/OpenAI-compatible model endpoint and model id;
- target use: eval only, few-shot/RAG bank, SFT data, or all three;
- initial target size per category.

Never ask for secrets in chat. Tell the user to place them in env vars or a
private config file.

## Onboarding Flow

1. Copy `configs/enterprise_template.yaml` to a private config.
2. Set `neo4j.*`, `models.*`, `paths.schema_path`, and
   `generation.graph_profile`.
3. For the first pass on sensitive graphs:
   `privacy.categorical_max_values: 0`.
4. Add sensitive property patterns to
   `privacy.categorical_omitted_properties` before schema inspection.
5. Validate config before long jobs:
   `python scripts/validate_config.py --config <config>`.
6. Inspect schema:
   `python scripts/inspect_schema.py --config <config> --output <schema.json>`.
7. Review labels, rel types, directions, relationship properties, sampled
   categorical values, and omitted fields.
8. Verify model endpoint:
   `python scripts/check_llm_endpoint.py --base-url <url> --model <model>`.
9. Dry run small:
   `python scripts/run_pipeline.py --config <config> --run-name <dry_run>`.
10. Summarize and inspect records before scaling:
    `python scripts/summarize_run.py artifacts/runs/<run_id>/records.jsonl`.

## Synthetic Benchmark Generation

Use the full category set unless the user requests otherwise:

```text
simple_retrieval, complex_retrieval, simple_aggregation,
complex_aggregation, boolean_existence, negation_difference,
path_temporal, ranking_topk
```

Quality gates that should stay enabled:

- read-only safety;
- schema labels/properties/relationship types;
- relationship direction;
- exact literal/value policy;
- live execution with non-empty result unless intentionally disabled;
- deterministic rewrite audit;
- local LLM judge;
- diversity/category/difficulty tracking.

If sparse categories fail, prefer schema-derived templates:

- relationship-count aggregation;
- anti-join negation;
- top-k over safe counts or low-cardinality properties.

Do not fall back to fake values or broad placeholders. Report `slot bindings
unavailable` or `slot bindings exhausted`.

## Export For Agents

After a clean run:

```bash
python scripts/export_benchmark.py --records artifacts/runs/<run_id> --output-dir artifacts/benchmarks/<name>_raw
python scripts/redact_benchmark_export.py --input artifacts/benchmarks/<name>_raw --output artifacts/benchmarks/<name>_redacted --hash-placeholders
```

Use raw internal JSONL for agent eval against the same graph snapshot. Use the
redacted export for broader review. Use `train.jsonl` as a schema-specific
example bank for few-shot/RAG; use `dev.jsonl` for prompt/retrieval tuning; use
`test.jsonl` only for final evaluation.

For SFT, keep only accepted examples with stable graph/schema hashes and
provenance. Do not train on test examples.

## Failure Triage

- Parse invalid: tighten prompt format or parser normalization.
- Schema invalid: inspect profile freshness and hallucinated labels/properties.
- Direction invalid: check relationship direction in schema, not NL wording.
- Empty result: inspect reverse binding, literal policy, and over-restrictive
  predicates.
- Judge reject: inspect ambiguity, return columns, and semantic alignment.
- Low diversity: increase overgeneration and run diversity selection; monitor
  query-signature concentration and value reuse.

## Safety Defaults

Use read-only credentials, bounded result samples, omitted sensitive properties,
local model endpoints, redacted exports, and post-hoc human judge calibration.
Do not weaken privacy or validators to improve yield without an explicit user
decision.

