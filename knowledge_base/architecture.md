# PIPE-Cypher Architecture

PIPE-Cypher generates enterprise-specific NL-to-Cypher benchmark examples through five gates and one export step:

1. **Schema profiling**
   - Introspect labels, properties, relationship types, and observed relationship directions from the property graph backend.
   - Store a compact schema summary for prompting, validation, and reproducibility.

2. **Template and slot generation**
   - Generate category-balanced natural-language templates.
   - Use reverse Cypher queries to bind slots to graph-backed values before producing final examples.
   - Keep template slots sparse, usually zero to two entities, to avoid brittle synthetic questions.
   - Support `template_source=default` for deterministic live smoke runs and `template_source=mixed` for seeded full runs that combine proven workload templates with LLM-proposed templates.
   - Cycle through reverse-query binding rows per template so seeded runs do not reuse the first graph value for every accepted example.

3. **Cypher generation and repair**
   - Generate read-only Cypher with schema-visible constructs only.
   - Normalize generated queries using BalkanID-inspired rules: strip markdown, enforce `RETURN DISTINCT`, avoid reserved variables, preserve relationship directions, and reject writes.
   - Run repair on deterministic validation and execution errors.
   - Fall back to deterministic template Cypher with graph-bound slot values when an LLM proposal fails validation, execution, or judge review. This keeps smoke runs reproducible while retaining rejected LLM candidates for yield analysis in larger runs.

4. **Validation and execution**
   - Validate read-only safety, syntax shape, labels, relationship types, properties, and relationship direction.
   - Execute against Neo4j in read-only mode and reject empty results for benchmark examples unless the category intentionally tests emptiness.

5. **LLM-judge review**
   - Replace human-in-the-loop review with a local LLM judge.
   - Judge receives the question, Cypher, schema slice, execution sample, and validation summary.
   - Judge outputs strict JSON with pass/fail, ambiguity, semantic alignment, schema use, difficulty, and failure reason.
   - The vLLM client disables Qwen thinking traces with `reasoning_effort=none`, `include_reasoning=false`, and `chat_template_kwargs.enable_thinking=false`, then defensively strips any residual reasoning before strict JSON parsing.
   - The judge schema context is sliced to labels, relationship types, and properties used by the candidate Cypher. This keeps the local 9B smoke endpoint under its conservative context limit while preserving deterministic validation against the full schema.

Every candidate is logged as JSONL whether accepted or rejected. This supports generation-yield analysis, per-category failure analysis, and ablation studies.

Accepted candidates can then be exported into a benchmark package with stable IDs, deterministic train/dev/test splits, result samples, gate metadata, aggregate stats, and a manifest hash. This separates raw generation traces from the evaluation artifact used by downstream Text2Cypher experiments.

Before long runs, `scripts/estimate_seed_capacity.py` checks whether built-in seeds can meet configured per-category targets under the reverse-binding limit. This caught a scale blocker: slot binding was capped at 10 execution rows, and no-slot negation/ranking seeds could not scale. The pipeline now uses the configured binding limit and includes slotted negation and ranking seeds for both FinBench and SNB.

The June 1, 2026 live smokes used deterministic seeded templates, Qwen3.5-9B generation/judging through vLLM, and Neo4j execution over loaded FinBench SF0.1 and SNB test-data graphs. FinBench accepted 8/8 examples across all planned categories, and the fixed SNB all-category seeded run accepted 8/8 examples across the same category set.

## Category Set

- `simple_retrieval`: one-hop lookup.
- `complex_retrieval`: multi-hop lookup without aggregation.
- `simple_aggregation`: count or aggregate over one main relation.
- `complex_aggregation`: aggregate over joins or transaction paths.
- `boolean_existence`: existence/risk-screening style question.
- `negation_difference`: anti-join or absence of a relation.
- `path_temporal`: path, temporal, or transaction-neighborhood query.
- `ranking_topk`: top-k, ranking, or superlative query.

## Main Contribution Claim

The research contribution is not only synthetic data generation. It is an auditable generation system for private enterprise property graphs, with Cypher-specific constraints that make generated benchmarks safer, more executable, and more representative of deployed analytics workloads.
