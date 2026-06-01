# PIPE-Cypher: Automatic Enterprise Benchmark Generation for Text-to-Cypher Systems

## Abstract

Enterprises increasingly use property graphs and Cypher to analyze fraud, risk, identity, customer, and operational data. However, public Text2Cypher benchmarks rarely reflect an organization's private schema, terminology, access patterns, or query difficulty distribution. We present PIPE-Cypher, a local-model pipeline for generating organization-specific natural-language-to-Cypher benchmarks. PIPE-Cypher combines schema introspection, reverse-query grounding, constrained Cypher generation, deterministic read-only and schema validation, execution feedback, repair, diversity controls, and LLM-judge review. The system is designed for industry settings where benchmark generation must avoid paid APIs, preserve data governance, and remain repeatable as graphs evolve. In our live study, PIPE-Cypher generates a 3,000-example benchmark over LDBC FinBench and LDBC SNB with balanced categories and all accepted examples passing execution and judge gates.

## 1 Introduction

Property graphs are a practical representation for enterprise data because they encode relationships directly: account transfers, identity entitlements, access paths, customer interactions, supply-chain dependencies, and fraud rings. Cypher is widely used to query these graphs. As LLMs become interfaces for graph analytics, organizations need reliable benchmarks for natural-language-to-Cypher systems on their own schemas.

Static public benchmarks are insufficient for this setting. They cannot contain private labels, relationship types, categorical values, or domain-specific wording. They also do not track schema evolution. An enterprise benchmark generator must therefore be private, repeatable, execution-grounded, and strict about query safety.

PIPE-Cypher addresses this need. Given a property graph, it produces balanced NL-Cypher examples with execution evidence and quality metadata. The pipeline is local-model-first and uses deterministic validation plus LLM-judge review instead of human review as the main gate.

Contributions:

1. A Cypher-specific benchmark-generation pipeline for enterprise property graphs.
2. A constraint and rewrite layer inspired by production Cypher systems, including read-only safety, schema discipline, directionality, and `RETURN DISTINCT`.
3. An automated judge gate that evaluates ambiguity, semantic alignment, schema use, and difficulty.
4. A live 3,000-example benchmark artifact over LDBC FinBench and LDBC SNB with generation-quality and downstream Text2Cypher metrics.

## 2 Related Work

Text2Cypher benchmarks and synthetic datasets show growing interest in natural-language interfaces to graph databases. Recent work such as [Mind the Query](https://aclanthology.org/2025.emnlp-industry.133/), [SyntheT2C](https://aclanthology.org/2025.coling-main.46/), [Auto-Cypher](https://aclanthology.org/2025.naacl-short.53/), and [Text2Cypher](https://aclanthology.org/2025.genaik-1.11/) provides important datasets, generation methods, and verification strategies. PIPE-Cypher differs by generating private benchmarks from a target graph rather than assuming one static benchmark captures deployed use cases.

Text-to-SQL benchmarks such as [Spider 2.0](https://arxiv.org/abs/2411.07763) and [BIRD](https://arxiv.org/abs/2305.03111) motivate more realistic database tasks and execution-based evaluation. PIPE-Cypher adapts this lesson to property graphs, where relationship direction, path semantics, and graph-specific schema constraints are central.

Workload generation research, especially [CIKM AutoQuery](https://adalabucsd.github.io/papers/2024_AWESOME_CIKM.pdf), motivates separating benchmark-generation quality from model quality and reporting strategy-level coverage. PIPE-Cypher logs generation yield and failure modes by category, difficulty, and structural features. [LDBC FinBench](https://ldbcouncil.org/benchmarks/finbench/) and [LDBC SNB](https://ldbcouncil.org/post/introducing-snb-interactive-the-ldbc-social-network-benchmark-online-workload/) provide the primary and secondary graph workloads.

## 3 Method

PIPE-Cypher has five stages.

First, the system introspects the target property graph to collect labels, properties, relationship types, and observed directions. This schema summary is used both in prompts and in deterministic validation.

Second, the system generates category-specific question templates. Reverse Cypher queries ground template slots in graph-backed values, reducing unanswerable questions.

Third, a local LLM generates Cypher using a constrained prompt. The prompt enforces schema-only generation, exact matching for quoted values, forward relationship directions, read-only behavior, `RETURN DISTINCT`, and aggregation rules.

Fourth, generated Cypher passes deterministic gates: read-only safety, syntax shape, parser validation when available, label and relationship checks, direction checks, property checks, execution, and repair. For reproducible smoke and seeded full runs, PIPE-Cypher keeps a small library of workload templates with deterministic reverse-binding queries and fallback Cypher instantiated with graph-backed slot values.

Fifth, a local LLM judge reviews the question, query, schema, execution sample, and validation summary. The judge outputs strict JSON with a pass flag, ambiguity score, semantic alignment score, schema-use score, difficulty, and failure reason. The judge receives a schema slice tied to the candidate Cypher, while deterministic validation still uses the full introspected schema.

Candidate acceptance gates:

| Gate | Evidence checked | Failure mode caught |
| --- | --- | --- |
| Read-only safety | blocked Cypher write/admin tokens | destructive or operational queries |
| Schema validity | labels, relationship types, properties | hallucinated graph vocabulary |
| Direction validity | observed relationship directions | reversed or invalid traversals |
| Question constraints | quoted values use exact literals | fuzzy matching of exact user values |
| Execution | query runs and returns rows | syntactic validity without answerability |
| LLM judge | ambiguity, semantic alignment, schema use | executable but semantically weak examples |

## 4 Implementation

The implementation is a Python package with Neo4j as the experimental backend. Neo4j is used for execution and schema introspection, while the paper frames the contribution around Cypher and property graphs.

The project supports local vLLM-compatible model serving on `ds-serv6`. The target model is `Qwen/Qwen3.5-35B-A3B`; `Qwen/Qwen3.5-9B` is used for smoke tests and fallback full runs. Embeddings use local BGE-M3-style models where retrieval embeddings are needed.

The June 1, 2026 model check found `Qwen/Qwen3.5-35B-A3B` available remotely; it has since been staged under `/home/suraj/pipecypher-models/Qwen3.5-35B-A3B`. A serving-capacity check estimated that the staged weights require four A5000 GPUs under our vLLM budget, while only one GPU was safely free in the live snapshot. All live evidence in this draft therefore uses the 9B fallback.

We also estimate seed-template capacity before full generation. This check caught and fixed a scale blocker: reverse-binding execution was hard-capped to 10 rows, and no-slot negation/ranking seeds could not support full category targets. PIPE-Cypher now uses the configured binding limit and includes slotted negation and ranking seeds for both graphs.

| Graph | Target/category | Binding limit | Min seed capacity | All categories meet target |
| --- | ---: | ---: | ---: | --- |
| FinBench | 250 | 300 | 300 | Yes |
| SNB | 125 | 200 | 200 | Yes |

The deterministic Cypher layer borrows from production lessons in the BalkanID Cypher system: schema-only prompting, exact matching, relationship direction discipline, `RETURN DISTINCT`, reserved variable rejection, categorical values, required contextual return columns, and parser-aware rewrite boundaries.

For LDBC FinBench, the implementation grounds its built-in reference profile in the public snapshot export used by the datagen tooling. The profile includes typed properties and directed relationship patterns for people, companies, accounts, loans, media, transfers, withdrawals, repayments, deposits, sign-ins, investments, guarantees, account ownership, and loan applications. The Neo4j import script uses node uniqueness constraints and relationship creation rather than relationship merging so repeated transaction events between the same endpoints remain visible to generated benchmark queries. The SNB reference profile is grounded in the official Neo4j/Cypher headers and read-query files, covering people, forums, messages, tags, locations, organizations, and the standard interactive relationship patterns.

## 5 Experiments

The generated benchmark contains 3,000 accepted examples: 2,000 from LDBC FinBench and 1,000 from LDBC SNB. Examples are balanced across simple retrieval, complex retrieval, simple aggregation, complex aggregation, boolean existence, negation/difference, path/temporal transaction, and ranking/top-k categories.

Full live experimental setup:

| Setting | Value |
| --- | --- |
| Accepted examples | 3,000 |
| Primary graph | LDBC FinBench, 2,000 examples |
| Secondary graph | LDBC SNB, 1,000 examples |
| Categories | 8 balanced categories, 375 each |
| Generation/judge model | Local Qwen3.5-9B fallback |
| Execution backend | Neo4j Community, two live databases |
| Judge audit packet | 80 sampled accepted/rejected pairs |

Baselines:

- unconstrained local LLM generation;
- reverse-query-only generation;
- validators plus repair;
- full PIPE-Cypher with constrained prompts, retrieval, rewrite, execution validation, diversity control, and LLM judge.

Metrics:

- generation yield;
- syntax-valid rate;
- schema-valid rate;
- read-only safety rate;
- execution success and non-empty result rates;
- repair success and judge pass rates;
- diversity over labels, relationships, properties, entities, templates, and difficulty;
- downstream Text2Cypher execution accuracy and answer F1.

## 6 Results

The repository includes the package scaffold, validators, schema introspection, generation loop, judge interface, configs, scripts, offline smoke mode, FinBench and SNB load helpers, and live smoke paths. On June 1, 2026, we generated and loaded FinBench SF0.1 into a user-space Neo4j Community instance on `ds-serv6`, loaded the official SNB Cypher test-data into a second Neo4j instance, served Qwen3.5-9B locally with vLLM, introspected both live schemas, and ran four-category smoke benchmarks.

The full live run produced 3,000 accepted examples from 4,777 candidates using local Qwen3.5-9B for generation and judging. Category-specific recovery top-ups filled the only under-target categories from the initial sequential run. Every exported example passed read-only, syntax, schema, execution, non-empty result, and judge gates.

| Graph | Candidates | Accepted | Acceptance | Categories at target |
| --- | ---: | ---: | ---: | ---: |
| FinBench | 3,404 | 2,000 | 0.588 | 8/8 |
| SNB | 1,373 | 1,000 | 0.728 | 8/8 |
| Total | 4,777 | 3,000 | 0.628 | 16/16 |

The repository includes a judge-audit CSV sampled from full-run accepted and rejected candidates, plus a labeling protocol. The human labels are intentionally blank in the current artifact; this file is the starting point for the calibration analysis rather than a pipeline gate.

Current smoke evidence:

| Metric | Offline | Live FinBench | Live SNB |
| --- | ---: | ---: | ---: |
| Records generated | 4 | 4 | 4 |
| Accepted records | 4 | 4 | 4 |
| Read-only pass | 4 | 4 | 4 |
| Syntax-valid pass | 4 | 4 | 4 |
| Schema-valid pass | 4 | 4 | 4 |
| Execution-success pass | 4 | 4 | 4 |
| Judge pass | 4 | 4 | 4 |

The live smokes used graph-backed entity values and non-empty Neo4j execution. A broader seeded FinBench run also accepted 8/8 examples across all planned categories, with four easy and four medium examples. These smoke numbers verify end-to-end wiring but are not final experimental results.

Live mini-ablation evidence with Qwen3.5-9B:

| Run | Records | Accepted | Acceptance |
| --- | ---: | ---: | ---: |
| FinBench LLM-only probe | 16 | 0 | 0.000 |
| FinBench mixed mini | 29 | 16 | 0.552 |
| SNB mixed mini | 8 | 8 | 1.000 |

The FinBench LLM-only probe disabled deterministic seed/fallback behavior and accepted no examples; deterministic validation tagged all 16 attempts as generic unlabeled node scans. The mixed run recovered two useful benchmark candidates in every planned FinBench category, while still logging rejected Qwen-generated node scans for failure analysis.

We then ran a live mid-scale generation pass with a target of five accepted examples per category for each graph.

| Run | Records | Accepted | Acceptance | Categories at target |
| --- | ---: | ---: | ---: | ---: |
| FinBench mid-scale | 46 | 40 | 0.870 | 8/8 |
| SNB mid-scale | 47 | 40 | 0.851 | 8/8 |

The accepted full-run records were exported into a benchmark package with stable example identifiers, train/dev/test splits, result samples, gate metadata, aggregate statistics, and a manifest hash. The export contains 3,000 accepted examples: 2,000 FinBench, 1,000 SNB, and 375 accepted examples in every planned category.

| Export artifact | Examples | FinBench | SNB | Train | Dev | Test |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Live full benchmark | 3,000 | 2,000 | 1,000 | 2,408 | 296 | 296 |

Finally, we ran a downstream Text2Cypher evaluation using local Qwen3.5-9B on the exported full test split. The model saw schema text and the natural-language question, generated Cypher, and was evaluated by live execution against the corresponding FinBench or SNB database.

| Split | Examples | Parse | Schema | Exec. success | Exec. acc. | Answer F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Live full test | 296 | 0.959 | 0.905 | 0.622 | 0.189 | 0.189 |

## 7 Industry Use

PIPE-Cypher is intended to be rerun when an enterprise graph changes. The generated artifact records the schema snapshot, graph profile, model identifier, validation gates, execution samples, judge scores, difficulty features, and source run for every example. Long-running jobs can be monitored from JSONL records and recovered with category-specific top-up runs that reject questions accepted in earlier runs. This design supports private benchmark refreshes without exposing schemas or values to paid APIs, while still leaving audit hooks for data owners to sample accepted and rejected examples.

## 8 Limitations

Execution validity does not guarantee semantic correctness; this motivates the judge gate and human audit calibration. LLM judges can inherit model biases and may over-accept plausible but wrong queries. FinBench and SNB are representative benchmarks but cannot cover every enterprise graph. Local model constraints may reduce generation quality relative to paid frontier models, but they match industry governance and cost constraints.

## 9 Ethics And Governance

PIPE-Cypher is designed for private enterprise benchmark generation. Prompt logs and benchmark artifacts may contain schema details and sampled values, so organizations should apply access controls, retention policies, and redaction where needed. The pipeline rejects write/admin Cypher to reduce operational risk.

## 10 Conclusion

PIPE-Cypher provides a practical path for enterprises to create private, executable, balanced NL-to-Cypher benchmarks. By combining schema introspection, constrained generation, deterministic validation, execution feedback, diversity control, and automated judge review, it makes benchmark generation more reliable and repeatable for deployed graph analytics.
