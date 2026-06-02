# Codex Goal Prompt

Source consulted: <https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex>

Use this compact prompt with `/goal`. The full project contract lives in `AGENTS.md`.

```text
Complete PIPE-Cypher as an evidence-backed EMNLP Industry Track + arXiv-ready project in /Users/suraj/Desktop/PIPE-Cypher. First read/follow AGENTS.md; it is the long project contract.

Objective: build an industry successor to /Users/suraj/Desktop/Archive/PIPE-KG for automatic private-enterprise NL-to-Cypher benchmark generation over large property graphs. Preserve Cypher/property-graph framing; Neo4j is only the experimental backend. Use LDBC FinBench primary and LDBC SNB secondary unless blocked by evidence.

Novelty target: do not just port PIPE-KG. Make PIPE-Cypher a practical pipeline combining schema/value grounding, Cypher governance, parser/AST-aware validation and rewrite, fuzzy/entity placeholders, diversity+difficulty control, local-model generation/judging, and calibrated automated quality gates. Contribution: a local-model enterprise pipeline for diverse, executable, difficulty-controlled NL-to-Cypher benchmarks over private graphs.

Use relevant skills: ml-paper-writing for narrative/claim-evidence maps; literature-review and citation-management for verified related work/BibTeX; scientific-critical-thinking for claims, ablations, judge calibration; scientific-schematics or repo scripts for figures. Never invent citations.

Deeply inspect the private cypher example reference archive before major Cypher work. Adapt ANTLR/parser/listeners, return/alias/variable/MATCH/WHERE/ORDER/LIMIT extraction, risky-construct detection, read-only safety, relationship direction, RETURN DISTINCT, exact quoted matching, categorical constraints, contextual returns, rewrite/skip logs, fuzzy entity/value dictionaries, typo/abbreviation handling, typed annotations, placeholders, and retrieval examples.

Model/compute: no paid generation APIs. Use local Qwen/Qwen3.5-9B with vLLM or another local OpenAI-compatible endpoint for reported generation, judging, and downstream evaluation. Do not frame 9B as fallback evidence or make larger-model unavailability a manuscript limitation unless the owner explicitly reopens that comparison. Keep Qwen reasoning out of artifacts. Use BGE-M3/local embeddings. Use ds-serv6; run long jobs in tmux and log commit, models, GPUs, commands, outputs, failures.

Pipeline success: repo has package, configs, scripts, tests, docs, reproducibility/literature/cypher-example-reference/graph-loading notes, enterprise deployment/privacy notes, experiment matrix, artifacts, and paper dir. Pipeline supports arbitrary enterprise schema onboarding, schema introspection, configurable value sampling/redaction, schema/value summaries, constrained prompting, retrieval placeholders, reverse Cypher grounding, deterministic syntax/parser/schema/relationship/categorical/read-only/execution checks, repair/rewrite, diversity controls, difficulty tags, structural features, JSONL logs, and LLM-judge review. Human review is only post-hoc judge calibration.

Experiments/metrics: target 3,000 examples with FinBench/SNB split. Cover baselines, no-retrieval/no-rewrite/no-judge ablations, judge calibration, and downstream Text2Cypher evaluation with the reported local 9B endpoint. Report yield, validity/safety/execution/non-empty/repair/judge rates, judge-human agreement, failure taxonomy, diversity, difficulty balance, execution accuracy, answer F1, parse/schema validity, and breakdowns.

Paper success: complete serious EMNLP Industry draft plus arXiv appendix plan/draft with verified related work, method, implementation, experiments, results or explicit placeholders, limitations, ethics, reproducibility, references, and themed figures/tables. For EMNLP Industry, Conclusion must end by page 6; Limitations, ethics, references, and appendices are outside the counted limit. Appendix holds ablations, diversity diagnostics, failures, graph coverage, judge calibration, and examples.

Work loop: inspect repo state, AGENTS.md, recent commits, outputs, TODOs, tmux jobs, and ds-serv6 before assumptions. Pick highest-leverage missing piece, implement, test/smoke/build, update docs/paper with evidence, commit/push coherent changes. Do not mark complete until criteria are verified. If blocked, report commands tried, evidence, artifacts, exact blocker, and smallest next command/input needed.
```
