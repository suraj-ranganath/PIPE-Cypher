# Codex Goal Prompt

Source consulted: <https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex>

Use this with `/goal` when restarting or continuing the project in a fresh Codex thread.

```text
Complete PIPE-Cypher as an end-to-end, publishable EMNLP Industry Track research project and arXiv-ready paper.

Work in /Users/suraj/Desktop/PIPE-Cypher. Build it as an industry-focused successor to /Users/suraj/Desktop/Archive/PIPE-KG for automatic enterprise NL-to-Cypher benchmark generation. Preserve Cypher/property-graph framing throughout; Neo4j is only the experimental backend. Use LDBC FinBench as the primary industry graph and LDBC SNB as the secondary generality graph unless evidence blocks that choice. Deeply inspect and borrow implementable ideas from /Users/suraj/Documents/Archive/BalkanID/Dev/copilot-api, especially constrained Cypher prompting, exact matching, relationship-direction discipline, RETURN DISTINCT, read-only safety, categorical-property constraints, required contextual return columns, parser-aware rewrites, retrieval examples, and query alteration/normalization.

Use relevant skills throughout, especially ml-paper-writing for paper structure and citation discipline, literature-review for research synthesis, citation-management for verified BibTeX, venue-templates for EMNLP/ACL formatting, and GPU skills for ds-serv6 work. Do not invent citations; verify references through primary sources.

Core constraints:
- Use Cypher-first wording in code, docs, and paper; mention Neo4j only in experimental setup.
- Use local models for benchmark generation and judging. Do not use paid generation APIs.
- Use Qwen3.5-35B-A3B as the target generation/judge model when it can be served locally; use Qwen3.5-9B for smoke tests and fallback full runs.
- Use local embeddings such as BGE-M3 where retrieval embeddings are needed.
- Keep benchmark artifacts reproducible, executable, private-graph oriented, and useful for enterprise teams.
- Replace human-in-the-loop dataset gating with LLM-judge review, while keeping a small post-hoc human audit for judge calibration.
- Keep edits scoped, run tests/smokes, and update documentation and paper claims whenever evidence changes.

Success means:
1. The repo has a clean Python package, configs, scripts, tests, docs, AGENTS.md, experiment matrix, literature notes, graph-loading notes, and paper directory.
2. The pipeline supports schema introspection, constrained prompt generation, reverse Cypher grounding, deterministic validation, read-only safety checks, schema validation, execution validation, repair/rewrite, retrieval, diversity controls, strategy/difficulty tagging, JSONL logging, and LLM-judge review.
3. ds-serv6 setup is documented and scripted for Qwen3.5 models, BGE-M3, FinBench, SNB, Neo4j experimental backends, vLLM endpoints, monitoring, recovery, and final export.
4. The experiment plan covers the intended 3,000-example target, FinBench/SNB split, baselines, ablations, metrics, judge calibration audit, and downstream Text2Cypher evaluation.
5. The paper draft under paper_emnlp2026_industry/ is serious-submission quality: abstract, introduction, related work with verified citations, method, implementation, experiments, results, limitations, ethics, reproducibility notes, and references in ACL/EMNLP format.
6. Verification includes available unit tests, compile checks, LaTeX builds, smoke commands, generated benchmark exports, and exact logs or blocker reports for any full experiment that cannot complete.

Work loop:
1. Inspect current repo, docs, artifacts, running tmux jobs, and ds-serv6 state before making assumptions.
2. Pick the highest-leverage missing piece toward the success criteria.
3. Implement it, run the relevant tests or smoke checks, sync needed changes to ds-serv6 when appropriate, and update docs/paper with the new evidence.
4. Continue monitoring long runs and finalize exports/evaluations when they complete.
5. Do not mark the goal complete until the repository, scripts, tests, experiment documentation, generated artifacts or documented blockers, and paper draft have all been checked against the criteria above.
```
