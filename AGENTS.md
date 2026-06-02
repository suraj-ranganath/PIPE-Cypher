# PIPE-Cypher Agent Instructions

PIPE-Cypher is an industry-track research codebase for automatic benchmark generation for natural-language-to-Cypher systems over enterprise property graphs.

## Non-Negotiable Project Constraints

- Use Cypher/property-graph language in the paper and docs. Neo4j is the experimental backend, not the conceptual contribution.
- Do not use paid generation APIs for dataset generation. Use local models on `suraj@ds-serv6.ucsd.edu`.
- Reported generation/judge model: `Qwen/Qwen3.5-9B` served locally with vLLM or another local OpenAI-compatible endpoint. Do not frame the 9B study as fallback evidence or make the inability to run larger models a manuscript limitation unless the project owner explicitly reopens that comparison.
- For Qwen/vLLM, keep reasoning traces out of generated artifacts: use `reasoning_effort=none`, `include_reasoning=false`, `chat_template_kwargs.enable_thinking=false`, and strip residual `</think>` preambles before JSON parsing.
- Default embedding model: BGE-M3 or another local embedding model.
- Primary graph workload: LDBC FinBench, because it targets financial fraud and risk-control scenarios. Secondary generality workload: LDBC SNB.
- Third-graph onboarding candidate: ICIJ Offshore Leaks. It is a public finance/compliance property graph with a downloadable Neo4j dump and CSV package, and should be used to test arbitrary-schema onboarding beyond LDBC. Do not promote ICIJ numbers into the paper until the graph is loaded live, the run is complete, and the same paper-readiness audit standards are met.
- The pipeline must support arbitrary enterprise property-graph onboarding beyond FinBench/SNB. FinBench and SNB are study workloads, not hard-coded assumptions.
- Preserve the private cypher example reference as a first-class design source. Reuse its ideas for constrained prompting, relationship direction discipline, read-only query safety, `RETURN DISTINCT`, exact matching for quoted values, required contextual return columns, synonym normalization, categorical-property constraints, and post-generation rewrites.
- Treat the cypher example reference parser/listener and query-alteration design as an innovation source, not just an implementation detail. When practical, prefer grammar/AST-aware validation and conservative rewrites over brittle string edits; when parser risk is high, skip rewrites and log why.
- Human review is not a generation gate. Use deterministic validation plus LLM-judge review. A small human audit may be used only to calibrate judge reliability for the paper.
- Large-scale evaluation is a core requirement. Keep target-100, repeated target-50-or-larger, full held-out downstream, and graph/category/difficulty-stratified runs moving when `ds-serv6` has capacity; do not stop because a smaller suite already passed.
- Latest owner directive: do more large-scale evaluation and ablations whenever feasible, because reviewer confidence depends on scale, repeated evidence, and reliable slice-level results. Keep queueing or launching defensible scale increments while compute is available.

## Engineering Rules

- Keep the pipeline runnable without GPU access for deterministic tests.
- Treat generated Cypher as unsafe until it passes read-only, schema, syntax, execution, and judge checks.
- Prefer schema-derived constraints over prompt-only instructions.
- Provide configurable privacy redaction and value-sampling policies for enterprise users. Raw internal artifacts may contain schema names, values, questions, Cypher literals, and result samples; anything intended for broad review, appendix material, or external sharing must either be sanitized or clearly marked as private/internal.
- Treat low-cardinality value sampling as potentially sensitive. Bound sampled value length and omit free-text/sensitive properties such as notes, comments, and addresses unless the owner explicitly enables them.
- Preserve exact values inside Cypher string literals during normalization and rewriting. Do not collapse, trim, or otherwise alter whitespace inside quoted literals. Slot grounding should reject hidden-control or leading/trailing-whitespace values unless an explicit value-normalization policy is being evaluated.
- Log every accepted and rejected candidate with enough metadata to reproduce failure analysis.
- Do not silently weaken validation to improve yield; add explicit ablations if a check is optional.
- Measure benchmark diversity explicitly. Report lexical diversity, query-template/signature diversity, schema coverage, structural feature coverage, difficulty balance, and graph/category balance.
- When adding Cypher transformations, prefer parser/listener/token-span logic where practical. String rewrites must be conservative, covered by tests, and logged with before/after Cypher plus the reason for applying or skipping the rewrite.
- Preserve deterministic tests for the AST, validator, diversity, judge, and reporting layers. GPU-dependent behavior should have smokeable local stubs or fixtures.
- Before launching long YAML-driven GPU jobs, run strict config validation. Unknown or misspelled config keys must be treated as launch blockers, because silent YAML mistakes can invalidate multi-hour ablations.

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
- Enterprise deployment story: maintain a clean guide for connecting a company's own graph, read-only credentials, schema introspection, local model endpoint, privacy/value policy, dry run, scaled run, audit, and redacted export.
- Benchmark-factory reliability inspired by YourBench: strict config validation, pre-run capacity/token/request estimation, stage-level inference accounting, benchmark-card generation, provenance-rich exports, and schema-validated benchmark rows. Adapt these ideas to property-graph execution; do not copy document-ingestion or citation-QA mechanics directly.

Each novelty claim in the paper should map to code, an ablation, a table/figure, or a documented blocked experiment.

## YourBench Transfer Mandate

Treat `huggingface/yourbench` as a useful reference for dynamic benchmark-generation operations, not for Cypher methodology. Its transferable strengths are strict YAML validation, explicit pipeline stages, estimate-before-run tooling, multi-model stage assignment, custom output schemas, quality filtering, dataset-card/export discipline, and provenance-heavy logs. Record adaptations in `knowledge_base/yourbench_transfer_notes.md`.

High-value adaptations for PIPE-Cypher:

- fail fast on unknown config keys before expensive `ds-serv6` jobs;
- estimate candidate attempts, generation calls, judge calls, prompt/token load, endpoint usage, and expected wall-clock before target-50, target-100, or full runs;
- keep stage-level ledgers with request IDs, retries, model IDs, run IDs, graph backend, code revision, latency, and token/use counts when available;
- generate redacted benchmark cards with graph profile, schema fingerprint, privacy/value policy, model endpoint, quality-gate rates, diversity metrics, judge calibration, and intended evaluation protocol;
- validate accepted-example and export rows against a stable schema contract;
- adapt single-hop/multi-hop/cross-document thinking into single-relation, multi-hop, cross-neighborhood, temporal-path, negation, and ranking query sampling;
- consider graph-grounding diagnostics analogous to citation support: literal-result overlap, return-context coverage, schema-mention coverage, and value-placeholder coverage.

Do not make Hugging Face Hub upload, paid APIs, document summarization, or text citation scoring core PIPE-Cypher defaults. Enterprise deployments should default to local models, local artifacts, read-only graph credentials, and redacted exports.

## Mind The Query Transfer Mandate

Treat Mind the Query (Chauhan et al., EMNLP Industry 2025) as the closest venue-aligned Text2Cypher dataset/pipeline reference. Use it as a reviewer-facing checklist, not as a design to copy. Keep the analysis note in `knowledge_base/mind_the_query_analysis.md` current when borrowing ideas.

High-value ideas to adapt:

- report graph statistics and category distributions with enough detail for grounded execution;
- keep a category crosswalk against SR/CR/SA/CA/EQ while emphasizing PIPE-Cypher's additional enterprise categories: boolean existence, negation/difference, path/temporal transaction, and ranking/top-k;
- report a validator cascade analogous to schema/runtime/value validation, expanded with read-only safety, direction validation, categorical values, execution, non-empty checks, repair/rewrite, and LLM-judge review;
- run a prompt-factorial ablation inspired by their zero-shot/few-shot/instruction/few-shot-plus-instruction study, using `schema_only`, `instructions_only`, `examples_only`, `examples_plus_instructions`, and `full_pipe_cypher_governed`;
- report downstream zero-shot vs retrieval few-shot evaluation on the same held-out split when a complete, audited run is available;
- include an effort/automation comparison that makes PIPE-Cypher's local-model automation and calibration-only human audit concrete;
- include failure examples and empty-result diagnostics that explain structure hallucination, unsupported Cypher functions, over-restrictive predicates, literal misses, and empty-but-logically-plausible queries.

Do not copy Mind the Query's Gemini/manual-review setup. PIPE-Cypher must remain local-model, privacy-aware, AST/governance-oriented, and automated-judge-first. Do not commit full PDF text or page screenshots; commit only sanitized analysis, tables, and comparisons.

## Cypher Example Reference Design Mining Mandate

Treat the private cypher example reference archive as a primary design source. Re-inspect it before major Cypher changes and record transferable ideas in `knowledge_base/cypher_example_reference_design_notes.md`.

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
- arbitrary enterprise schema onboarding beyond the two LDBC study workloads;
- additional public enterprise-style graph onboarding evidence, especially ICIJ Offshore Leaks for finance/compliance, when completed under research-quality audit rules;
- repeatable benchmark refresh as graphs evolve;
- configurable privacy redaction and value-sampling policies;
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
- Do not put smoke-run or engineering sanity-check evidence into paper tables, figures, or appendix result sections. Every reported result must come from a completed, audited, research-quality run with enough scale for reviewer scrutiny.
- Keep `tests/test_paper_reporting_guards.py` green. It prevents smoke, mini, midscale, target-five, and target-25 diagnostic artifacts from reappearing in manuscript, table, appendix, or paper-figure surfaces.
- Every experiment reported in the paper or appendix must be research-quality and reviewer-defensible: scaled enough to be reliable, run on the intended live graph workloads, backed by explicit configs/run directories/logs/model IDs/commit or code revision, and accompanied by failure analysis rather than only cherry-picked successes.
- Treat target-five or similarly tiny ablations as engineering sanity checks unless explicitly framed outside the paper. Publishable ablation claims should come from larger target-per-category runs, preferably on both FinBench and SNB when the claim is not graph-specific.
- Prefer large-scale evaluation whenever compute permits. Use target-25 only as an interim ablation checkpoint; for final paper claims, push toward larger target-per-category ablations, the full 3,000-example benchmark or larger refreshed exports, full held-out downstream evaluation, and repeated or graph-stratified runs that make variance and reliability clear to reviewers.
- Scale is part of the contribution, not a nice-to-have. Reviewer-facing claims should report enough examples, graph cells, category cells, and downstream evaluation cases that the result would remain persuasive under skeptical review. When compute allows, prefer target-100 ablation cells or repeated target-50 runs over a single barely complete target-50 suite.
- The project owner explicitly wants more large-scale evaluation and ablations, not merely a minimally complete paper. While the goal is active, keep using available `ds-serv6` capacity to finish, repeat, or broaden research-quality runs that strengthen reviewer confidence.
- Continue pursuing larger evaluation and ablation runs while compute is available. Do not stop at the first complete suite if a target-100, repeated target-50, larger refreshed export, or broader downstream-model evaluation is feasible within `ds-serv6` constraints.
- Report uncertainty where possible: repeated seeds, bootstrap confidence intervals, paired comparisons on the same held-out examples, per-graph/per-category/per-difficulty variance, or clear sensitivity analyses. If a run is too expensive to repeat, say so explicitly and avoid treating a single aggregate as settled fact.
- Do not overclaim from partial-run evidence. The manuscript's local-model study should report Qwen3.5-9B as the standard deployed endpoint for this paper, not as a fallback from an unavailable larger model.
- Keep main-paper claims compact and evidence-backed. Use the appendix aggressively for scaled experiment matrices, ablation plots, judge calibration, failure taxonomy, qualitative examples, prompt variants, parser/rewrite case studies, downstream per-difficulty breakdowns, and graph-specific details.
- The paper should compare or position against verified prior work such as Text-to-Cypher benchmarks, SyntheT2C, Spider 2.0, BIRD, AutoQuery-style generation pipelines, LDBC FinBench, LDBC SNB, and relevant Text-to-SQL synthetic benchmark methods found during literature review.
- Report metrics that reviewers can audit: generation yield, syntax validity, schema validity, read-only safety, execution success, non-empty result rate, repair success, judge pass rate, judge-human agreement, diversity metrics, difficulty balance, downstream execution accuracy, answer F1, parse validity, schema validity, and per-category/per-difficulty performance.
- Every figure and table should answer a paper question: why the benchmark matters, what the pipeline changes, which gates improve quality, how diversity/difficulty are controlled, where failures occur, and whether downstream evaluation becomes more discriminative.
- The completed 80-row human judge audit from June 2026 is usable calibration evidence: report the filled-audit agreement metrics only from sanitized summaries, not raw value-bearing CSV rows. The observed judge behavior is precision-oriented: 80.0% agreement, Cohen's kappa 0.60, judge precision/specificity 1.00, judge recall 0.714, and zero false accepts in the labeled sample. Frame this as a conservative generation gate that protects accepted benchmark quality while reducing yield.

## Large-Scale Experiment Standard

- Current owner directive: keep running larger evaluation and ablation jobs while `ds-serv6` capacity permits. The paper should not read like a small prototype; it should report research-quality, scaled, reviewer-defensible results with enough examples, ablation cells, repeated seeds, downstream cases, and slice-level analyses to make the conclusions reliable.
- Bias toward larger runs whenever compute is available. The reviewer-facing study should use the full 3,000-example benchmark, both FinBench and SNB, target-50-or-larger ablation cells at minimum, downstream test evaluation over the full held-out split, judge calibration, and graph/category/difficulty stratification.
- Treat target-25 ablations as interim scaled checkpoints and target-five runs as engineering checks. They can guide implementation, debugging, and appendix planning, but they must not anchor paper claims.
- For final ablation claims, prefer target-100 per category, repeated target-50 suites, or another scale-equivalent design when `ds-serv6` capacity allows. If the project stops at target-50 because of real compute, storage, or time limits, document that constraint and avoid overstating fine-grained differences.
- Large-scale evaluation is required for reviewer credibility, not optional polish. Keep pushing beyond the first successful run while compute is available: finish queued target-100 ablations, add repeated seeds when runtime permits, and prefer broader downstream-model evaluation over narrow proof-of-concept reporting.
- Do not treat a first passing ablation suite as the end state. The default research posture is to continue scaling evaluation and ablations until the evidence is reliable enough for skeptical EMNLP Industry reviewers: complete target-100 cells, repeated target-50 or larger seeds, full held-out downstream evaluation, and appendix-level variance/sensitivity reporting whenever `ds-serv6` capacity permits.
- Research-quality scale means more than a high accepted-example count. For ablations and downstream evaluation, require complete planned cells, both intended graphs when relevant, category/difficulty coverage, explicit seeds or target sizes, run logs, model IDs, graph backend identifiers, code revisions, readiness audits, and visible failure analysis before any result is promoted into the manuscript or appendix.
- Reported paper results should be convincing under skeptical review: enough examples per graph, variant, category, and difficulty bucket to make trends stable; enough held-out downstream cases to support per-slice analysis; and enough repeated or stratified evidence to distinguish real effects from run noise.
- Downstream Text2Cypher evaluation should use the complete held-out benchmark split unless a model/backend failure makes that impossible. Sampled or partial downstream runs are development diagnostics, not paper results, unless the sampling plan is preregistered in the docs and justified by compute limits.
- If a scaled run is still active, monitor it and prepare collection/audit tooling rather than copying partial outputs into the manuscript. When it completes, immediately fetch artifacts, run readiness audits, update the claim/evidence map, and then decide whether an additional target-100, repeated target-50, or extra downstream-model run is needed for reviewer confidence.
- During goal-mode work, keep one eye on the remote experiment queue. If `ds-serv6` has available capacity and a larger ablation, repeated seed, refreshed benchmark export, or downstream evaluation can run without disrupting active jobs, prefer launching or queueing it over stopping after local-only progress.
- For every reported ablation, keep both yield and quality-gate reporting: accepted examples, generated records, acceptance rate, categories at target, read-only rate, syntax-valid rate, schema-valid rate, execution-success rate, judge-pass rate, failure taxonomy, and diversity diagnostics where relevant.
- Track every large run in a status document with planned cells, completed cells, missing cells, exact commands, code revision, model IDs, graph backend, run paths, logs, checksums for copied artifacts, and known deviations. Do not cherry-pick successful cells while omitting failed or incomplete cells.
- For repeated large-scale runs, set and record an explicit run seed in commands, summaries, manifests, and status notes. Repeated-seed evidence is stronger than uncontrolled reruns and should be used for variance or sensitivity claims.
- Prefer scale increments that answer reviewer questions: target-100 ablation cells for stability, repeated target-50-or-larger seeds for variance, additional downstream-model runs for discriminative utility, and per-slice reporting for graph/category/difficulty robustness. Queue the next defensible increment when GPUs are free rather than waiting until the paper-writing phase.
- Before rendering ablation tables or figures for the manuscript, run the paper-readiness audit in `scripts/summarize_live_ablation_suite.py`; the default standard is target-50 or larger, complete graph/variant cells, complete metadata, category-target coverage, run summaries, and core gate-rate availability.
- Prefer repeated, graph-stratified, or category-stratified analyses over single aggregate numbers. Main-paper tables may be compact, but appendix material should include the full matrix, per-graph/per-category breakdowns, and enough uncertainty or variance evidence to satisfy skeptical reviewers.
- Large appendix results are expected. Put full ablation matrices, repeated-run variance, confidence intervals, diversity distributions, failure taxonomies, judge-human agreement, downstream per-difficulty slices, and representative examples in the appendix even when the main six-page body can only summarize the headline.
- Do not promote a running, partially summarized, or under-audited suite into the paper. Only report results after the summary artifacts, logs, model IDs, graph workloads, code revision, readiness audit, and failure analysis have been checked into the evidence map or documented as externally stored large artifacts.
- Large-scale follow-up work is part of the research obligation, not an optional cleanup pass. While the goal remains active, future agents should keep monitoring queued `ds-serv6` experiments, collect only completed suites, and prefer launching the next defensible scale increment when GPUs are free.
- The appendix should make scale legible to reviewers: include the full ablation matrix, graph/category/difficulty counts, run-to-run sensitivity, uncertainty intervals, failure modes, and any excluded or failed cells with clear reasons. Do not hide weak cells by only reporting aggregate wins.
- Downstream evaluation should be treated as a full-benchmark reliability study. When additional models or larger local-model endpoints become feasible, run them on the complete held-out split and report paired, slice-aware comparisons instead of isolated sample results.

## Compute Notes

Known `ds-serv6` snapshot from June 1, 2026:

- 8 x NVIDIA RTX A5000, 24 GB VRAM each.
- GPUs 2 and 3 were idle at inspection time.
- `/data` had about 1.1 TB free and was 98% used.
- `/` had about 11 TB free.

Use staged storage under `/` unless `/data` has been cleaned. Run long jobs in `tmux`; log `git rev-parse HEAD`, model IDs, GPU allocation, commands, and output directories.

For research-scale runs, do not default to a single serial endpoint when clean GPU capacity is available. Start independent local vLLM/OpenAI-compatible endpoints on genuinely free GPUs, assign non-overlapping run prefixes or graph/variant cells to each endpoint via `PIPE_CYPHER_LLM_BASE_URL`, and summarize only completed, non-duplicated cells. Do not commandeer GPUs that have another user's resident processes or reserved VRAM without explicit owner approval; low utilization is not the same as free capacity.
