# PIPE-Cypher Agent Instructions

PIPE-Cypher is an industry-track research codebase for automatic benchmark generation for natural-language-to-Cypher systems over enterprise property graphs.

## Non-Negotiable Project Constraints

- Use Cypher/property-graph language in the paper and docs. Neo4j is the experimental backend, not the conceptual contribution.
- Do not use paid generation APIs for dataset generation. Use local models on `suraj@ds-serv6.ucsd.edu`.
- Default generation/judge model: `Qwen/Qwen3.5-35B-A3B` served locally with vLLM when it fits. Smoke-test fallback: `Qwen/Qwen3.5-9B`.
- For Qwen/vLLM, keep reasoning traces out of generated artifacts: use `reasoning_effort=none`, `include_reasoning=false`, `chat_template_kwargs.enable_thinking=false`, and strip residual `</think>` preambles before JSON parsing.
- Default embedding model: BGE-M3 or another local embedding model.
- Primary graph workload: LDBC FinBench, because it targets financial fraud and risk-control scenarios. Secondary generality workload: LDBC SNB.
- Preserve the BalkanID Cypher work as a first-class design source. Reuse its ideas for constrained prompting, relationship direction discipline, read-only query safety, `RETURN DISTINCT`, exact matching for quoted values, required contextual return columns, synonym normalization, categorical-property constraints, and post-generation rewrites.
- Human review is not a generation gate. Use deterministic validation plus LLM-judge review. A small human audit may be used only to calibrate judge reliability for the paper.

## Engineering Rules

- Keep the pipeline runnable without GPU access for deterministic tests.
- Treat generated Cypher as unsafe until it passes read-only, schema, syntax, execution, and judge checks.
- Prefer schema-derived constraints over prompt-only instructions.
- Log every accepted and rejected candidate with enough metadata to reproduce failure analysis.
- Do not silently weaken validation to improve yield; add explicit ablations if a check is optional.

## Research Framing

The core contribution is an enterprise benchmark-generation pipeline, not another static Text2Cypher dataset. The paper should emphasize:

- private enterprise schemas and values;
- repeatable benchmark refresh as graphs evolve;
- constrained Cypher generation and repair;
- automated quality gates with judge calibration;
- balanced difficulty and workload diversity;
- reproducible local-model operation.

## Compute Notes

Known `ds-serv6` snapshot from June 1, 2026:

- 8 x NVIDIA RTX A5000, 24 GB VRAM each.
- GPUs 2 and 3 were idle at inspection time.
- `/data` had about 1.1 TB free and was 98% used.
- `/` had about 11 TB free.

Use staged storage under `/` unless `/data` has been cleaned. Run long jobs in `tmux`; log `git rev-parse HEAD`, model IDs, GPU allocation, commands, and output directories.
