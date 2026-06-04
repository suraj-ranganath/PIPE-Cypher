# Clean Downstream Transfer Rerun Status

Created: 2026-06-04.

Benchmark: `artifacts/benchmarks/20260604_live_full_qwen9b_reviewfix`.

Purpose: rerun downstream zero-shot, ordered example-bank, scored no-signature,
and random same-category controls on the clean Qwen3.5-9B-only benchmark split.
Older downstream summaries were generated on a previous split whose generation
lineage included larger-model top-ups, so they must not be used for final
paper-facing clean claims.

## Final Status

All remote clean downstream queues completed on 2026-06-04. The paper-facing
suite contains 11 completed local downstream model checkpoints over the full
296-example clean held-out split. Each completed model has zero-shot evidence,
an ordered same-graph/category example-bank condition, a scored no-signature
condition, and random same-category controls for seeds 13, 17, and 23.

The attempted `ragraph-ai/stable-cypher-instruct-3b` transformers backend is
excluded from paper-facing results because local model loading failed with CUDA
OOM and only zero-row summaries were written. The failure is kept in logs and in
the markdown summary, but it is not counted as a model result.

## Completed Evidence

- `model_transfer_summary.json`: 10 zero/few-shot directories complete; the
  Neo4j Gemma-2 LoRA ordered evidence is stored as a separate ordered control.
- `fewshot_control_summary.json`: 11 paper-facing completed model slugs.
- `fewshot_control_uncertainty.json`: model-level paired bootstrap intervals
  over the 11 completed checkpoints.
- `fewshot_leakage_control_audit.json`: ordered, scored no-signature, and
  random selection-overlap audit.
- `downstream_uncertainty.json`: Qwen3.5-9B zero-shot row-level uncertainty.
- `downstream_error_report.json`: Qwen3.5-9B zero-shot error taxonomy.
- `strategy_diagnostics.json`: strategy-level coverage and Qwen3.5-9B
  downstream outcomes.
- `downstream_control_manifest.json`: readiness manifest; all expected 11
  zero-run and 45 control-run directories pass row-count and checksum checks
  after excluding the known failed stable-cypher slug.

## Paper-Facing Headline

The clean downstream paper claim is now:

- 11 completed local downstream models.
- Zero-shot execution accuracy range: 0.000--0.203; mean 0.036.
- Scored no-signature few-shot mean: 0.200.
- Ordered/random same-category example-bank means: 0.269/0.267.
- Gains are concentrated in 3/11 compatible checkpoints, supporting
  leakage-aware example-bank utility rather than universal transfer.

## Paper Promotion Rule

Only the clean snapshot files in this directory and the matching
`artifacts/evaluations/20260604_clean_*` directories should be used for final
downstream paper claims. Do not mix these results with older `20260603_*`
downstream outputs or the contaminated `20260601_live_full_qwen9b` export.
