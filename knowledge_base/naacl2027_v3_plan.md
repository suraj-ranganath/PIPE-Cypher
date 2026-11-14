# NAACL 2027: v3 Rebuild Plan

Written 2026-11-12 18:30Z. Deadline: 13 Nov 23:59 AoE, which is **14 Nov 11:59Z** (14 Nov 03:59 PST).
The current v2 paper stays the fallback until every v3 audit passes.

## 1. Goal

Rebuild the benchmark with a pipeline that has no known defects. The resulting paper should:

- leave only scope statements in Limitations;
- report a human-verified reference error rate;
- show substantial agreement between judges;
- have balanced easy/medium/hard tiers that are validated empirically;
- run generation to a full 3,000+ items.

## 2. What the v2 logs say (evidence behind each fix)

| Problem | Evidence from v2 | Root cause |
| --- | --- | --- |
| Wasted generation (budget) | 1,220 of 5,031 candidates (24%) were empty. 99% came from LLM-proposed templates, 70% of them single-slot. | Slots fell back to `MATCH (x:Label) WHERE x.prop IS NOT NULL`. That picks any id, not one that has the template's pattern (e.g., a Post with no replies). |
| Budget stop | Generation and evaluation shared one cap. 482 accepted items (18.5%) were thrown away to rebalance overfull cells. | No per-stage caps. Shards had their own quotas, so cells overshot. |
| Tiny hard tier | The heuristic called 1 of 216 test items hard. Yet 43 were solved by none of 11 models and 66 by 1–3. | The heuristic does not track what makes items hard. On v2, solve-count correlates with query length (r = -0.54), return arity (-0.53), and relationship count (-0.34). Mean models solving: path_temporal 1.1 of 11, complex_retrieval 2.5, simple_retrieval 6.3. |
| Judge disagreement (kappa 0.22) | gpt-6-luna flag reasons: ties 132, count/aggregation 100, temporal 57, duplicates 40, LIMIT/top-k 37, hop counts 31, KNOWS 24, self-loops 21, ambiguity 45. | Most are *convention* questions the question never states (count distinct? "after" strict? "within 2 hops" = 1..2? self-loops?) or determinism issues. A gate or an explicit convention can settle them. |
| Defective items | 65 ties at the LIMIT cutoff; 3 with an id bound as k. | No determinism gates. |
| Repetitive phrasing | Self-BLEU got worse, 0.81 -> 0.87. | One realization style. |

## 3. Changes (all off by default; v3 configs turn them on)

**P0: must have**

1. **Outcome-aware binding for every template.**
   - LLM and induced templates must come with parameterized Cypher.
   - The binding query is derived from that Cypher: remove the slot predicates, keep the pattern, and project the slot properties from one row. Before any LLM call, the parameterized query is executed with the binding and must return rows.
   - The generic lookup is never used for LLM templates. Failures log `slot bindings unavailable`, as AGENTS.md requires.
   - Expected effect: most of the 24% empty waste disappears.
2. **Determinism and consistency gates:**
   - `reject_limit_boundary_ties`;
   - `max_rank_slot_value`;
   - new: every number and quoted value in the question must equal a Cypher literal, and the reverse.
3. **Difficulty control.**
   - Use a transparent structural score: hops, variable-length paths, query stages, aggregation and grouping, negation, number of predicates, temporal comparisons, and answer-column arity.
   - Set tier thresholds on the v2 test solve-rates (216 items x 11 models), then validate on v3 items, which are new.
   - The planner sets quotas per (category, tier). Target: overall about 35/35/30. Simple categories mix easy/medium; complex, path, negation and ranking mix medium/hard.
   - Template induction is asked for the structures that a missing cell needs.
   - Unmet quotas are reported, never silently loosened.
4. **Judge v3 (agreement).**
   - A shared *convention sheet* goes into the question-realization prompt and the judge prompt alike, so questions state their conventions.
   - The judge fills a decomposed checklist: entities/values, relationship semantics, aggregation type, grouping key, comparison operators and boundaries, ranking direction and k, answer columns present, no unrequested filters, unambiguous.
   - It returns yes/no/NA per criterion with evidence; code computes the verdict.
   - Checks that gates already make deterministically are removed from the judge's scope.
   - **Gate = a panel of two open-weight judges from different families:** GLM-5.3-Flash plus the best of {gpt-oss-20b, Gemma-4-26B-A4B, Qwen3.5-9B}, chosen on a calibration set.
   - gpt-6-luna and the humans stay outside the gate as independent auditors.
   - Calibration uses 150 v2 items oversampled for disagreement, with at most 4 prompt iterations; the prompt is then frozen. Agreement is reported on fresh v3 items. Ablation: kappa with the v2 prompt vs the v3 prompt on the same items.
   - Optional repair-by-clarification: when the judge says "ambiguous" and proposes a clarification, regenerate the question once and re-judge.
5. **Style-diverse realization.** Five registers: terse analyst, business manager, imperative, context-first, keyword-style. Generate 2 paraphrases and keep the one least similar (BLEU) to already-accepted questions in the cell. Value-preservation guards stay.
6. **Budget engineering.**
   - Per-stage caps in the spend ledger.
   - Generation runs first and is frozen before evaluation starts.
   - A shared per-cell accepted counter across shards, so there is no overshoot.
   - Cells are filled round-robin, so a budget stop still yields a balanced set.
   - On reaching the cap: pause and resume, never exit.
7. **The pilot is a full dress rehearsal.**
   - 10 per cell, then every audit as go/no-go: ties, malformed slots, redaction, empty rate, tier mix, judge kappa, diversity.
   - Plus a 30-item spot check by me.
8. **Human validation.**
   - 200 items, stratified by graph x category x tier, oversampling hard items, items no model solves, and judge-disagreement items. Weighted estimates are reported.
   - 2 annotators, each labeling 130 items (60 shared for annotator kappa).
   - Labels: question clear / ambiguous; reference correct / minor issue / wrong; note.
   - Delivered as a private labeling web page; labels are read back automatically.

**P1: should have**

9. **Two independent seeds, about 1,600 items each.** Their union is the benchmark (>= 3,000). Model-ranking tau between the halves measures regeneration stability, at no extra cost.
10. **Zero-shot on all items.** All 11 hosted models plus 2 local T2C fine-tunes (MLX on the Mac, native and standard prompts) on all ~3,200 items. Held-out test (~300) for zero-shot, governed, and few-shot. This gives per-tier and per-category curves with large n.
11. **Generator swap with fixed plans.** Replay identical templates and bindings with gpt-6-luna and with Qwen3.5-9B: three generators, identical composition, so only the generator differs.
12. **Small-generator ablation.** Qwen3.5-9B (runs on one 24 GB GPU) as the full-pipeline generator on a 400-item slice: yield, diversity, judge and human quality, and ranking agreement with the main build. This answers "needs multi-GPU hardware".
13. **Public-graph benchmarks rebuilt with v3** (recommendations, northwind, fincen), then rank agreement with curated T2C-2024 again. The anchor results are reused unchanged.
14. **Refresh executed end to end on v3 FinBench.**
    - Rewrite, re-execute, and regenerate only affected items.
    - Measure cost and time vs a full rebuild.
    - Accuracy misestimate for all 11 models; one SNB migration.

**P2: if time allows**

15. **Schema scale: 25 -> 150 labels.** Merge the five graphs and add namespaced tenant replicas. Measure yield, cost, prompt tokens, and judge pass. Add generation-side schema slicing.
16. **Log-seeded generation.** Seed templates from the T2C-2024 *train* questions as a stand-in for a tenant's query log, then compare the category distribution. The agreement test uses the *test* split, so there is no leakage.

## 4. Timeline (UTC; PST = UTC-8)

| When (UTC) | Work | Checkpoint |
| --- | --- | --- |
Revised 2026-11-12 21:40Z. Implementation started about 2.5 h later than first planned.

| When (UTC) | Work | Checkpoint |
| --- | --- | --- |
| 12 Nov 21:40-05:00 | Implement P0 1-8, cache-ordered prompts, and Novita configs, with tests. Run the provider-equivalence check and judge calibration in parallel. Build the annotation page. | All tests pass; strict config validation passes. |
| 13 Nov 05:00-07:00 (9-11pm PST) | Pilot dress rehearsal. Generate 10 per cell on FinBench and SNB, then export and run every audit. Also run each downstream model, the refresh harness, a 20-item generator-swap replay, and the labeling page on pilot items. | **G1** (criteria in section 7). Fallback: v2 + rubric re-judging + filtered export + human labels on v2. |
| 07:00-12:00 | Full generation (2 seeds), public-graph builds, generator-swap replays, 9B ablation. | |
| 12:00-16:00 | Export, audits, gpt-6-luna audit, downstream suites, Mac T2C runs, refresh, P2. | **G2 (15:00):** v3 frozen and balanced; otherwise fall back. |
| 16:00-21:00 (8am-1pm PST) | **Human labeling: 200 items, 2 annotators, about 2.5 h each.** Paper rewrite in parallel. | **G3:** labels in. |
| 21:00-01:00 | Integrate human results; paper complete. | |
| 14 Nov 01:00-05:00 (5-9pm PST, 13 Nov) | Owner review; fixes. | |
| by 14 Nov 08:00 (midnight PST) | Owner submits on OpenReview (4 h buffer before 11:59Z). | |

## 5b. Budget with GLM on Novita FP8 (2026-11-12 21:40Z; supersedes 5a)

Owner decision: keep the full prompts and the full pipeline (per-item GLM generation, GLM in the judge panel, all models on all items). Pin GLM-5.3-Flash to Novita's FP8 endpoint instead of Z.AI's. Budget: at most $25 end to end.

**Provider facts** (OpenRouter endpoint list, fetched 21:25Z):

| Provider (fp8) | $/M input | $/M cached input | $/M output | Notes |
| --- | ---: | ---: | ---: | --- |
| Z.AI (v2) | 0.150 | 0.030 | 0.50 | no `seed` |
| **Novita** | **0.084** | **0.017** | **0.28** | listed as a 44% discount (may be a promotion); supports `seed`, `response_format` |

**Probe** (3 calls, $0.0003, ledger in the session scratchpad):

- Every call was served by Novita.
- Latency was 1.0-1.4 s. On Z.AI, v2 calls took 6-25 s.
- The 2nd and 3rd calls reused the 2,304-token prefix from cache (95% of the prompt), so they cost 73% less. The 3rd call had a different question with the same prefix and still hit.
- No reasoning text was returned.

**Implication.** Repriced on Novita, v2's GLM workload (27.3M input tokens, 22% cached, 1.83M output) costs $2.40 instead of $4.29. With about 80% cache hits it costs $1.34.

**Efficiency without cutting content: cache-ordered prompts.** Put the fixed blocks first in every prompt: schema, rules, convention sheet, examples. Put the item-specific blocks last: template, slots, candidate Cypher, results. The content is unchanged. v2 judge prompts got only 2% cache hits.

| Item | OpenRouter $ |
| --- | ---: |
| Provider-equivalence check (150 v2 items re-judged on Novita vs the Z.AI verdicts) and judge calibration (GLM + 3 cross-family candidates, at most 4 prompt versions) | 0.4 |
| Pilot dress rehearsal: every experiment at small scale, budgeted twice | 1.0 |
| Main generation, about 3,200 items in 2 seeds: GLM generator, paraphrase, and a two-judge panel (GLM + one cross-family judge) | 4.0 |
| Public-graph rebuilds, generator-swap replays (fixed plans), Qwen3.5-9B generator ablation | 1.3 |
| Downstream: zero-shot on all ~3,200 items x 10 OpenRouter models; held-out governed + few-shot | 4.4 |
| Public-graph rank agreement; refresh end to end with all-model misestimate | 1.6 |
| P2: schema scale (25 -> 150 labels), log-seeded generation | 1.8 |
| **Expected** | **about 14.5** |
| **Hard cap in the ledger** | **18 new** (with last night's $6.22, at most about $24.2) |

Assumes 50% cache hits for GLM. If Novita's discount ends mid-run, the GLM lines rise about 1.8x (about +$4.5). P2 is dropped first.

**gpt-6-luna** (OpenAI key, billed separately): independent judge audit, held-out downstream row, generator-swap replay, public-graph eval. Estimate about 10M input / 2M output tokens, about 1.3x last night.

## 5a. Revised budget (2026-11-12 19:10Z; superseded by 5b: the owner asked to keep full prompts and the full pipeline)

Facts from the v2 ledger:

- Input tokens were 82% of GLM generation cost ($3.26 input vs $0.71 output): long prompts were re-sent on every call.
- v2 used about 7 GLM calls per accepted item (19,053 calls for 2,609 accepted).

Observed cost per 1,000 calls: Gemma-4-26B-A4B $0.024, Gemma-3-4B $0.050, gpt-oss-20b $0.055, Qwen3.5-9B $0.068, Gemma-3-12B $0.084, Mistral-Small $0.091, Phi-4 $0.093, Qwen3-Coder $0.101, GLM-5.3-Flash $0.174, Llama-3.1-8B $0.276 (BF16-only providers).

Changes:

1. **Template-first generation.** GLM writes each template's question *and* parameterized Cypher once. Each item reuses that Cypher with values bound by the outcome-aware binding query. Per item, only a paraphrase call and the judge panel remain. The Cypher is also checked once per template, so literal errors drop.
2. **A model per stage.**
   - GLM only for template writing: about 400 calls, where quality matters most.
   - Paraphrase: Gemma-4-26B or GLM, whichever the pilot shows keeps values and reads well.
   - Judge panel: gpt-oss-20b + Gemma-4-26B, chosen by calibration. Neither is from the generator's family, which also answers C1.
   - If the cheap judges calibrate poorly, GLM joins the panel (+$0.8).
3. **Schema slices** in the template-writing prompt. Input tokens dominate cost.
4. **Zero-shot on all items** uses the 8 cheapest open models (not GLM or Llama). All 11 models still run on the held-out test.
5. **Pay as you go.** Runs pause at the cap instead of dying, so no large contingency is needed upfront.

| Item | OpenRouter $ |
| --- | ---: |
| Template writing (GLM, ~400 calls) | 0.6 |
| Paraphrase (~4,000) | 0.1-0.7 |
| Judge panel (2 cheap judges x ~4,000) | 0.5 |
| Calibration + pilot | 0.2 |
| Public-graph rebuilds | 0.2 |
| Generator-swap replays + Qwen 9B ablation | 0.2 |
| Qwen3.5-9B independent audit judge | 0.3 |
| Held-out downstream (10 open models x ~300 x 3 conditions) | 1.2 |
| Zero-shot on all ~3,200 items (8 cheapest models) | 1.8 |
| Public-graph rank agreement | 0.5 |
| Refresh misestimate (all models) | 0.5 |
| Schema-scale experiment, reduced (P2) | 0.5 |
| **Expected total** | **about 6-7** |
| **Ask: add $10 credit; raise the key limit to $20** (about $1 of room is left on $10) | |

gpt-6-luna drops to about 8M input / 1.5M output tokens, about the same as last night: judge audit, held-out downstream, generator-swap replay, public-graph eval. It no longer runs zero-shot on all items.

## 5. Budget, first estimate (superseded by 5a)

| Item | Calls (approx.) | OpenRouter $ |
| --- | ---: | ---: |
| Judge calibration (3 judges x 150 items x <= 4 prompt versions) | 1,800 | 0.5 |
| Pilot | 1,500 | 0.4 |
| Main generation, 3,200 items (generator + paraphrase + 2-judge panel; harder items yield less) | 25,000 | 7-9 |
| Public-graph rebuilds (3 x ~150) | 3,000 | 1.0 |
| Generator-swap replays + Qwen 9B ablation | 3,000 | 0.7 |
| Third independent judge (Qwen) on all judged candidates | 5,000 | 0.4 |
| Downstream held-out (~300 x 3 conditions x 10 open models) | 9,000 | 1.5 |
| Downstream zero-shot on all ~3,200 items x 10 open models | 32,000 | 5.0 |
| Public-graph rank agreement (10 x ~450) | 4,500 | 0.6 |
| Refresh misestimate (11 models x 3 migrations x ~150) | 5,000 | 1.0 |
| Schema-scale experiment (P2) | 6,000 | 2-3 |
| **Subtotal** | | **20-23** |
| Contingency (about 50%) | | 10 |
| **(Superseded by 5a: add $10 credit, key limit $20)** | | |

**gpt-6-luna (OpenAI)** totals about 13M input and 2.3M output tokens, roughly 1.8x last night's usage (about 7.5M in / 1.4M out):

| Use | Calls | Tokens (in / out) |
| --- | ---: | --- |
| Judge audit | ~4,500 | 4.7M / 0.9M |
| Downstream | ~3,900 | 6M / 1M |
| Generator-swap replay | ~800 | 1M / 0.15M |
| Calibration | ~600 | 0.6M / 0.1M |
| Public-graph eval | ~450 | 0.5M / 0.1M |

The local Mac runs cost nothing, but the machine must stay awake overnight (`caffeinate`).

## 6. Expected Limitations after v3

The remaining items are scope statements, not defects:

- public proxy graphs (no proprietary tenant deployment);
- Neo4j 5 dialect;
- read-only subset;
- the redaction audit is not a PII classifier;
- human validation covers a 200-item stratified sample (with CI);
- schema scale is shown on merged and replicated public graphs (if P2 runs), or is stated as untested.

## 7. Pilot go/no-go (G1)

The pilot runs every experiment at small scale before any money goes to the full run. Each criterion is checked by a script, and the result is written to `experiments/snapshots/<v3>/pilot_audit.json`.

| Check | Pass if | v2 value |
| --- | --- | --- |
| Empty-result rejects | < 5% of candidates | 24% |
| Ties at the LIMIT cutoff; ids bound as k; question/Cypher literal mismatches | 0 in accepted items | 65; 3; not checked |
| Tier mix | within 10 points of 35/35/30, with no planned (category, tier) cell empty | 134/81/1 |
| Panel judges agree | kappa >= 0.6 on the calibration set and on pilot items | 0.22 |
| Spot check (30 pilot items, read by Claude) | <= 2 wrong references | n/a |
| Self-BLEU of questions | < 0.81 (the v1 level) | 0.87 |
| Redaction residual | <= 1% | 1.0% |
| Cost per accepted item | full run projects under the cap | $0.0012 |
| Forced cap test | run pauses, resumes, and stays balanced | stopped; 482 items discarded |
| Downstream harness | all models return predictions on pilot items; failure rate 0 | 0 after the 404 fix |
| Refresh, generator-swap and labeling harnesses | run end to end on pilot items | n/a |

If a check fails, fix it and rerun the pilot (budgeted twice). If the second pilot also fails, fall back to v2 for that component.

## 8. v2 limitations and drawbacks -> v3 fix

| v2 limitation or drawback | v3 fix | Paper evidence after v3 |
| --- | --- | --- |
| Judges disagreed (kappa 0.22), no human labels, so no reference error rate | Shared convention sheet; checklist judge; two cross-family judges as the gate; gpt-6-luna as auditor; 200 human labels | Reference error rate with CI; judge-human and judge-judge kappa; v2-vs-v3 prompt ablation |
| 65 tied references; 3 ids bound as k | Tie gate, rank-slot bound, literal-consistency gate turned on | Gate counts in the funnel; 0 in the release |
| Half of rejects were empty (generic slot lookup) | Outcome-aware binding from each template's own Cypher | Empty rate and yield, v2 vs v3 |
| Heuristic found 1 hard test item | Structural score calibrated on v2 solve rates; (category, tier) quotas | Tier counts; solve rate falls monotonically by tier on fresh v3 items |
| One phrasing register (self-BLEU 0.87) | Five registers; least-similar paraphrase kept | Self-BLEU and distinct-n, v2 vs v3 |
| Budget stop cut generation; 482 accepted items discarded | Per-stage caps, pause-and-resume, round-robin cells, shared counters | Full 3,200 built; cost per item |
| 9B generator "far less diverse"; GLM needs multi-GPU | Qwen3.5-9B through the fixed pipeline on a 400-item slice | Yield, diversity, quality, rank agreement for 9B vs GLM |
| One local T2C fine-tune | Two Neo4j T2C fine-tunes on the Mac (MLX), native + standard prompts, on all items | Rows in the downstream table |
| Categories are a planner scaffold; no logs | Log-seeded generation from T2C-2024 train questions (P2) | Category distribution, seeded vs planned |
| 100+ label schemas untested | Merged and replicated schema, 25 -> 150 labels (P2) | Yield, cost, tokens, judge pass vs schema size |
| Refresh measured staleness after migrations, but incremental regeneration was only planned | Refresh executed end to end on v3 FinBench | Cost and time vs full rebuild; misestimate for all models |
| Public graphs only; Neo4j 5; read-only subset; redaction audit is not a PII classifier | Stays as scope | Limitations (scope only) |

## 9. Progress log

**2026-11-12 22:00Z**
- **Done, with tests (620 tests pass):**
  - parameterized template Cypher;
  - outcome-aware binding: pattern-derived candidates, each verified by executing the template's own query, with no unverified fallback;
  - literal-consistency gate;
  - deterministic gates run before the paid judge;
  - template-Cypher fallback and agreement metadata;
  - convention sheet (fork; `pipecypher/conventions.py`, C1-C13);
  - calibrated difficulty score and tier quotas with reported spillover (fork; `configs/difficulty_v3.json`);
  - style-diverse realization;
  - cache-ordered v3 prompts;
  - Novita FP8 configs (`configs/{finbench,snb}_v3.yaml`) with request seeds;
  - pause-on-cap ledger;
  - per-cell launcher (`scripts/launch_v3_build.sh`);
  - pilot audit (`scripts/audit_v3_pilot.py`);
  - generator-swap replay with fixed plans (`scripts/replay_generator_swap.py`);
  - human labeling page (fork): https://claude.ai/artifact/Bav54TnLQZziuAJtPRaCGc.
- **v2 literal-consistency audit** (`artifacts/naacl_results/literal_consistency/`):
  - 222 of 2,080 items flagged (10.7%): 163 malformed quoted ids (bug in id-slot phrasing, now fixed), 38 with an unstated LIMIT k, 24 with unfilled placeholders, 11 with unbound slot names.
  - Held-out test: 30 of 216 items flagged. Dropping them changes no model by more than 5.2 points; zero-shot tau 1.0 / 0.96, few-shot tau 0.85. Median accuracy on flagged items: 0.27 vs 0.38 overall.
- Schema-derived top-k templates now state k, and degenerate "scoped" rankings are dropped under v3.
- **Blocked:** jamming needs a Tailscale SSH browser re-auth from the owner.
- **Owner request:** an appendix arguing that the results transfer to tenant deployments. Draft: `paper_naacl2027_industry/appendix_tenant_deployment.tex`, with v3 placeholders. Limitations keeps one scope sentence that points to it.

**2026-11-12 22:20Z: judge v3 integrated**
- **Provider equivalence:** Z.AI vs Novita kappa 0.73 / 0.82, the same range as Novita vs Novita (0.72). The provider switch is safe.
- **Calibration** (150 disagreement-oversampled v2 items vs Claude adjudication):
  - v2 prompt: kappa 0.14.
  - v3 checklist: GLM 0.67.
  - **Panel GLM + Gemma-4-26B: 0.73**, agreement 0.87 [0.80, 0.91], 15 false accepts / 5 false rejects.
  - Agreement between the two panel judges: kappa 0.50-0.61, to be re-measured on pilot items.
  - Frozen contract hash a4b55edc...; see `experiments/snapshots/20261113_naacl_v3/judge_v3_calibration.md`.
- **Wired in:**
  - `scripts/run_pipeline.py::build_judge` delegates to `pipecypher.judge.build_judge`, and the v3 configs carry `judge.mode: checklist` plus the Gemma panel member.
  - v3 generation and template prompts follow C4 (entity vs instance counts) and C10 (explicit self-exclusion).
  - New hard gate `structural defect` (`deterministic_judge_notes`): it flags 16 v2 SNB items, all real (reversed HAS_CREATOR inside NOT EXISTS; variables dropped at WITH).
- **Still blocked:** jamming Tailscale re-auth.

**2026-11-13 02:10Z: full build launched (after one restart)**
- Key limit raised by the owner to $40 (account credit $35; $25.25 available at launch).
- First launch (01:59Z, prefixes `naacl_v3_main`, `naacl_v3_t2c`, `naacl_v3_qwen9b`) aborted at 02:07Z after ~$0.6:
  template-generation and induction replies were truncated at `max_tokens=2048` (GLM spent 1.2-1.9k
  reasoning tokens on hard categories), the JSON failed to parse, and induction silently returned
  nothing. SNB s2 path_temporal exited at 8/75 and hard items were at 9% of accepted.
  Fix: `PipeCypherPipeline._template_json` gives template calls 3x the per-call budget and retries a
  truncated reply once at 4x (test `test_template_calls_get_headroom_and_truncation_is_retried`;
  630 tests pass). Aborted runs: `artifacts/runs_superseded/20261113_template_budget/`.
- Relaunched 02:08Z on code tree `29bcf41a…` (see `logs/<prefix>/launch_manifest.txt`):
  - `naacl_v3_full`: FinBench 125 + SNB 75 per category x seeds 1, 2 (32 cells, cap $7).
  - `naacl_v3_pub`: recommendations / northwind / fincen, 20 per category, seed 1 (24 cells, cap $1.5).
  - `naacl_v3_gen9b`: Qwen3.5-9B generator, FinBench + SNB, 25 per category, seed 1 (16 cells, cap $1.5).
- Gemma-2-9B base re-downloaded (first attempt failed on the HF xet CDN with 403); LoRA merge running.
- `scripts/run_downstream_parallel.sh`: Mac launcher for the downstream suite (keys from the
  environment, no tmux, no env file).

**2026-11-13 05:45Z: all v3 experiments complete except human labels**
- Results: `experiments/snapshots/20261113_naacl_v3/status.md`; numbers in `artifacts/naacl_results/v3_results.json`.
- Paper rewritten for v3 (`paper_naacl2027_industry/main.tex`). The main body ends on page 6. The only remaining
  placeholders are the human-label numbers (abstract and Sec. 5.2) and the human-results table in Appendix E.
- P2 schema scale done as a wide-schema stress test (132 labels; Appendix "Wide-Schema Stress Test"). The
  log-seeded generation run was dropped.
- Spend: OpenRouter new spend about $11.4 (key usage $21.2 at 05:30Z); gpt-6-luna is on the owner's OpenAI credits.
- Human labeling page live with v3 items (set id `v3`); labeling window 16:00-21:00Z.
- Readback once labels are in: ArtifactData query on collection `labels` with set_id `v3`, then
  `scripts/read_human_labels.py --labels <dump> --key artifacts/human_validation_v3/v3/key.jsonl --output-dir artifacts/human_validation_v3/v3/results`.
