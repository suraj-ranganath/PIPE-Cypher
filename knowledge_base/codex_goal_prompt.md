# Codex Goal Prompt

Source consulted: <https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex>

Use this with `/goal` when restarting or continuing the project in a fresh Codex thread.

```text
Complete PIPE-Cypher as an end-to-end, evidence-backed EMNLP Industry Track research project and arXiv-ready paper, verified by concrete repository artifacts, passing tests or documented blockers, reproducible experiment scripts, generated benchmark exports or smoke-run evidence, and a serious paper draft under /Users/suraj/Desktop/PIPE-Cypher/paper_emnlp2026_industry/.

Before acting, read and follow /Users/suraj/Desktop/PIPE-Cypher/AGENTS.md. Treat it as the durable project contract for constraints, research standards, BalkanID design mining, compute rules, and paper/reporting expectations.

Objective:
Build /Users/suraj/Desktop/PIPE-Cypher as an industry-focused successor to /Users/suraj/Desktop/Archive/PIPE-KG for automatic private enterprise NL-to-Cypher benchmark generation over large property graphs. The core contribution should be a practical benchmark-generation pipeline that combines graph/value grounding, Cypher governance, parser/AST-aware validation and rewrite, diversity and difficulty control, local-model generation/judging, and calibrated automated quality gates. Preserve Cypher/property-graph framing throughout; Neo4j is only the experimental backend.

Research quality and novelty mandate:
- Use relevant skills throughout the work. Use ml-paper-writing for paper narrative, claim/evidence mapping, section drafting, and submission quality. Use literature-review for Text-to-Cypher, Text-to-SQL, benchmark generation, synthetic query generation, diversity metrics, LLM-as-judge evaluation, and enterprise graph benchmark synthesis. Use citation-management or verified citation tooling for BibTeX. Use scientific-critical-thinking for claims, ablations, threats to validity, and judge calibration. Use scientific-schematics or the repo plotting scripts for publication-quality figures.
- Do not merely port PIPE-KG. Develop and document novel, implementable contributions around Cypher governance, AST-aware query analysis, enterprise value grounding, diversity/difficulty control, automated judging, and benchmark refresh as private graphs evolve.
- Do not invent citations. Verify references from primary sources or mark them as explicit placeholders needing human verification.
- Keep one crisp contribution sentence visible in the paper work: PIPE-Cypher is a local-model, enterprise-oriented pipeline for generating diverse, executable, difficulty-controlled NL-to-Cypher benchmarks over private property graphs using schema/value grounding, parser-aware Cypher governance, and calibrated automated quality gates.

BalkanID mining mandate:
Deeply inspect and adapt implementable ideas from /Users/suraj/Documents/Archive/BalkanID/Dev/copilot-api before major Cypher work, especially:
- ANTLR grammar/parser/listener flow from modules/llm_manager/cypher_parser/, alter_cypher_query.py, and cypher_listener_helpers.py.
- Listener-style extraction of return columns, aliases, variable-to-label mappings, MATCH patterns, WHERE clauses, ORDER BY, SKIP, LIMIT, aggregation, optional-match opportunities, relationship direction, labels, properties, predicates, and risky constructs.
- Conservative rewrite policy: add RETURN DISTINCT, normalize function formatting, canonicalize contextual return columns, and apply safe rewrites only when parser evidence supports them; skip and log rewrites for risky constructs such as CASE, UNION, CALL, WHERE EXISTS, WHERE NOT EXISTS, UNWIND, multiple WHERE clauses, reserved variable names, or unsupported parser states.
- Prompt and validation rules: schema-only generation, forward relationship direction discipline, exact matching for quoted values, categorical-property constraints, required contextual return columns, no explanations in generated Cypher, read-only safety, and no schema/value leakage beyond the selected schema slice.
- Fuzzy/value grounding ideas from modules/fuzzy_manager/: graph-derived entity/value dictionaries, preprocessing, abbreviation replacement, omit lists, typo correction, n-gram matching, typed annotations, entity placeholders, and retrieval examples that reduce tenant-specific leakage and value overuse.
- Audit logs for every generated, repaired, rewritten, skipped, accepted, and rejected candidate.

Graph, model, and compute constraints:
- Use LDBC FinBench as the primary industry graph because it targets fraud/risk-control workloads, and LDBC SNB as the secondary generality graph unless loading or licensing evidence blocks that choice.
- Use only local models for benchmark generation and LLM judging. Do not use paid generation APIs.
- Target Qwen/Qwen3.5-35B-A3B served locally with vLLM for generation/judging when feasible; use Qwen/Qwen3.5-9B for smoke tests and fallback runs. Keep Qwen reasoning traces out of artifacts using reasoning_effort=none, include_reasoning=false, chat_template_kwargs.enable_thinking=false, and residual </think> stripping before JSON parsing.
- Use local embeddings such as BGE-M3 for retrieval.
- Use suraj@ds-serv6.ucsd.edu for GPU work. Run long jobs in tmux and log git commit, model IDs, GPU allocation, commands, output directories, failures, and recovery steps.

Pipeline success criteria:
1. The repo has a clean Python package, configs, scripts, tests, docs, AGENTS.md, reproducibility notes, literature notes, BalkanID design notes, graph-loading notes, experiment matrix, generated-artifact directories, and paper directory.
2. The pipeline supports schema introspection, schema/value summaries, constrained prompt generation, retrieval with placeholders, reverse Cypher grounding, deterministic validation, read-only safety checks, syntax/parser checks, schema validation, relationship-direction validation, categorical-value validation, execution validation, parser-aware repair/rewrite, diversity controls, strategy/difficulty tagging, structural feature extraction, JSONL logging, and LLM-judge review.
3. The judge gate replaces human-in-the-loop generation review. A small post-hoc human audit is used only to calibrate judge reliability and report judge-human agreement or disagreement patterns.
4. The experiment plan and scripts cover the intended 3,000-example target, FinBench/SNB split, unconstrained local generation baseline, PIPE-KG-style Cypher port baseline, deterministic validators plus repair, full PIPE-Cypher, no-retrieval/no-rewrite/no-judge ablations, Qwen3.5-9B versus Qwen3.5-35B comparison where feasible, FinBench-only versus FinBench+SNB generality, judge calibration audit, and downstream Text2Cypher evaluation.
5. Metrics include generation yield, syntax-valid rate, parser-valid rate, schema-valid rate, relationship-direction-valid rate, categorical-value-valid rate, read-only safety rate, execution success, non-empty result rate, repair/rewrite success, judge pass rate, judge-human agreement, failure taxonomy, diversity metrics, difficulty balance, downstream execution accuracy, answer F1, parse validity, schema validity, and per-category/per-difficulty breakdowns.
6. Diversity is treated as a first-class benchmark property. Measure lexical diversity, n-gram/self-similarity, query-template/signature diversity, AST/structural feature coverage, label/relationship/property coverage, entity/value coverage, graph/category balance, and difficulty balance. Use prior literature where possible; otherwise define the metric precisely and justify it.

Paper and reporting success criteria:
- Produce an EMNLP Industry main-paper draft and an arXiv-ready extended version or appendix plan. The main paper should be concise and reviewer-facing; the appendix can be extensive.
- The draft must include abstract, introduction with strong industry motivation, related work with verified citations, method, implementation details, experiments, results or clearly marked result placeholders, figures, tables, limitations, ethics, reproducibility, and references in ACL/EMNLP style.
- The paper should position PIPE-Cypher against verified prior work including Text-to-Cypher resources, SyntheT2C, Spider 2.0, BIRD, AutoQuery-style generation pipelines, LDBC FinBench, LDBC SNB, LLM-as-judge work, and relevant Text-to-SQL synthetic benchmark methods found during literature review.
- Create high-quality, thematically consistent figures and tables: system overview, gate funnel, rewrite/validation examples, diversity diagnostics, difficulty distribution, ablation acceptance, downstream performance by difficulty/category, judge calibration, failure taxonomy, graph coverage, and appendix-only extended result plots. Use accessible palettes and vector PDFs where practical.
- Every main claim should map to evidence: code/tests, experiment outputs, run logs, tables/figures, literature notes, or a clearly labeled blocker.

Iteration policy:
1. At the start of each continuation, inspect current repo state, AGENTS.md, recent commits, outstanding docs/paper TODOs, experiment outputs, running tmux jobs, and ds-serv6 availability before assuming the next step.
2. Choose the highest-leverage missing piece toward the success criteria: implementation, test, experiment, figure, paper section, citation verification, or blocker reduction.
3. Implement the next piece, run the relevant tests/smokes/builds, update documentation and paper artifacts with the new evidence, and commit/push coherent changes when useful.
4. For long experiments, launch reproducible jobs, capture logs and metadata, monitor progress, and convert outputs into tables/figures or blocker reports.
5. Keep the project practical for enterprise use: private schemas, local models, repeatable refresh, auditable quality gates, and useful downstream evaluation should stay central.

Verification surface:
Use concrete evidence before marking the goal complete: pytest results, script smoke outputs, LaTeX builds, generated PDFs, benchmark JSONL exports, diversity reports, experiment result files, judge calibration files, ds-serv6 logs, verified BibTeX, paper figures/tables, and a final claim/evidence audit against AGENTS.md and this goal.

Blocked stop condition:
Do not mark the goal complete because progress is substantial. Mark it complete only after the criteria above are satisfied and verified. If no defensible path remains because of missing credentials, unavailable models, inaccessible data, licensing blockers, broken external resources, compute/storage limits, or repeated experiment failures, stop with a precise blocker report: commands attempted, evidence gathered, current artifacts, why the blocker prevents completion, and the smallest command, credential, data access, or user input needed to proceed.
```
