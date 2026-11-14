# Clean Downstream Transfer Rerun Status

Created: 2026-06-04.

> **INVALIDATED 2026-11-11. Do not cite this suite.** 8 of the 11 "completed"
> checkpoints (both aigentx LoRAs, Azzedde, Gemma-2-9B-IT, Neo4j Gemma-3-4B,
> projectwilsen, Saiprasanth15, tomasonjo) received
> `404 Client Error: Not Found for url: http://localhost:800{0,1}/v1/chat/completions`
> on 296/296 requests in every zero-shot and control run. Their predictions are
> empty strings and the evaluator scored them 0.000. The "8/11 at 0.000" and
> "bimodal transfer" findings in the EMNLP 2026 submission are infrastructure
> failures, not model results. On the earlier (non-paper) split the same
> checkpoints scored 0.07-0.29 zero-shot and 0.73-0.99 few-shot, which is
> consistent with that reading. The readiness manifest below checked row counts
> and checksums, not request errors.
>
> Only Qwen3.5-9B, Qwen2.5-Coder-7B-Instruct, and the Neo4j Gemma-2 LoRA have
> real predictions here. Those three remain subject to the scoring fixes listed
> in `knowledge_base/eacl_revision_plan.md`: governance-gated execution and
> strict context-column equality. `pipecypher/downstream_model_transfer.py` now
> refuses any run with a prediction-failure rate above 1%.

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
