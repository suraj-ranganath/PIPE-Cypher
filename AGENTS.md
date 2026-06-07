# PIPE-Cypher Agent Notes

PIPE-Cypher is a public library for generating private NL-to-Cypher benchmarks
from a live property graph. Optimize for users with proprietary graphs who want
to evaluate or improve AI agents without sending schema, values, or examples
outside their environment.

## Non-Negotiables

- Keep `main` library-facing. Do not add paper source, submission packages, or
  private experiment logs here.
- Treat all graph access as read-only. Generated Cypher is unsafe until it
  passes read-only, syntax, schema, direction, execution, and judge checks.
- Never commit credentials, private schema dumps, raw proprietary values, or
  unredacted benchmark exports.
- Prefer local or organization-hosted OpenAI-compatible model endpoints. Paid or
  external APIs should not be defaults.
- Keep Neo4j as one backend implementation detail. Write docs and code around
  Cypher/property graphs unless a file is explicitly backend-specific.
- Do not hard-code FinBench, SNB, or ICIJ assumptions into enterprise paths.

## High-Signal Files

- `configs/enterprise_template.yaml`: starting config for a company graph.
- `docs/enterprise_onboarding.md`: full onboarding flow.
- `docs/benchmark_format.md`: exported JSONL schema and eval protocol.
- `scripts/inspect_schema.py`: profile a live graph.
- `scripts/run_pipeline.py`: generate and judge examples.
- `scripts/export_benchmark.py`: create train/dev/test benchmark splits.
- `scripts/redact_benchmark_export.py`: produce shareable review artifacts.
- `scripts/sample_judge_audit.py`, `scripts/analyze_judge_audit.py`: calibrate
  the automated judge after generation.
- `pipecypher/validator.py`, `cypher_parser.py`, `schema.py`,
  `schema_templates.py`, `privacy.py`, `diversity_selection.py`: core safety and
  quality logic.

## Enterprise Onboarding Path

1. Start from `configs/enterprise_template.yaml`; put secrets in env/private
   files, not git.
2. Use read-only graph credentials. No write/admin/index permissions.
3. Run schema inspection. For sensitive graphs, first set
   `privacy.categorical_max_values: 0`.
4. Review labels, relationship directions, properties, omitted properties, and
   sampled categorical values before any LLM call.
5. Verify the local model endpoint with `scripts/check_llm_endpoint.py`.
6. Dry run with a tiny `generation.target_per_category`; inspect accepted and
   rejected records.
7. Scale only after gate failures are understood. Export raw internal artifacts
   and redacted review artifacts separately.
8. Use accepted train/dev/test JSONL as agent eval data, few-shot/RAG examples,
   or future SFT data. Keep split manifests tied to graph/schema hashes.

## Generation Quality Rules

- Preserve exact quoted Cypher literals. Do not normalize whitespace inside
  strings.
- Prefer parser/schema-derived checks over prompt-only rules.
- Keep relationship direction explicit unless the schema truly permits both.
- Sparse enterprise schemas need schema-derived relationship-count, anti-join,
  and top-k templates; fail loudly if slot bindings are unavailable.
- Diversity matters: track category, difficulty, schema coverage, query
  signature concentration, lexical diversity, and value/entity reuse.
- Do not weaken validators to improve yield. Add an explicit optional mode or
  ablation if a check must be relaxed.

## Useful Commands

```bash
python -m pip install -e ".[dev]"
pytest
python scripts/inspect_schema.py --config configs/enterprise_template.yaml --output configs/schema_enterprise_private.json
python scripts/run_pipeline.py --config configs/enterprise_template.yaml --run-name enterprise_dry_run
python scripts/summarize_run.py artifacts/runs/<run_id>/records.jsonl
python scripts/export_benchmark.py --records artifacts/runs/<run_id> --output-dir artifacts/benchmarks/<name>_raw
python scripts/redact_benchmark_export.py --input artifacts/benchmarks/<name>_raw --output artifacts/benchmarks/<name>_redacted --hash-placeholders
```

