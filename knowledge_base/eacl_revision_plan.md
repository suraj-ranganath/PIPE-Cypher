# Post-EMNLP Revision Plan (EACL / next Industry Track)

> **Status 2026-11-12:** The experiments were executed on `jamming` (CPU only) with hosted open-weight models (GLM-5.3-Flash FP8 generator/judge; downstream models at released precision) because GPU access ended. Results, decisions, and deviations are in `experiments/snapshots/20261112_naacl_v2/status.md`; the review-concern mapping is in `knowledge_base/naacl2027_reviewer_concern_map.md`. Parts of this document that refer to ds-serv6, local vLLM, or Qwen3.5-9B as generator are historical.


Date: 2026-11-11. Supersedes `review_response_matrix.md` (June 2026) for the
resubmission. EMNLP 2026 Industry decision: Reject (AC: borderline conference;
reviewers 2.5 / 1.5 / 2.5).

## 0. Venue status (verify before planning)

| Venue | Industry deadline | Notes |
| --- | --- | --- |
| EACL 2027 Industry | 11 Sep 2026 (passed) | Reviews 28 Oct, rebuttal closed 4 Nov, meta 30 Nov, notification 18 Dec. If the paper is under review there, it cannot go anywhere else until 18 Dec. |
| NAACL 2027 Industry | 13 Nov 2026 (extended from 31 Oct) | Notification 24 Feb 2027. Too soon for the experiments below. |
| ACL 2027 | ARR 4 Jan 2027 (main) | No Industry call posted yet. In past years it had a separate early-spring deadline. This is the realistic target for the full revision. |

**If an EACL submission is under review with the June downstream numbers, those
numbers are wrong (Section 1.1).** If accepted, the camera-ready must correct
them. Consider telling the PCs now rather than at camera-ready.

## 1. Critical findings from the November 2026 audit

These change the paper's story. Every downstream sentence in the EMNLP
submission is affected.

### 1.1 The "8/11 checkpoints score 0.000" result was an infrastructure failure

In `artifacts/evaluations/20260604_clean_*`, these eight checkpoints got
`404 Client Error: Not Found for url: http://localhost:800{0,1}/v1/chat/completions`
on 296/296 requests in every zero-shot, ordered, scored-no-signature, and random
run: both aigentx LoRAs, Azzedde, Gemma-2-9B-IT, Neo4j Gemma-3-4B, projectwilsen,
Saiprasanth15, and tomasonjo. That is 8 models x 6 conditions of empty
predictions, scored 0.000. Only Qwen3.5-9B, Qwen2.5-Coder-7B, and the Neo4j
Gemma-2 LoRA produced predictions.

On the earlier (non-paper) `20260601` split, the same checkpoints produced real
predictions: zero-shot 0.07-0.29 and few-shot 0.73-0.99 (tomasonjo 0.166 / 0.976,
Azzedde 0.155 / 0.976, Gemma-2-9B-IT 0.152 / 0.993). So the reviewers' central
critiques had no factual basis: bimodality, "stylistic compatibility with the
generator", "only 3/11 benefit", and "public T2C fine-tunes fail
catastrophically". The readiness manifest checked row counts and checksums,
never request errors.

Even the old-split fine-tune numbers are suspect. The old queue script served
each LoRA base model under the same name as its adapter, so requests could reach
the untuned base. `configs/downstream_models_naacl2027.yaml` and
`scripts/run_downstream_suite.py` now reject that setup.

The Neo4j Gemma-3-4B 0.000 on the old split was also an artifact. The model
emits the two characters `\n` instead of newlines, and the evaluator never
unescaped them, so every query failed to execute.

Qwen2.5-Coder zero-shot fell from 0.291 (old split) to 0.007 (clean split).
Direction errors rose from 25 to 205: it suddenly writes
`(:Person)<-[:OWN_ACCOUNT]-(:Account)`. The schema prompt renders correctly, so
the cause is unknown (endpoint config? chat template?). Prompts were not logged.
Predictions now carry a `prompt_sha256` so the next run can be audited.

### 1.2 The downstream metric penalizes correct answers

- **Context columns.** The governance layer makes references co-return context
  (`Account.accountId` comes with `accountType, isBlocked`). The question never
  asks for those columns. 161/296 test references return several columns. Strict
  row-set equality then scores a prediction with exactly the right account IDs
  as 0, which explains most of the 0.000 on complex_retrieval, negation, and
  path. It also explains the zero-to-few-shot jump: demonstrations teach the
  projection convention.
- **Governance-gated execution.** The evaluator ran a prediction only if it
  passed every construction-time rule. Valid Cypher (undirected `-[:KNOWS]-`,
  `-[]->`, reserved variable names) was never executed and scored 0.
- **Reviewer framing.** The reviewers' "asymmetric context" point is partly
  right. The generator saw the context-column rule; downstream models did not.

### 1.3 The benchmark is concentrated by template

- 123 canonical query signatures across 3,000 examples (36 template families).
  The top 10 signatures cover 67.3% of examples.
- 12 of 16 graph x category cells have 1-3 signatures. All 250 FinBench
  complex_aggregation items are one query with different names, and the same
  holds for simple_retrieval and simple_aggregation.
- 289/296 test items share a signature with train. The effective test size is
  about 26 signatures, not 296 items. That is why per-category scores are 0.000
  or 1.000, and why row-level bootstrap CIs are far too narrow. Measured with
  `scripts/analyze_downstream_statistics.py cluster-ci`, Qwen3.5-9B zero-shot
  EX is 0.189, with a row-level CI of [0.145, 0.233] and a signature-cluster CI
  of [0.029, 0.392]. That is 4.1x wider, a design effect of about 17, and an
  effective n of about 17.
- Few-shot at about 0.99 is mostly copy-and-substitute from a same-signature
  demonstration.
- There are no `hard` items. Difficulty is fixed by category (complex_aggregation
  and ranking are 100% medium; simple_* and complex_retrieval are 100% easy).

### 1.4 Some references are probably semantically wrong, and governance forces it

- All 140 SNB `KNOWS` references are directed (`-[:KNOWS*1..2]->`). LDBC stores
  each friendship once (`person_knows_person`), and the official SNB Cypher
  queries traverse KNOWS undirected. "Within two knows hops" probably misses
  friends. The direction gate rejects the correct undirected form. **Verify
  with one query:** for test persons, count 2-hop neighbours directed vs.
  undirected.
- 146/296 test references carry `LIMIT 200/300` without `ORDER BY`. Two hit the
  limit, so their references are non-deterministic.
- `CONTEXTUAL_RETURN_PROPERTIES` in `pipecypher/validator.py` is hard-coded to
  FinBench labels. That violates the "no hard-coded schema" rule and should be
  derived from the schema/profile.

Items like these are exactly what the independent-judge and human-validation
experiments should surface. Report them honestly; reviewers will value a
pipeline that measures its own error rate.

## 2. Code fixes completed (2026-11-11)

| Fix | Where | Test |
| --- | --- | --- |
| Model preflight: abort if `--model` is missing from the endpoint's `/models` | `pipecypher/llm.py::assert_model_served`, `scripts/generate_text2cypher_predictions.py` | `test_assert_model_served_rejects_unserved_model` |
| Abort after N consecutive request failures | `scripts/generate_text2cypher_predictions.py --max-consecutive-errors` | n/a (live path) |
| Evaluator flags failed requests; exit 3 when failure rate > 1% | `pipecypher/evaluation.py`, `scripts/evaluate_benchmark_predictions.py` | `test_failed_requests_are_flagged_not_scored_silently` |
| Transfer summaries refuse runs with failure rate > 1% (also legacy runs) | `pipecypher/downstream_model_transfer.py::prediction_failure_rate` | `test_transfer_report_marks_failed_request_runs_incomplete` |
| Execute read-only predictions as written; report governance violations separately (`governance_valid`, `governed_execution_accuracy`); `--governed-execution-only` keeps the legacy behaviour | `pipecypher/evaluation.py::evaluate_prediction` | `test_evaluator_executes_governance_violating_read_only_prediction`, `test_evaluator_never_executes_write_queries` |
| Projection-tolerant accuracy: forgives only policy-injected context columns, extra predicted columns, column order/aliases, and whole-entity returns | `policy_context_columns`, `projected_answer_scores` | 6 tests |
| Unescape literal `\n`/`\t` outside quoted literals | `pipecypher/text2cypher.py::unescape_literal_whitespace` | 2 tests |
| `prompt_sha256` on every prediction | `pipecypher/text2cypher.py` | n/a |
| Medians in control aggregates | `downstream_model_transfer.py::_aggregate_control_models` | n/a |

Re-summarizing the June 4 suite with the new guard now reports 3/11 complete
models, as it should.

## 3. Review concerns mapped to the work that answers them

| # | Concern (who) | What answers it | Exp. |
| --- | --- | --- | --- |
| C1 | Same Qwen3.5-9B generates, judges, and is evaluated; references not independently validated (AC, Hoqx, Uscg) | Cross-family local judges on the full benchmark, plus multi-annotator human validation that reports a benchmark error rate, plus a generator self-preference test | E2.1-E2.4 |
| C2 | Bimodal results; mean hides it; 8/11 at 0 (AC, Hoqx, hUmi) | Bug fix (Section 1.1); full rerun; per-model table with medians and template-clustered CIs | E3.1-E3.3 |
| C3 | Prompt-format fairness for T2C fine-tunes (AC, Uscg) | Standardized and model-native prompt formats for every checkpoint | E3.2 |
| C4 | Is the benchmark hard, or is the eval broken? Is it useful? (hUmi, Uscg) | Sanity anchor on the public Text2Cypher-2024 test set, plus ranking agreement with a curated benchmark on the same graph | E3.4, E3.5 |
| C5 | Low signature diversity / long tail (AC, Uscg) | Benchmark v2 with signature quotas, uncovered-structure-conditioned template induction, a hard tier, and a signature-disjoint split | E1.x |
| C6 | Refresh never demonstrated (AC, Uscg) | Schema-migration and data-drift experiment | E4.1 |
| C7 | No cost/time analysis (Uscg) | Clean timed end-to-end run: per-stage wall time, calls, tokens, GPU-hours per 1k examples | E4.2 |
| C8 | Scale to 100+ labels (Uscg) | Multi-domain consolidated graph and/or synthetic wide-schema stress test | E4.3 |
| C9 | No real deployment / analyst validation (AC, Uscg, hUmi) | Partner deployment if any exists; otherwise a practitioner rating study and log-seeded generation | E4.4, E4.5 |
| C10 | Cross-backend claims (Hoqx, AC) | Narrow the claim. Optional: Memgraph execution-portability check | E4.6 |
| C11 | Hard to follow; jargon; no running example; graph stats in appendix; model list hidden (hUmi) | Rewrite (Section 5) | - |
| C12 | "Deterministic" vs LLM judge; "reference" overstated (Hoqx) | Terminology: "pipeline-validated reference"; Figure 1 separates deterministic gates from the LLM gate and shows the downstream execution comparison | - |
| C13 | Judge sensitivity / significance tests (hUmi) | Judge-swap ablation; paired tests clustered by template | E2.3, E3.3 |

## 4. Experiment plan (priority order)

All models are local weights on project GPUs (AGENTS.md). Run
`scripts/validate_config.py` before every YAML-driven job. Track every run in a
status doc with seed, revision, model IDs, and paths.

### Phase 0: re-score and verify (1-2 days, DB only, no LLM)
- **E0.1** Re-evaluate the existing valid predictions (Qwen3.5-9B, Qwen2.5-Coder,
  Neo4j Gemma-2 LoRA; all conditions) with the new evaluator. Report strict EX,
  projected EX, and governed EX side by side. This shows how much of the old gap
  was a metric artifact.
- **E0.2** Run the KNOWS direction check (Section 1.4) and the gold-LIMIT
  truncation audit on the full export. Quantify how many references are
  incomplete.

### Phase 1: benchmark v2 (about 1-2 weeks; main GPU cost)
Code first (Section 6). Then regenerate FinBench + SNB at 3,000-4,000 examples
with:
- a per-signature cap (for example at most 8 instances per canonical signature
  per graph), with the shortfall filled by template induction;
- uncovered-structure-conditioned template induction: the LLM proposes new
  templates for (category x operator x schema-atom) combinations not yet
  covered; they are reverse-grounded and validated as usual;
- a hard tier: temporal windows on transfer timestamps, variable-length paths
  with predicates, WITH pipelines, multi-aggregate, OPTIONAL MATCH, existential
  subqueries, top-k over aggregates;
- an answer contract on every item (`answer_columns`, `context_columns`), and
  NL realizations that name requested attributes when the reference returns
  several;
- a symmetric-relationship policy (KNOWS undirected) and no unordered LIMIT in
  references;
- two test splits: random and **signature-disjoint** (template-held-out). The
  signature-disjoint split is the honest generalization test.

Target diagnostics: at least 600 unique signatures (vs. 123); at least 15
signatures per graph x category cell; difficulty with a real hard tier.
Re-run diversity, gate-cascade, rejection-taxonomy, and redaction audits on v2.
The v1 ablation suites can stay as "core reliability" evidence only if they are
explicitly labelled v1.

### Phase 2: independent semantic validation (about 1 week, overlaps Phase 3)
- **E2.1 Cross-family judges.** Re-judge every v2 candidate (accepted and
  rejected) with two non-Qwen local judges, for example Llama-3.3-70B-Instruct
  (AWQ, TP=2-4 on A5000s) and Gemma-3-27B-IT. Each gets exactly the generator's
  context: schema slice, template, grounded values, execution sample. Report
  pairwise Cohen's kappa, Fleiss' kappa, and the accept/reject confusion against
  the Qwen judge. Items flagged by any judge go to human adjudication.
- **E2.2 Human validation of the benchmark.** This is the number reviewers want:
  the estimated error rate of accepted items, with a Wilson CI.
  1. Exhaustive template-level check: every v2 signature x 2 realizations.
  2. A stratified instance sample of at least 300 accepted items, 2 annotators
     (for example both authors plus one external), with inter-annotator kappa.

  Rubric: question unambiguous? reference correct for the question? answer
  columns appropriate? Re-run judge calibration (Qwen and the independent
  judges vs. humans) on at least 200 accepted + rejected items. Check whether
  the IRB exemption covers additional annotators.
- **E2.3 Judge-swap ablation.** Build the accepted set under the Qwen judge, the
  Llama judge, and their intersection. Show that downstream model rankings are
  stable (Kendall tau) and how yield changes.
- **E2.4 Generator self-preference test.** This is the decisive circularity
  experiment. Generate a target-50/cell v2 slice with a different-family
  generator (Gemma-3-27B or Llama-3.3-70B). Evaluate all downstream models on
  both slices. Does Qwen3.5-9B score disproportionately well on Qwen-generated
  items? Report the generator x model interaction.

### Phase 3: downstream evaluation done right (about 3-5 days; cheap per model)
- **E3.1 Models** (local; prefer current families):
  - general: Qwen3.5-9B (flagged as generator), Llama-3.1-8B-Instruct, Gemma-3-12B/27B-IT, Mistral-Small-24B, Llama-3.3-70B (AWQ);
  - code: Qwen2.5-Coder-7B/32B, Qwen3-Coder-30B-A3B;
  - Text2Cypher-tuned: Neo4j Gemma-2-9B LoRA, Neo4j Gemma-3 T2C checkpoints (verify current names on HF), tomasonjo, Azzedde, aigentx, projectwilsen, Saiprasanth15.

  The preflight now blocks mis-routed endpoints. Also check that the error count
  is 0 before summarizing.
- **E3.2 Prompt conditions:** (a) standardized PIPE prompt, now including the
  answer-contract rule; (b) each checkpoint's model-card format (fetch and cite
  the model cards; store the format in a registry); (c) few-shot retrieval from
  train on the signature-disjoint split (headline); (d) same-signature retrieval
  (upper bound only).
- **E3.3 Reporting:** per-model table (strict EX, projected EX, answer F1,
  governance-violation rate including wrong direction), median and IQR across
  models, bootstrap clustered by signature, paired McNemar / paired bootstrap
  between conditions, and per category / difficulty / strategy slices.
- **E3.4 Sanity anchor.** Evaluate the same checkpoints on the public Neo4j
  Text2Cypher-2024 test rows whose databases can be loaded locally (Neo4j
  example-graph dumps). Reasonable scores there and low scores on PIPE-Cypher
  mean a real transfer gap, not a broken harness.
- **E3.5 Benchmark validity via ranking agreement.** Onboard PIPE-Cypher onto
  2-3 of those same Neo4j example graphs (for example recommendations,
  northwind, stackoverflow). Generate a benchmark for each. Compute Kendall tau
  between model rankings on the generated benchmark and on the curated
  Text2Cypher-2024 items for that graph. This is the strongest "is the generated
  benchmark useful" evidence a benchmark-factory paper can show, and it also
  adds 2-3 onboarding graphs.

### Phase 4: industry evidence (parallel)
- **E4.1 Refresh / migration.** On a FinBench copy, apply realistic migrations:
  rename `TRANSFER_TO`, split or rename a property, add a label (for example
  Merchant), drop a relationship type. Also apply data drift: a different
  datagen snapshot, or delete or perturb 10% of edges. Measure the share of v1
  items that break (schema/execution) vs. *silently change answers*; the
  accuracy misestimate from a stale benchmark; and full vs. incremental refresh
  cost. This turns "refreshable" into evidence.
- **E4.2 Cost.** Run one clean, timed end-to-end v2 generation on a single
  A5000. Report per-stage wall time, LLM calls, tokens, GPU-hours per 1,000
  accepted examples, and acceptance rate. Put a compact table in the main paper.
- **E4.3 Schema scale.** Load FinBench + SNB + ICIJ + 2-3 example graphs into one
  database (about 40-60 labels), and/or a synthetic 50/100/200-label schema.
  Report planning/grounding time, category fill, and prompt size with schema
  slicing.
- **E4.4 Practitioner study.** If there is a partner or employer graph, even a
  small deployment case study is the single most valuable industry addition.
  Otherwise, 3-5 graph practitioners blind-rate generated vs. human-written
  questions (realism, usefulness, clarity).
- **E4.5 Log-seeded generation.** Use Text2Cypher-2024 questions for one graph
  as "analyst log" seeds. Show that seeded generation covers more held-out real
  query signatures than unseeded generation.
- **E4.6 (optional)** Memgraph portability: execute v2 references and report
  dialect failures. Otherwise, just narrow the claim.

### Compute sketch (8 x A5000 24 GB, if still available)
- Downstream: 296-600 test items x about 6 conditions per model is minutes per
  model on vLLM. About 15 models x 2 prompt formats is roughly 1-2 GPU-days in
  total.
- 70B AWQ judge: TP=2-4. Re-judging about 6k candidates takes hours.
- v2 generation: comparable to the original full run plus induction calls.
  Measure it (E4.2) rather than guess.
- **Blocker as of 2026-11-11:** `ssh suraj@ds-serv6.ucsd.edu` returns
  `Permission denied (publickey)` from this machine (likely the key needs
  `ssh-add`, or access changed).

## 5. Paper restructure (6 pages + Limitations; appendix after refs)

One-sentence contribution: *PIPE-Cypher turns a live property graph into a
private, execution-grounded Text2Cypher benchmark whose references are
validated by deterministic gates, cross-family judges, and humans, and we show
that the generated benchmarks rank models like curated ones and stay valid
across schema refreshes.*

- Intro (0.75 pp): enterprise need; why an agent alone is not enough; contributions with numbers.
- Related work (0.4 pp).
- Method (1.6 pp): **one running FinBench example** threaded through every stage, as a figure/box; glossary table; Figure 1 redrawn to (i) split deterministic gates from the LLM gate and (ii) include the downstream execution comparison.
- Setup (0.4 pp): graphs (compact stats table in main), models (full list with family mapping), metrics (strict vs. projected EX, defined precisely).
- Results (2.3 pp):
  - (a) benchmark quality: gates, diversity v1 -> v2, error rate from human validation, judge agreement;
  - (b) validity: ranking agreement, self-preference test;
  - (c) downstream per-model table with medians and clustered CIs, prompt-format effect, signature-disjoint few-shot;
  - (d) refresh and cost.
- Conclusion (0.2 pp). Limitations: explicitly public proxies, the v1/v2 split, Neo4j-only, and the residual human-estimated error rate.

Terminology: "pipeline-validated reference" (not "gold"); call only the
deterministic gates "deterministic"; "Neo4j-evaluated, backend-portable by
design"; "enterprise-oriented workflow validated on public proxies".

## 6. Code still to do

1. Per-signature quota and uncovered-structure template-induction loop in generation.
2. Answer contract (`answer_columns`/`context_columns`) in export. The evaluator then reads it instead of inferring context from the policy.
3. Schema-derived contextual-return policy (remove hard-coded FinBench labels).
4. Symmetric-relationship policy in validator + schema config.
5. Reference determinism gate: reject unordered `LIMIT` on set-valued references, or flag truncation.
6. Hard-tier template families.
7. `--split-strategy signature_disjoint` in export.
8. `scripts/rejudge_with_independent_model.py` + agreement report (kappa, confusion, disagreement packet for humans).
9. Model-native prompt registry for downstream checkpoints (from verified model cards).
10. Signature-clustered bootstrap in `evaluation_uncertainty.py`; paired McNemar.
11. Migration/refresh harness and stale-vs-fresh diff report.
12. Ranking-agreement harness (Kendall tau with bootstrap CI).
13. Readiness manifest: add a prediction-error check, so a 404 suite can never pass "readiness" again.
