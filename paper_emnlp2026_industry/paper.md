# PIPE-Cypher: Automatic Enterprise Benchmark Generation for Text-to-Cypher Systems

## Abstract

Enterprises increasingly use property graphs and Cypher to analyze fraud, risk, identity, customer, and operational data. A useful enterprise Text2Cypher benchmark must therefore be private, refreshable, executable, and sensitive to graph-specific semantics such as relationship direction, literal grounding, and schema vocabulary. We present PIPE-Cypher, a local-model pipeline for generating organization-specific natural-language-to-Cypher benchmarks. PIPE-Cypher combines schema introspection, reverse-query grounding, constrained generation, deterministic Cypher governance, execution validation, diversity controls, and LLM-judge review. In live runs with local Qwen3.5-9B generation and judging, PIPE-Cypher exports 3,000 accepted FinBench/SNB examples, completes three audited ablation suites, calibrates an automated judge, onboards ICIJ Offshore Leaks, and evaluates 12 local downstream models. The resulting benchmark is difficult zero-shot, and leakage-aware few-shot controls show that schema-specific examples can substantially improve compatible model families while still exposing brittle transfer failures.

## 1 Introduction

Property graphs are attractive in enterprise settings because the facts of interest are often relational paths: account transfers, identity entitlements, access chains, customer interactions, supplier dependencies, and fraud rings. Cypher gives analysts a compact language for these patterns. As LLMs become natural-language interfaces for graph analytics, an organization cannot evaluate a Text2Cypher system only on public schemas; it needs to know whether the model handles its labels, relationship directions, values, governance rules, and recurring operational questions.

This changes the benchmark problem. A static public dataset is valuable for shared comparison, but it cannot contain a bank's account taxonomy, an identity team's permission graph, or the exact categorical values that make a query answerable. It also cannot refresh when schemas change. Industry teams therefore need a benchmark factory: a repeatable way to turn a live property graph into a balanced, executable, privacy-aware NL-to-Cypher benchmark without sending sensitive schema or values to paid generation APIs.

PIPE-Cypher addresses this setting. The pipeline profiles a target graph, grounds question slots through reverse Cypher execution, constrains local-model generation, validates and repairs generated Cypher through deterministic gates, and uses a local LLM judge only after execution evidence is available. Its design treats Cypher correctness as a governed artifact rather than a prompt preference: relationship direction, read-only safety, exact literal use, categorical values, contextual return columns, and `RETURN DISTINCT` are checked or normalized before examples are accepted.

Contributions:

1. An end-to-end local-model pipeline for private enterprise NL-to-Cypher benchmark generation.
2. A Cypher governance layer that turns production query-writing constraints into deterministic validation and conservative rewrite rules.
3. A scaled evaluation over FinBench, SNB, and ICIJ showing balanced generation, ablations, judge calibration, and a 12-model local transfer stress test.
4. Reproducible artifacts for enterprise onboarding, privacy redaction, value sampling, benchmark refresh, and appendix-level auditability.

## 2 Related Work

Text2Cypher benchmarks and synthetic datasets show growing interest in natural-language interfaces to graph databases. Recent work such as [Mind the Query](https://aclanthology.org/2025.emnlp-industry.133/), [SyntheT2C](https://aclanthology.org/2025.coling-main.46/), [Auto-Cypher](https://aclanthology.org/2025.naacl-short.53/), and [Text2Cypher](https://aclanthology.org/2025.genaik-1.11/) provides important datasets, generation methods, and verification strategies. PIPE-Cypher differs by studying the enterprise process of generating, refreshing, auditing, and redacting private benchmarks from a target graph rather than assuming one static benchmark captures deployed use cases.

Text-to-SQL benchmarks such as [Spider 2.0](https://arxiv.org/abs/2411.07763) and [BIRD](https://arxiv.org/abs/2305.03111) motivate more realistic database tasks and execution-based evaluation. PIPE-Cypher adapts this lesson to property graphs, where relationship direction, path semantics, and graph-specific schema constraints are central.

Workload generation research, especially [CIKM AutoQuery](https://adalabucsd.github.io/papers/2024_AWESOME_CIKM.pdf), motivates separating benchmark-generation quality from model quality and reporting strategy-level coverage. PIPE-Cypher logs generation yield and failure modes by category, difficulty, and structural features. [LDBC FinBench](https://ldbcouncil.org/benchmarks/finbench/) and [LDBC SNB](https://ldbcouncil.org/post/introducing-snb-interactive-the-ldbc-social-network-benchmark-online-workload/) provide the primary and secondary graph workloads.

## 3 Method

PIPE-Cypher has six stages: schema profiling, workload planning, reverse Cypher grounding, constrained Cypher generation and repair, deterministic validation and execution, and LLM-judge review. The central design choice is to make answerability and governance executable. Prompts can ask a model to respect relationship directions or exact literals, but accepted examples must prove those properties through schema checks, parser-style structure extraction, live execution, and judge review.

First, the system introspects the target property graph to collect labels, properties, relationship types, observed directions, and bounded low-cardinality categorical values. This schema summary is used both in prompts and in deterministic validation.

Second, the system generates category-specific question templates. Reverse Cypher queries ground template slots in graph-backed values, reducing unanswerable questions.

Third, a local LLM generates Cypher using a constrained prompt. Retrieved examples are formatted with typed placeholders for graph-specific values, preserving query structure while reducing tenant-value leakage and memorized entity reuse. A schema-driven value grounder adds typed prompt annotations for categorical values and reverse-bound entities, covering punctuation variants, possessives, plurals, synonyms, name partials, and small typos. The prompt enforces schema-only generation, exact matching for quoted values, forward relationship directions, read-only behavior, `RETURN DISTINCT`, and aggregation rules.

Fourth, generated Cypher passes deterministic gates: read-only safety, syntax shape, parser validation when available, label and relationship checks, direction checks, property checks, execution, and repair. A lightweight Cypher analyzer extracts return aliases, variables, labels, relationship observations, risky constructs, and rewrite skip reasons so normalization is auditable rather than a silent string edit. For seeded full runs, PIPE-Cypher keeps a library of workload templates with deterministic reverse-binding queries and template Cypher instantiated with graph-backed slot values.

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

The project supports local vLLM-compatible model serving inside a private compute environment. Reported benchmark generation and judge review use `Qwen/Qwen3.5-9B`; downstream evaluation separately tests 12 locally served model checkpoints spanning general instruction, code-tuned, Cypher-tuned, and Text2Cypher-tuned families. Embeddings use local BGE-M3-style models where retrieval embeddings are needed. This matches the paper's enterprise deployment framing: benchmark generation stays inside the organization's compute boundary and does not rely on paid generation APIs.

We also estimate seed-template capacity before full generation. This check caught and fixed a scale blocker: reverse-binding execution was hard-capped to 10 rows, and no-slot negation/ranking seeds could not support full category targets. PIPE-Cypher now uses the configured binding limit and includes slotted negation and ranking seeds for both graphs.

For arbitrary enterprise onboarding, the repo includes a deployment template, privacy/value-sampling config fields, schema introspection from read-only credentials, and a redacted export CLI. Companies can bound which low-cardinality values enter prompts and can share review artifacts with quoted literals, entity values, and string-valued result samples replaced by stable placeholders.

The ICIJ onboarding run further motivated schema-derived sparse-category templates. PIPE-Cypher now derives relationship-count, anti-join, and top-k templates from observed labels, relationship directions, and safe low-cardinality properties, then grounds slot values with outcome-aware reverse Cypher.

| Graph | Target/category | Binding limit | Min seed capacity | All categories meet target |
| --- | ---: | ---: | ---: | --- |
| FinBench | 250 | 300 | 300 | Yes |
| SNB | 125 | 200 | 200 | Yes |

The deterministic Cypher layer uses production-derived constraints: schema-only prompting, exact matching, relationship direction discipline, `RETURN DISTINCT`, reserved variable rejection, categorical values, required contextual return columns, fuzzy value annotations, placeholderized retrieval examples, and parser-aware rewrite boundaries. PIPE-Cypher now records parser-style structure features and skips rewrites for risky constructs such as `UNION`, `CALL`, `UNWIND`, `WHERE EXISTS`, multiple `WHERE` clauses, or reserved variables.

For LDBC FinBench, the implementation grounds its built-in reference profile in the public snapshot export used by the datagen tooling. The profile includes typed properties and directed relationship patterns for people, companies, accounts, loans, media, transfers, withdrawals, repayments, deposits, sign-ins, investments, guarantees, account ownership, and loan applications. The Neo4j import script uses node uniqueness constraints and relationship creation rather than relationship merging so repeated transaction events between the same endpoints remain visible to generated benchmark queries. The SNB reference profile is grounded in the official Neo4j/Cypher headers and read-query files, covering people, forums, messages, tags, locations, organizations, and the standard interactive relationship patterns.

## 5 Experiments

We evaluate PIPE-Cypher around four questions that matter for an industry benchmark generator: RQ1, can a local-model pipeline produce a balanced executable benchmark over live property graphs? RQ2, do Cypher-specific governance and grounding steps make generation reliable at scale? RQ3, does the resulting benchmark expose meaningful downstream Text2Cypher failures rather than merely checking syntax? RQ4, can the same machinery onboard a new public enterprise-style graph without hard-coding FinBench or SNB?

The generated benchmark contains 3,000 accepted examples: 2,000 from LDBC FinBench and 1,000 from LDBC SNB. Examples are balanced across simple retrieval, complex retrieval, simple aggregation, complex aggregation, boolean existence, negation/difference, path/temporal transaction, and ranking/top-k categories.

Full live experimental setup:

| Setting | Value |
| --- | --- |
| Accepted examples | 3,000 |
| Primary graph | LDBC FinBench, 2,000 examples |
| Secondary graph | LDBC SNB, 1,000 examples |
| Categories | 8 balanced categories, 375 each |
| Generation/judge model | Local Qwen3.5-9B |
| Execution backend | Neo4j Community, two live databases |
| Judge audit packet | 80 sampled accepted/rejected pairs |

We also report three completed FinBench/SNB ablation suites: an initial target-50 suite, a corrected target-100 suite, and a seed-17 target-50 repeat. Each suite contains 14 graph/setting cells over unconstrained local generation, reverse-only generation, validators+repair, no retrieval, no rewrite, no LLM judge, and full PIPE-Cypher. Paper-reported ablations have collection manifests, model IDs, code revisions, run summaries, and readiness audits.

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
- Cypher operator-strategy coverage and strategy-conditioned downstream failures;
- downstream Text2Cypher execution accuracy and answer F1;
- supplementary reference-based text metrics over serialized answer sets and query strings: ROUGE, BLEU, METEOR, BERTScore, FrugalScore, cosine similarity, Jaro-Winkler similarity, and exact match. These are debugging and near-match diagnostics, not substitutes for executable correctness.

## 6 Results

The full live run produced 3,000 accepted examples from 4,777 candidates using local Qwen3.5-9B for generation and judging. Category-specific recovery top-ups filled the only under-target categories from the initial sequential run. Every exported example passed read-only, syntax, schema, execution, non-empty result, and judge gates.

| Graph | Candidates | Accepted | Acceptance | Categories at target |
| --- | ---: | ---: | ---: | ---: |
| FinBench | 3,404 | 2,000 | 0.588 | 8/8 |
| SNB | 1,373 | 1,000 | 0.728 | 8/8 |
| Total | 4,777 | 3,000 | 0.628 | 16/16 |

Failure taxonomy over the same 4,777 full-run candidates shows that rejected candidates were dominated by duplicate/diversity control during recovery (1,335), empty execution results (374), judge semantic rejection (66), and schema invalidity (2). This indicates that deterministic schema governance made invalid Cypher rare, while refresh-scale generation mostly needs better template and value exploration. The target-100 ablation suite reaches every non-unconstrained graph/setting/category target, and the three-suite comparison shows target-normalized coverage of 1.000 for every non-unconstrained cell.

The completed 80-row judge audit samples full-run accepted and rejected candidates, with a 40/40 judge accept/reject split, both graphs, and all eight categories. Human labels show 80.0% agreement, Cohen's kappa of 0.60, judge precision and specificity of 1.00, judge recall of 0.714, and no false accepts in the labeled sample. The judge is therefore conservative: it protects accepted-example quality while rejecting some human-approved candidates.

The accepted full-run records were exported into a benchmark package with stable example identifiers, train/dev/test splits, result samples, gate metadata, aggregate statistics, and a manifest hash. The export contains 3,000 accepted examples: 2,000 FinBench, 1,000 SNB, and 375 accepted examples in every planned category.

| Export artifact | Examples | FinBench | SNB | Train | Dev | Test |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Live full benchmark | 3,000 | 2,000 | 1,000 | 2,408 | 296 | 296 |

Diversity diagnostics treat value grounding as a first-class audit signal. The full export uses 1,115 unique grounded entity values, has a unique grounded-value ratio of 0.373, and exactly quotes grounded values in 82.6% of examples with entity bindings. The appendix reports these aggregate metrics without listing raw values, which keeps concentration visible without making the diagnostic itself a value leak. The reported export is balanced and executable, while the diversity diagnostics show what a benchmark owner should monitor during refresh or fine-tuning data generation.

Finally, we ran a downstream Text2Cypher stress test on the exported full test split. Each local model saw schema text and the natural-language question, generated Cypher, and was evaluated by live execution against the corresponding FinBench or SNB database. This result should be read as a discriminative-utility test rather than a strong-baseline claim: parse validity, schema validity, and execution success can be high while exact execution accuracy remains low for operational categories. Zero-shot execution accuracy across the 12-model local transfer suite ranges from 0.000 to 0.291 with a mean of 0.139. A stricter scored control that excludes exact query-signature matches and near-duplicate questions raises mean accuracy to 0.245, while ordered and random same-category example-bank controls reach 0.380 and 0.378. Model-level bootstrap intervals show that gains are concentrated in compatible model families rather than universal; the remaining failures are themselves useful evidence of brittle transfer under enterprise-style Cypher workloads.

| Split | Examples | Parse | Schema | Exec. success | Exec. acc. | Answer F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Live full test | 296 | 0.959 | 0.905 | 0.622 | 0.189 | 0.189 |

The downstream error taxonomy makes the discriminative signal more concrete: the 296-row full test split contains 56 exact-answer matches and 240 incorrect rows. Incorrect rows are dominated by answer mismatches (128), followed by execution failures (72), schema-invalid predictions (28), and parse-invalid predictions (12). This separates invalid-Cypher failures from executable but semantically wrong Cypher, which is the distinction an enterprise benchmark needs to expose.

Strategy diagnostics add a second view of benchmark structure beyond category balance. The full export contains six primary Cypher strategies: aggregation (1,125 examples), and single-hop, join-heavy, negation, order/rank, and path strategies (375 examples each). Strategy-conditioned downstream evaluation shows that local Qwen3.5-9B gets exact answers mainly on aggregation and single-hop queries, while join-heavy, negation, ranking, and path examples expose hard Cypher reasoning failures. The zero-accuracy slices are therefore useful: they identify where a model is not yet ready for operational graph analytics.

The scaled ablation suites show that the benchmark factory is stable once deterministic grounding and schema metadata are fixed. They should be read as a reliability study of the execution-grounded core rather than as a claim that every optional module independently increases yield. In the target-100 suite, every non-unconstrained graph/setting cell reached all eight category targets with 800 accepted examples per cell; the full PIPE-Cypher setting accepted 800/824 candidates on both FinBench and SNB. Across the three evidence-ready suites, target-normalized coverage is 1.000 for every non-unconstrained cell; component value is clearest in gate diagnostics, failure taxonomy, and auditability, while reverse grounding plus deterministic governance forms the robust minimum viable core. The unconstrained local-generation stress baseline is reported with explicit attempt accounting because plausible raw generations do not by themselves provide balanced, reliable benchmark coverage.

ICIJ onboarding reaches the same per-category target on a larger public finance/compliance graph: 800 accepted examples from 983 candidates over 2.0M nodes and 3.3M relationships, with 100 examples in every category. This does not replace private tenant validation, but it exercises arbitrary-schema onboarding beyond the two LDBC study workloads. In practice, ICIJ forced the pipeline to derive relationship-count, anti-join, and top-k templates from observed schema structure instead of relying only on preauthored LDBC seeds.

## 7 Industry Use

PIPE-Cypher is intended to be rerun when an enterprise graph changes. The generated artifact records the schema snapshot, graph profile, model identifier, validation gates, execution samples, judge scores, difficulty features, and source run for every example. Long-running jobs can be monitored from JSONL records and recovered with category-specific top-up runs that reject questions accepted in earlier runs. This design supports private benchmark refreshes without exposing schemas or values to paid APIs, while still leaving audit hooks for data owners to sample accepted and rejected examples and to build a schema-specific question-answer demonstration bank for retrieval, adaptation, and future tenant-specific training.

## 8 Conclusion

PIPE-Cypher reframes Text2Cypher benchmarking as a private, repeatable enterprise workflow. The main lesson is that benchmark generation improves when Cypher constraints become executable gates: reverse grounding makes questions answerable, deterministic governance catches unsafe or schema-invalid queries, execution exposes empty or brittle candidates, diversity diagnostics reveal concentration, and a calibrated local judge provides a conservative semantic filter. This produces a benchmark that is not only larger, but more useful: it is balanced, auditable, refreshable, and able to reveal downstream model failures that syntax-only evaluation would hide.

## Limitations

Execution validity does not guarantee semantic correctness. The completed 80-row, single-audit-sheet calibration suggests a conservative judge with no observed false accepts in the labeled sample, but the confidence interval is necessarily wider than the point estimate and larger multi-annotator audits may reveal additional failure modes. FinBench, SNB, and ICIJ are public enterprise-style proxies rather than a proprietary tenant graph. The full export is balanced by graph, category, and difficulty, yet query-signature diagnostics show residual template concentration from the seeded, execution-grounded generation strategy. The downstream few-shot result should be read as graph-specific example-bank conditioning: ordered and random same-category demonstrations often share query signatures, while the stricter no-signature control is lower and has a wide model-level interval despite improving the aggregate. Tenant-specific fine-tuning remains an engineering path enabled by the artifact, not a completed deployment claim in this paper. Generated artifacts may contain private schema details or sampled values, so organizations should apply privacy redaction and normal data governance controls before broad sharing.

## Ethics And Governance

PIPE-Cypher is designed for private enterprise benchmark generation. Prompt logs and benchmark artifacts may contain schema details and sampled values, so organizations should apply access controls, retention policies, and redaction where needed. The pipeline rejects write/admin Cypher to reduce operational risk.
