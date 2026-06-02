# YourBench Transfer Notes

Inspection date: June 2, 2026

Source inspected:

- GitHub: https://github.com/huggingface/yourbench
- Local clone commit: `d9fa4c7966c052b6417a694968ff0d129d725828`
- Paper: Shashidhar et al., "YourBench: Easy Custom Evaluation Sets for Everyone", arXiv:2504.01833

## Bottom Line

YourBench is a document-grounded QA benchmark generator, so its document ingestion,
summarization, chunk citation, and LightEval export are not directly portable to
PIPE-Cypher. The meaningful transfer is at the benchmark-factory layer:
configuration safety, stage accounting, provenance-rich examples, output schema
contracts, quality filtering, and dataset card/reporting discipline.

These ideas strengthen PIPE-Cypher's industry story because enterprises need a
repeatable, auditable private benchmark-generation process, not only a one-time
generated dataset.

## High-Value Ideas To Borrow

1. Strict config validation before long jobs.
   YourBench rejects unknown YAML fields through Pydantic's `extra="forbid"` and
   exposes `yourbench validate`. PIPE-Cypher previously ignored unknown fields in
   `load_config`, which is risky for multi-hour GPU ablation runs. Immediate
   adaptation: `scripts/validate_config.py` plus reusable config validation.

2. Token/request/capacity estimation.
   YourBench has an `estimate` command before running expensive generation. The
   graph-query analogue should estimate candidate attempts, generation calls,
   judge calls, approximate prompt tokens, endpoint concurrency, and expected
   wall-clock by graph, category, and variant.

3. Stage-level logs and inference accounting.
   YourBench tracks stage tags, request IDs, retries, token counts, and aggregate
   inference logs. PIPE-Cypher should preserve the current JSONL decision logs
   but add a separate run ledger for stage duration, LLM calls, retry counts,
   errors, model IDs, endpoint, graph, and code revision.

4. Benchmark card generation.
   YourBench generates dataset cards. PIPE-Cypher should generate a redacted
   benchmark card with graph profile, schema fingerprint, privacy policy,
   value-sampling policy, model IDs, run command, quality gates, diversity
   metrics, judge calibration summary, and intended evaluation use.

5. Custom output schema contracts.
   YourBench lets users define a custom Pydantic output schema. PIPE-Cypher should
   use a validated benchmark-row schema for enterprise exports and optionally
   expose configurable redacted metadata contracts for downstream evaluators.

6. Multi-hop and cross-document sampling analogues.
   YourBench explicitly generates single-hop, multi-hop, and cross-document
   questions. PIPE-Cypher should treat this as evidence for deliberate structural
   sampling: single-relation queries, multi-hop paths, cross-neighborhood joins,
   temporal transaction paths, negation/difference, and top-k ranking. Exact
   combination sampling can be adapted to choose relationship-pattern
   neighborhoods uniformly instead of overusing common labels.

7. Citation-score analogue for graph grounding.
   YourBench filters by citation support. PIPE-Cypher can add graph-grounding
   diagnostics: literal-result overlap, return-context coverage, schema-mention
   coverage, value-placeholder coverage, and result-support evidence. These
   should start as diagnostic metadata and only become gates after ablation.

8. Question rewriting with provenance.
   YourBench stores rewritten questions with original question, model, rationale,
   and raw response. PIPE-Cypher already rewrites Cypher; a conservative NL
   rewrite stage could improve enterprise readability while preserving bound
   literals/placeholders and logging before/after text.

9. Dataset export discipline.
   YourBench offers structured local/HF exports and column documentation.
   PIPE-Cypher should keep column documentation current for raw, internal,
   redacted, and evaluation exports so companies know which fields can be shared.

10. Public argument framing.
    YourBench frames dynamic benchmarks as a response to static benchmark
    saturation, contamination, and expensive human evaluation. PIPE-Cypher should
    adapt that framing to private enterprise property graphs: schema drift,
    confidential values, graph-specific query idioms, and repeatable local
    benchmark refresh.

## What Not To Borrow Directly

- Document ingestion and summarization stages. PIPE-Cypher's grounding source is
  a property-graph schema and executable graph contents, not source documents.
- Citation scoring as-is. PIPE-Cypher needs executable query grounding, not text
  citation overlap.
- Hugging Face Hub upload as the default path. Enterprise use should default to
  local/redacted exports; public export is optional and only for sanitized study
  artifacts.
- OpenAI-cost framing. PIPE-Cypher must keep local-model operation as the default
  research and deployment story.

## Immediate Implementation Status

- Added strict run-config validation in `pipecypher.config`.
- Added `scripts/validate_config.py` for preflight checks before long GPU jobs.
- Added tests for unknown-key rejection, numeric guardrails, CLI acceptance of
  run configs, and rejection of non-run experiment matrices.

## Follow-Up Implementation Targets

- Add `scripts/estimate_run_capacity.py` to estimate LLM calls, judge calls,
  approximate token load, category cells, and endpoint wall-clock before target-50
  or target-100 runs.
- Add a redacted benchmark-card renderer and include its output in snapshots.
- Add a provenance column audit for accepted examples and redacted exports.
- Add graph-grounding diagnostic scores inspired by citation filtering.
- Add a cross-neighborhood sampler for harder multi-hop/path examples.
