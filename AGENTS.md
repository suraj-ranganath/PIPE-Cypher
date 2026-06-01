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
- Treat BalkanID's parser/listener and query-alteration design as an innovation source, not just an implementation detail. When practical, prefer grammar/AST-aware validation and conservative rewrites over brittle string edits; when parser risk is high, skip rewrites and log why.
- Human review is not a generation gate. Use deterministic validation plus LLM-judge review. A small human audit may be used only to calibrate judge reliability for the paper.

## Engineering Rules

- Keep the pipeline runnable without GPU access for deterministic tests.
- Treat generated Cypher as unsafe until it passes read-only, schema, syntax, execution, and judge checks.
- Prefer schema-derived constraints over prompt-only instructions.
- Log every accepted and rejected candidate with enough metadata to reproduce failure analysis.
- Do not silently weaken validation to improve yield; add explicit ablations if a check is optional.
- Measure benchmark diversity explicitly. Report lexical diversity, query-template/signature diversity, schema coverage, structural feature coverage, difficulty balance, and graph/category balance.
- When adding Cypher transformations, prefer parser/listener/token-span logic where practical. String rewrites must be conservative, covered by tests, and logged with before/after Cypher plus the reason for applying or skipping the rewrite.
- Preserve deterministic tests for the AST, validator, diversity, judge, and reporting layers. GPU-dependent behavior should have smokeable local stubs or fixtures.

## Required Research Skills And Workflow

- Use `ml-paper-writing` whenever drafting, restructuring, or auditing the paper. Keep a one-sentence contribution, a coherent narrative, a strong Figure 1, and a reviewer-facing claim/evidence map.
- Use `literature-review` for state-of-the-art synthesis and gap analysis across Text-to-Cypher, Text-to-SQL, query benchmark generation, synthetic data generation, LLM-as-judge evaluation, and enterprise graph benchmarks.
- Use `citation-management` or equivalent verified-citation tooling for BibTeX. Never invent citations; mark unverifiable references as placeholders with explicit TODOs.
- Use `scientific-critical-thinking` or equivalent reasoning when deciding claims, threats to validity, judge calibration, diversity metrics, and ablation design.
- Use `scientific-schematics` or publication plotting scripts for paper figures. Figures should share a consistent visual theme, use accessible palettes, render as vector PDFs where possible, and have captions that state the takeaway rather than merely naming the plot.
- Favor concrete artifacts over narration: code, tests, run scripts, logs, paper tables, figures, and reproducibility notes should be updated as evidence changes.

## Novelty And Method Targets

PIPE-Cypher should make a defensible research contribution beyond porting PIPE-KG to Cypher. Prioritize implementable novelty that improves practical benchmark generation:

- Cypher governance layer: read-only safety, schema validation, relationship-direction validation, categorical-value validation, contextual return-column requirements, and parser-aware rewrites.
- AST-aware generation repair: extract Cypher structure, features, return columns, variables, labels, relationship types, properties, predicates, aggregation, ordering, path patterns, and risky constructs from parser output when possible.
- Enterprise value grounding: fuzzy entity/value annotation, synonym normalization, exact matching for quoted values, placeholder-based retrieval examples, and value overuse controls.
- Diversity and difficulty control: balanced category sampling, structural feature coverage, template/signature diversity, schema coverage, value/entity coverage, lexical diversity, self-similarity diagnostics, and per-difficulty downstream evaluation.
- Automated quality gates: deterministic validators plus local LLM judge, with a post-hoc human audit only for judge calibration and failure analysis.
- Benchmark refresh story: show how an enterprise can regenerate or update a private benchmark as schemas, categorical values, and graph contents evolve.

Each novelty claim in the paper should map to code, an ablation, a table/figure, or a documented blocked experiment.

## BalkanID Design Mining Mandate

Treat `/Users/suraj/Documents/Archive/BalkanID/Dev/copilot-api` as a primary design source. Re-inspect it before major Cypher changes and record transferable ideas in `knowledge_base/balkanid_cypher_design_notes.md`.

High-value ideas to adapt where practical:

- ANTLR grammar/parser/listener flow from `modules/llm_manager/cypher_parser/`, `alter_cypher_query.py`, and `cypher_listener_helpers.py`.
- Conservative alteration policy: skip rewrites for reserved variable names, `CASE`, `UNION`, `CALL`, `WHERE EXISTS`, `WHERE NOT EXISTS`, `UNWIND`, multiple `WHERE` clauses, or any parser-risky construct unless tests prove the rewrite is safe.
- Listener-style extraction of return columns, projection aliases, variable-to-label mappings, MATCH patterns, WHERE clauses, ORDER BY, SKIP, LIMIT, aggregation, and optional-match opportunities.
- Rewrite/normalization ideas: add `RETURN DISTINCT`, normalize function formatting, canonicalize contextual return columns, expand required optional matches only when semantically safe, and preserve ordering/limits.
- Prompt rules: schema-only generation, forward relationship direction, exact matching for quoted values, no explanations, no newlines when required by downstream parsing, categorical-property constraints, required co-returned context columns, and domain synonym normalization.
- Fuzzy/value grounding from `modules/fuzzy_manager/`: graph-derived entity lists, preprocessing, abbreviation replacement, omit lists, typo correction, n-gram matching, typed annotations, and placeholder replacement so retrieval examples do not leak tenant-specific values.
- Auditability: every generated, repaired, rewritten, skipped, accepted, and rejected query should carry enough metadata to reproduce the decision.

## Research Framing

The core contribution is an enterprise benchmark-generation pipeline, not another static Text2Cypher dataset. The paper should emphasize:

- private enterprise schemas and values;
- repeatable benchmark refresh as graphs evolve;
- constrained Cypher generation and repair;
- automated quality gates with judge calibration;
- balanced difficulty and workload diversity;
- ablations with appendix-ready tables and figures;
- diversity metrics grounded in prior text-generation and text-to-query evaluation practice;
- reproducible local-model operation.

The main paper should stay tight, but the appendix can be long. Use the appendix for full ablation tables, plots, diversity diagnostics, graph/category breakdowns, run commands, extra examples, and details that are too large for the counted six-page EMNLP Industry main body.

## Paper And Reporting Standards

- Target EMNLP Industry Track first and maintain an arXiv-ready extended version in parallel.
- EMNLP 2026 Industry Track page accounting: the counted main paper is at most 6 pages, and the `Conclusion` must end by the end of page 6. The `Limitations` section, ethical considerations, references, acknowledgements in the final version, and appendices do not count toward this limit.
- Keep a dedicated section titled `Limitations` before references; papers without it can be desk rejected. Put appendices after the bibliography, and use them heavily but only for material that supports the main paper.
- Do not report smoke tests, tiny probes, or engineering-only checks as paper evidence. Smoke and mini runs are useful for development logs and reproducibility notes, but not for main-paper or appendix result tables/figures.
- Every experiment reported in the paper or appendix must be research-quality and reviewer-defensible: scaled enough to be reliable, run on the intended live graph workloads, backed by explicit configs/run directories/logs/model IDs/commit or code revision, and accompanied by failure analysis rather than only cherry-picked successes.
- Treat target-five or similarly tiny ablations as engineering sanity checks unless explicitly framed outside the paper. Publishable ablation claims should come from larger target-per-category runs, preferably on both FinBench and SNB when the claim is not graph-specific.
- Prefer large-scale evaluation whenever compute permits. Use target-25 only as an interim ablation checkpoint; for final paper claims, push toward larger target-per-category ablations, the full 3,000-example benchmark, full held-out downstream evaluation, and repeated or graph-stratified runs that make variance and reliability clear to reviewers.
- Do not overclaim from fallback-model or partial-run evidence. If Qwen3.5-35B-A3B cannot be served, state that explicitly and report Qwen3.5-9B results as a documented local-model fallback rather than as the intended strongest configuration.
- Keep main-paper claims compact and evidence-backed. Use the appendix aggressively for scaled experiment matrices, ablation plots, judge calibration, failure taxonomy, qualitative examples, prompt variants, parser/rewrite case studies, downstream per-difficulty breakdowns, and graph-specific details.
- The paper should compare or position against verified prior work such as Text-to-Cypher benchmarks, SyntheT2C, Spider 2.0, BIRD, AutoQuery-style generation pipelines, LDBC FinBench, LDBC SNB, and relevant Text-to-SQL synthetic benchmark methods found during literature review.
- Report metrics that reviewers can audit: generation yield, syntax validity, schema validity, read-only safety, execution success, non-empty result rate, repair success, judge pass rate, judge-human agreement, diversity metrics, difficulty balance, downstream execution accuracy, answer F1, parse validity, schema validity, and per-category/per-difficulty performance.
- Every figure and table should answer a paper question: why the benchmark matters, what the pipeline changes, which gates improve quality, how diversity/difficulty are controlled, where failures occur, and whether downstream evaluation becomes more discriminative.

## Compute Notes

Known `ds-serv6` snapshot from June 1, 2026:

- 8 x NVIDIA RTX A5000, 24 GB VRAM each.
- GPUs 2 and 3 were idle at inspection time.
- `/data` had about 1.1 TB free and was 98% used.
- `/` had about 11 TB free.

Use staged storage under `/` unless `/data` has been cleaned. Run long jobs in `tmux`; log `git rev-parse HEAD`, model IDs, GPU allocation, commands, and output directories.
