# Enterprise Deployment And Onboarding Guide

This guide describes how a company can run PIPE-Cypher on its own property graph with a local model endpoint. FinBench and SNB are the paper workloads; an enterprise deployment should use the same pipeline contracts with a private graph profile.

## 1. Prepare Read-Only Access

Create a database user with read-only privileges for the target graph. The pipeline should never need write, admin, index-management, or schema-mutation permissions during benchmark generation. Put credentials in environment variables or a private config file; do not commit them.

Start from `configs/enterprise_template.yaml` and update:

- `generation.graph_profile`: a stable internal graph name, for example `identity_access` or `fraud_risk_2026q2`.
- `neo4j.uri`, `neo4j.user`, `neo4j.password`, `neo4j.database`: the read-only graph endpoint.
- `models.llm_base_url`, `models.generation_model`, `models.judge_model`: the local OpenAI-compatible endpoint and model ID.
- `privacy.categorical_max_values`: the maximum distinct string values to expose as categorical constraints during schema introspection.
- `privacy.categorical_max_value_chars`: the maximum length of any sampled categorical string. Keep this low enough to prevent long free-text fields from entering prompts.
- `privacy.categorical_omitted_properties`: exact or wildcard property patterns, such as `*.note` and `*.address`, that should never expose values during schema introspection.
- `generation.target_per_category`: the desired scale after a small dry run.

## 2. Serve A Local Model Endpoint

Serve `Qwen/Qwen3.5-9B` or another approved local model through vLLM or an OpenAI-compatible internal gateway. Keep Qwen reasoning traces out of artifacts with the settings already present in the template config:

```bash
MODEL=Qwen/Qwen3.5-9B \
CUDA_VISIBLE_DEVICES=0 \
MAX_MODEL_LEN=2048 \
GPU_MEMORY_UTILIZATION=0.90 \
scripts/serve_qwen_vllm.sh
```

Then verify the endpoint:

```bash
python scripts/check_llm_endpoint.py \
  --base-url http://localhost:8000/v1 \
  --model Qwen/Qwen3.5-9B
```

## 3. Introspect The Enterprise Schema

Run schema introspection with the enterprise config. The inspector uses `privacy.categorical_max_values`, `privacy.categorical_max_value_chars`, and `privacy.categorical_omitted_properties` unless overridden on the command line.

```bash
python scripts/inspect_schema.py \
  --config configs/enterprise_template.yaml \
  --output configs/schema_enterprise_private.json
```

For high-sensitivity graphs, disable value exposure during the first pass:

```bash
python scripts/inspect_schema.py \
  --config configs/enterprise_template.yaml \
  --categorical-max-values 0 \
  --output configs/schema_enterprise_private_novalues.json
```

Review the schema summary before generation. In particular, check that relationship directions, relationship properties, and low-cardinality categorical values are correct. If a property is sensitive but low-cardinality, either disable value sampling or remove that property from the schema summary before a broad internal run.

## 4. Run A Dry Pass

Start with a copied config whose `generation.target_per_category` is set to a
small value such as `2`, then inspect rejected records before scaling.

```bash
python scripts/run_pipeline.py \
  --config configs/enterprise_template.yaml \
  --run-name enterprise_dry_run

python scripts/summarize_run.py artifacts/runs/<run_id>/records.jsonl
```

Expected dry-run checks:

- all accepted examples pass read-only, syntax, schema, execution, non-empty-result, and judge gates;
- rejected examples have actionable failure reasons rather than silent drops;
- relationship directions match business semantics;
- questions use enterprise terminology without leaking more values than the privacy policy allows;
- result samples are useful enough for judge review and downstream evaluation.

## 5. Scale Generation

After the dry run, increase `generation.target_per_category` and run the same config in `tmux` or an internal job scheduler. Record the git revision, schema hash, model ID, endpoint URL, run command, and artifact directory.

```bash
python scripts/run_pipeline.py \
  --config configs/enterprise_template.yaml \
  --run-name enterprise_target50
```

Use category top-ups only when the under-target categories are understood. Do not weaken validators to improve yield; instead, record the optional gate as an ablation.

## 6. Export Raw Internal And Redacted Review Artifacts

Raw benchmark exports are for authorized internal users only:

```bash
python scripts/export_benchmark.py \
  --records artifacts/runs/<run_id> \
  --output-dir artifacts/benchmarks/enterprise_target50_raw
```

For broader review, create a redacted copy:

```bash
python scripts/redact_benchmark_export.py \
  --input artifacts/benchmarks/enterprise_target50_raw \
  --output artifacts/benchmarks/enterprise_target50_redacted \
  --hash-placeholders
```

The redacted export preserves graph/category/difficulty/gate metadata and query structure while replacing quoted values, entity values, and string-valued result samples with deterministic placeholders. Use `--include-private-mapping` only for private debugging, never for external sharing.

## 7. Calibrate The Judge

Generate a post-hoc audit sample after the automated pipeline completes. Human labels are calibration evidence, not a generation gate.

```bash
python scripts/sample_judge_audit.py \
  --records artifacts/runs/<run_id>/records.jsonl \
  --output artifacts/audits/enterprise_judge_audit.csv \
  --n 80

python scripts/analyze_judge_audit.py \
  --audit artifacts/audits/enterprise_judge_audit.csv \
  --require-complete-labels
```

For production use, treat zero or near-zero false accepts as the most important safety signal. False rejects reduce generation yield but do not corrupt the accepted benchmark.

## 8. Refresh As The Graph Evolves

Repeat schema introspection and generation after schema changes, material categorical-value changes, or major graph-content refreshes. Keep old and new schema hashes in the benchmark manifest so downstream Text2Cypher evaluation can be tied to a specific graph state.
