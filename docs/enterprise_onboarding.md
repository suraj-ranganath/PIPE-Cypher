# Enterprise Onboarding

This guide describes how to run PIPE-Cypher on a company-owned property graph.
FinBench, SNB, and ICIJ are public study graphs; an enterprise deployment should
use the same pipeline contracts with the organization's own schema, values, and
user workloads.

## 1. Prepare Read-Only Access

Create a graph user with read-only privileges. PIPE-Cypher does not need write,
admin, index-management, or schema-mutation permissions during benchmark
generation. Put credentials in environment variables or a private config file;
do not commit credentials.

Start from [`configs/enterprise_template.yaml`](../configs/enterprise_template.yaml)
and configure:

- `generation.graph_profile`: a stable internal graph name.
- `neo4j.uri`, `neo4j.user`, `neo4j.password`, `neo4j.database`: the read-only
  graph endpoint.
- `models.llm_base_url`, `models.generation_model`, `models.judge_model`: the
  local OpenAI-compatible model endpoint and model ID.
- `privacy.categorical_max_values`: the maximum number of distinct string values
  exposed as categorical constraints during schema introspection.
- `privacy.categorical_max_value_chars`: the maximum length of any sampled
  categorical string.
- `privacy.categorical_omitted_properties`: exact or wildcard property patterns
  such as `*.note`, `*.comment`, and `*.address` that should never expose values.
- `generation.target_per_category`: the intended scale after the dry run.

## 2. Serve A Local Model

Serve `Qwen/Qwen3.5-9B` or another approved local model through vLLM or an
internal OpenAI-compatible gateway:

```bash
MODEL=Qwen/Qwen3.5-9B \
CUDA_VISIBLE_DEVICES=0 \
MAX_MODEL_LEN=2048 \
GPU_MEMORY_UTILIZATION=0.90 \
scripts/serve_qwen_vllm.sh
```

Verify the endpoint:

```bash
python scripts/check_llm_endpoint.py \
  --base-url http://localhost:8000/v1 \
  --model Qwen/Qwen3.5-9B
```

## 3. Introspect The Schema

```bash
python scripts/inspect_schema.py \
  --config configs/enterprise_template.yaml \
  --output configs/schema_enterprise_private.json
```

For high-sensitivity graphs, disable value exposure on the first pass:

```bash
python scripts/inspect_schema.py \
  --config configs/enterprise_template.yaml \
  --categorical-max-values 0 \
  --output configs/schema_enterprise_private_novalues.json
```

Review the schema summary before generation. Check relationship directions,
relationship properties, and low-cardinality categorical values. If a property is
sensitive, disable value sampling for that property before any broad run.

## 4. Run A Dry Pass

Start with a small `generation.target_per_category`, then inspect accepted and
rejected candidates before scaling.

```bash
python scripts/run_pipeline.py \
  --config configs/enterprise_template.yaml \
  --run-name enterprise_dry_run

python scripts/summarize_run.py artifacts/runs/<run_id>/records.jsonl
```

Expected dry-run checks:

- accepted examples pass read-only, syntax, schema, execution, non-empty-result,
  and judge gates;
- rejected examples have actionable failure reasons;
- relationship directions match business semantics;
- questions use organization terminology without exposing more values than the
  privacy policy allows;
- result samples are useful for judge review and downstream evaluation.

## 5. Scale And Export

Increase `generation.target_per_category` and run the same config through your
job scheduler:

```bash
python scripts/run_pipeline.py \
  --config configs/enterprise_template.yaml \
  --run-name enterprise_target50
```

Export raw internal artifacts:

```bash
python scripts/export_benchmark.py \
  --records artifacts/runs/<run_id> \
  --output-dir artifacts/benchmarks/enterprise_target50_raw
```

Create a redacted review copy:

```bash
python scripts/redact_benchmark_export.py \
  --input artifacts/benchmarks/enterprise_target50_raw \
  --output artifacts/benchmarks/enterprise_target50_redacted \
  --hash-placeholders
```

The redacted export preserves graph/category/difficulty/gate metadata and query
structure while replacing quoted values, entity values, and string-valued result
samples with deterministic placeholders.

## 6. Calibrate And Refresh

Generate a post-hoc judge audit sample after generation. Human labels calibrate
the automated gate; they are not used as a generation gate.

```bash
python scripts/sample_judge_audit.py \
  --records artifacts/runs/<run_id>/records.jsonl \
  --output artifacts/audits/enterprise_judge_audit.csv \
  --n 80

python scripts/analyze_judge_audit.py \
  --audit artifacts/audits/enterprise_judge_audit.csv \
  --require-complete-labels
```

Repeat schema introspection and benchmark generation after schema changes,
material categorical-value changes, or major graph-content refreshes. Keep schema
hashes and benchmark manifests tied to each benchmark release.
