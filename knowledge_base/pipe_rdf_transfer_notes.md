# PIPE-RDF Transfer Notes

Date: 2026-06-02

Source inspected: `/Users/suraj/Desktop/Archive/PIPE-KG/PIPE-RDF-arxiv-submission.zip` and the adjacent `paper_acl2026_industry` working directory.

## What PIPE-RDF Does Well

PIPE-RDF presents the generator as an observable benchmark factory rather than only a dataset release. The most useful presentation choices are:

- strategy/operator coverage heatmaps that show which query operations each natural-language category exercises;
- strategy-conditioned error heatmaps that separate weak categories from weak operators;
- explicit pre-repair and post-repair validity reporting;
- latency, prompt-length, retrieval-score, and answer-count diagnostics for operational transparency;
- a radar-style view of structural category complexity;
- clear separation between benchmark-generation quality and downstream model quality.

## What We Added To PIPE-Cypher

The highest-value paper-ready transfer is strategy diagnostics over the existing audited PIPE-Cypher artifacts. Category balance alone can hide operator concentration, so PIPE-Cypher now derives Cypher strategy tags from each accepted query's structural features and reports:

- a strategy diagnostics table over the 3,000-example export;
- a strategy-coverage heatmap by workload category;
- a strategy-conditioned downstream outcome figure over the full held-out Qwen3.5-9B Text2Cypher evaluation.

These diagnostics use only completed, audited paper artifacts:

- benchmark: `artifacts/benchmarks/20260601_live_full_qwen9b/all.jsonl`;
- downstream evaluation: `artifacts/evaluations/20260601_full_qwen9b_test_eval.jsonl`;
- report: `experiments/snapshots/20260601_live_full_qwen9b/strategy_diagnostics.json`.

## What We Did Not Add Yet

PIPE-RDF's latency and prompt-length diagnostics are useful, but should not be promoted into the PIPE-Cypher paper until we have complete stage-level ledgers for the reported full runs. A future paper-ready version should include per-stage request counts, retries, token estimates or token counts, endpoint latency, and graph execution latency for every generation/judge/downstream stage.

PIPE-RDF's retrieval-score histogram is also useful, but the current PIPE-Cypher reported artifacts do not yet have a complete retrieval-score distribution tied to accepted and rejected candidates. This should be generated in a future run with provenance-rich request ledgers before appearing in the appendix.

## Research Framing Takeaway

PIPE-RDF reinforces that an automatic benchmark paper should make the pipeline's behavior legible. For PIPE-Cypher, the strongest adapted framing is: the artifact is balanced by graph/category/difficulty, but we also audit operator strategies and downstream error modes so reviewers can see whether the benchmark exercises the Cypher operations that matter in enterprise graph analytics.
