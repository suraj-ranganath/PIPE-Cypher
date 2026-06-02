# Mind The Query Analysis For PIPE-Cypher

Source: ACL Anthology entry and PDF for **Mind the Query: A Benchmark Dataset towards Text2Cypher Task** by Chauhan et al., EMNLP Industry 2025: https://aclanthology.org/2025.emnlp-industry.133/. The released code/data repository is https://github.com/endeavorXx/Mind-the-Query.

This note intentionally does not store full PDF text or page screenshots. Local analysis caches were kept outside the repo under `/tmp`.

## Why It Matters

Mind the Query is a close venue and track reference for PIPE-Cypher: it was published in the EMNLP Industry Track, studies Text2Cypher, and uses a generation-plus-validation pipeline rather than only downstream model evaluation. The ACL page verifies the core artifact: 27,529 NL-Cypher pairs across 11 graph datasets, grounded graph databases, automated schema/runtime/value checks, manual logical review, and complexity-aware categories.

PIPE-Cypher should use it as the strongest static-dataset and industry-track comparison point, while clearly differentiating our contribution: private enterprise benchmark generation, local model operation, configurable privacy/value policies, AST-aware Cypher governance, automated judge review with post-hoc calibration, benchmark refresh, and deployment on an organization's own graph.

## Page-By-Page Structure Notes

| PDF pages | Content | Lesson for PIPE-Cypher |
| --- | --- | --- |
| 1-2 | Motivation, limitations of existing Text2Cypher resources, contributions, task definition. | Start with the enterprise benchmark gap, not just Text2Cypher difficulty. Make the contribution list concrete and reviewer-auditable. |
| 2-3 | Pipeline figure and query categories. | Keep Figure 1 simple, but make ours more specific: privacy/value policy, reverse grounding, AST governance, execution diagnostics, judge calibration, and export/refresh. |
| 3 | Knowledge-graph setup and few-shot/cross-few-shot curation. | Add graph-statistics and schema-profile appendix tables. Emphasize arbitrary schema onboarding rather than hard-coded public datasets. |
| 3-4 | Prompt refinement and four prompt settings: zero-shot, zero-shot+instruction, few-shot, few-shot+instruction. | Add prompt profiles and a target-50+ prompt-factorial ablation modeled on this analysis. |
| 4-5 | Schema/runtime/value validation and manual logical verification. | Report our validator cascade and judge-human calibration. Frame human labels as calibration only, not a generation gate. |
| 5 | Failure examples for aggregation hallucination, structure hallucination, and void results. | Add empty-result diagnostics and a Cypher-governance failure taxonomy. Examples should explain production failure modes, not just counts. |
| 5-7 | Dataset split, downstream model evaluation, execution accuracy tables, prompt-refinement table, effort estimate. | Mirror downstream zero-shot/few-shot evaluation on the same held-out split. Add an effort/automation table contrasting manual review burden with local automated generation and calibration. |
| 7-8 | Related work, conclusion, limitations. | Keep related work compact in the main body; move detailed comparison and prompt variants to appendix. |
| 8-16 | Appendices: category descriptions, graph statistics, annotation protocol, validator performance, examples, prompts, prompt refinement. | Use our unlimited appendix aggressively for graph stats, category crosswalk, prompt contracts, validation cascade, failure taxonomy, and deployment details. |

## What To Borrow

| Mind the Query idea | PIPE-Cypher adaptation |
| --- | --- |
| Graph databases are available for grounded execution. | Report FinBench/SNB as live execution workloads and keep ICIJ as onboarding-only until fully audited. |
| Query categories SR/CR/SA/CA/EQ. | Keep our eight categories but add a crosswalk showing how boolean, negation, path/temporal, and ranking extend the familiar categories. |
| Validator cascade: schema, runtime, value. | Report read-only, syntax, schema/direction/property, categorical/value, execution, non-empty, and judge gates. |
| Prompt variants and prompt-refinement table. | Add `schema_only`, `instructions_only`, `examples_only`, `examples_plus_instructions`, and `full_pipe_cypher_governed` prompt profiles. |
| Failure examples with human reasons. | Add empty-result diagnostics and governance/failure examples from accepted/rejected records after sanitization. |
| Downstream zero-shot/few-shot and fine-tuned evaluation. | Run zero-shot and retrieval few-shot on the same held-out split first; fine-tuning is optional only if compute permits and should not distract from benchmark generation. |
| Effort estimate. | Report automation/deployment effort and human-audit reduction, not a large manual-review process. |
| Large appendix. | Put complete prompt contracts, graph statistics, validator tables, ablations, uncertainty, and examples in the appendix. |

## What Not To Copy

| Mind the Query design | Why PIPE-Cypher should differ |
| --- | --- |
| Public static benchmark as primary artifact. | Our industry contribution is a repeatable private benchmark-generation pipeline. |
| Gemini-based generation. | Project constraints require local generation and judging, reported as Qwen/Qwen3.5-9B. |
| Human review as final dataset gate. | Human labels should calibrate the judge, not gate generation. This is central to enterprise scalability. |
| Regex-only schema parsing. | PIPE-Cypher should keep moving toward parser/AST-aware validation and conservative rewrites. |
| Reporting only execution accuracy downstream. | We should report execution accuracy, answer F1, parse/schema validity, execution success, uncertainty, and failure taxonomy. |
| Treating empty results mainly as a limitation. | Add diagnostics that classify likely empty-result causes and make this a pipeline improvement. |

## Comparison Table

| Dimension | Mind the Query | PIPE-Cypher target |
| --- | --- | --- |
| Primary artifact | Public multi-domain Text2Cypher dataset | Private enterprise benchmark factory |
| Graphs | 11 public graph examples | FinBench, SNB, and audited third-graph onboarding evidence |
| Generation model | Gemini Flash 2.0 | Local Qwen/Qwen3.5-9B endpoint |
| Validation | Dedup, schema, runtime, value, manual logical review | Dedup/diversity, read-only, parser/schema/direction/value, execution, repair, judge |
| Human role | Dataset validation gate | Post-hoc judge calibration and failure analysis |
| Prompt analysis | ZS/FS/instruction/few-shot+instruction | Same factorial profile plus governed PIPE-Cypher |
| Privacy | Public data | Configurable value sampling and redacted exports |
| Refresh | Dataset release | Regenerate as schema and graph values evolve |
| Industry story | Broad Text2Cypher coverage | Deployable private benchmark generation inside enterprise compute |

## Implementation Checklist

- Add prompt-profile configs and tests.
- Add prompt-factorial ablation variants and a launch wrapper.
- Add empty-result diagnostic module and tests.
- Add downstream zero/few-shot evaluation wrapper.
- Add appendix tables: graph statistics, category crosswalk, validator cascade, prompt-refinement plan, effort/automation.
- Add pipeline overview figure.
- Update `AGENTS.md` so future agents treat Mind the Query as required venue-aligned inspiration.
- Do not report prompt-factorial results until target-50-or-larger runs complete and pass readiness audit.
