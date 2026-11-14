# NAACL 2027 v3: run status and results log

Plan: `knowledge_base/naacl2027_v3_plan.md`. Every row names its artifacts. Item-level files are
PRIVATE (questions, Cypher literals, result values).

## Builds (launched 2026-11-13 02:08Z, code tree 29bcf41a…, `logs/<prefix>/launch_manifest.txt`)

| Prefix | What | Cells | Target | Cap | Status |
| --- | --- | ---: | --- | ---: | --- |
| `naacl_v3_full` | FinBench + SNB, seeds 1 and 2 | 32 | 125 / 75 per category per seed | $7 | running |
| `naacl_v3_pub` | recommendations / northwind / fincen, seed 1 | 24 | 20 per category | $1.5 | done 02:20Z: 160 / 160 / 160 |
| `naacl_v3_gen9b` | Qwen3.5-9B generator, FinBench + SNB, seed 1 | 16 | 25 per category | $1.5 | running |

Aborted first launch (template replies truncated at 2048 tokens): `artifacts/runs_superseded/20261113_template_budget/README.txt`.

## Public-graph rank agreement (v3 build vs curated Text2Cypher-2024 anchor; 11 models; projected EX)

Exports `artifacts/benchmarks/naacl_v3_pub_{g}` (160 items each). Evaluations
`artifacts/evaluations/naacl_v3_pubeval_{g}_downstream_<slug>/` (all 33 runs: 0 prediction failures).
Anchor evaluations are reused unchanged from v2 (`naacl_anchor_downstream_<slug>`).

| Graph | tau (11 models) | tau without generator | concordant pairs | tau strict | v2 tau |
| --- | ---: | ---: | ---: | ---: | ---: |
| Recommendations | 0.764 | 0.756 | 0.87 | 0.564 | 0.855 |
| Northwind | 0.782 | 0.778 | 0.89 | 0.564 | 0.818 |
| FinCEN | 0.655 | 0.622 | 0.82 | 0.582 | 0.745 |

(Point estimates from a quick script; final numbers with clustered CIs come from
`scripts/collect_naacl_v3_results.py`.) GLM (generator) scores highest on all three generated sets
(0.76 / 0.93 / 0.84) but is just behind gpt-6-luna on the curated rows; in v2 it was also first on
Recommendations. Self-preference is tested directly by the fixed-plan generator swap.

## Main build `naacl_v3_full` (done 03:27Z)

- 32 cells, 02:08Z-03:27Z. 24 ran to completion (EXIT=0): 21 at target and 3 short (SNB s1 path_temporal 48/75,
  SNB s2 negation_difference, SNB s2 ranking_topk). SNB s1 path_temporal ended at 48/75:
  induced templates had no slot value with a non-empty answer ("slot bindings unavailable"),
  so they were retired, and induction stopped after 6 rounds.
- 03:25Z: the 8 unfinished cells were stopped at a fixed time budget (EXIT=143; `launch_manifest.txt`).
  They were churning on full tier quotas, with the spillover point at 750 of 1,000 attempts. Finishing
  them would have cost about 2.5 h and $2.4, mostly for medium items after spillover. Every accepted item was kept.
  At the stop: boolean s1 109/125, negation s1 93, ranking s1 124, simple_agg s1 112, negation s2 79,
  path s2 122, ranking s2 120, SNB complex_retrieval s2 70/75.
- Candidates 5,617; accepted 3,042; exported 3,038 (`artifacts/benchmarks/naacl_v3_full`,
  signature-disjoint split, seed `naacl-v3`): train 2,355 / dev 341 / test 342.
  FinBench 1,882 / SNB 1,156. Seed halves: 1,511 / 1,527.
- Tiers: easy 1,065 (35%) / medium 1,104 (36%) / hard 869 (29%); the target is 35/35/30.
- Export audits (`experiments/snapshots/20261113_naacl_v3/naacl_v3_full/`): LIMIT ties 0 of 571 ordered-limit
  references; literal-consistency flags 0 of 3,038; redaction residual in `redaction.json`.
- Spend $3.50 (ledger `naacl_v3_full_spend.jsonl`).
- Diversity vs v2: 919 vs 1,312 signatures; per-cell min 19 vs 19, median 53.5 vs 74.5; top-10 share 4.3% vs 3.8%;
  483 vs 712 template families; Distinct-2 0.187 vs 0.236; EAD-Distinct-2 0.728 vs 0.696.

## Qwen3.5-9B generator ablation `naacl_v3_gen9b` (done 02:58Z)

- 2,297 candidates, 325 accepted (14%); target 400. Most cells ended below 25. Spend $1.14.
- Template-contract pass rate 30% (GLM 87%; collector). Export `artifacts/benchmarks/naacl_v3_gen9b`:
  180 signatures, top-10 share 23%; 0 literal flags.

## Question normalization (03:30Z)
- 160 exported questions had a duplicated id phrase ("with companyId company with id 42"). The export now
  normalizes them (`pipecypher.benchmark_export.normalize_id_phrasing`; ids unchanged; the original wording is
  stored in `question_normalization`). The root cause (`pipeline._phrase_id_slot`) is fixed and tested.
- The downstream runs that started on the old wording were stopped. They were relaunched with
  `PIPE_CYPHER_REUSE_PREDICTIONS=1`, which reuses a stored prediction only when the question text is identical
  (about 11.6k reused).

## Downstream (all 3,038 items, zero-shot standard; 11 models; 0 prediction failures)
- Projected EX ranges 0.21 to 0.77, median 0.43. Medians by tier: easy 0.70, medium 0.42, hard 0.15.
  All 11 models fall strictly from easy to medium to hard.
- Held-out test (342): zero-shot median 0.41; governed 0.42 (hurts 8 of 11); few-shot 0.58 (helps 11 of 11).
- Local fine-tunes (MLX BF16, held-out): Gemma-3-4B T2C std 0.39 (native: rerun pending);
  Gemma-2-9B T2C native 0.30 strict 0.23.
  - The first Gemma-2 pass returned `<end_of_turn>` as text. Its predictions were re-extracted from the
    stored raw outputs (`scripts/reclean_predictions.py`).
- Full results: `artifacts/naacl_results/v3_results.json` (`scripts/collect_naacl_v3_results.py`).

## Validity
- Generator swap on 400 fixed plans: gates and panel pass for GLM 98.0%, gpt-6-luna 97.3%, Qwen 96.3%.
  Same answer as the released reference: 98% / 97% / 99%. Common set: 375 items.
- Self-preference DiD (projected EX): GLM own vs gpt-6-luna refs +0.004 [-0.061, 0.061], placebo p 0.36;
  GLM vs Qwen refs +0.001 [-0.063, 0.061]. gpt-6-luna own -0.001; Qwen own +0.002.
- Stability between seed halves: tau 0.89 [0.82, 1.00], strict 0.95, 95% of pairs concordant.
- gpt-6-luna audit (3,238 panel-judged; 91 truncated replies re-audited at 4,096 tokens):
  - flags 21.8% of accepted (easy 11.5 / medium 20.1 / hard 36.5%); panel agreement 79%, kappa 0.27.
  - On the 150 adjudicated calibration items: agreement 0.86, kappa 0.71, false accepts 3, false rejects 18.
  - Rogan-Gladen corrected error rate: 0% [0, 7.3%].

## Refresh (v3 FinBench, 1,882 items; copy on jamming 7697)
- Broken / silent: M1 29.9 / 1.4%; M2 22.8 / 0; M3 0 / 14.0%; M4 9.6 / 0; D1 0 / 15.9%; D2 0 / 12.6%; M0 0 / 0.
- M1: 562 broken references (376 empty, 165 changed, 21 unchanged; no errors). The rename rewrite keeps 557 of 562 answers.
- Misestimate after M1 (11 models, stale-schema predictions): stale minus refreshed accuracy is +10.5 to +22.9 pp,
  median +17.5 pp. Stale-vs-refreshed rank tau 0.89.
- M4 incremental regeneration: 180 items (232 candidates) on the migrated copy in 4,484 s on one sequential worker
  (75 worker-minutes), $0.161, 934 calls (`naacl_v3_refresh_spend.jsonl`; timing in
  `artifacts/refresh_v3/m4_drop_guarantee/audit/regeneration/regeneration_timing.tsv`). Full FinBench build: $2.06 and
  950 worker-minutes (sum of first-to-last record time per FinBench cell), so the refresh used about 8% of each.

## Wide-schema stress test (`naacl_v3_wide`; jamming 7720)
- Five public graphs x 4 namespaced replicas in one database: 132 labels, 148 types, 372 patterns,
  328,652 nodes, 1,354,796 relationships (`scripts/build_wide_schema_graph.py`).
- Schema prompt about 6,200 tokens. 135 candidates -> 80 accepted (59%); 8/8 cells at target; 8 min; $0.17
  ($2.13 per 1,000). Template contract 59% (32 of 36 rejections: property on the wrong label).
- Domains: Rec 34, Fc 26, Nw 11, Fin 8, Snb 1. 0 accepted queries mix namespaces.

## Human validation
- Sample: 200 items (`artifacts/human_validation_v3/v3/`). Queues A and B have 130 items each, 60 shared.
  FinBench 113 / SNB 87; easy 54 / medium 61 / hard 85.
- Page republished 04:15Z: https://claude.ai/artifact/Bav54TnLQZziuAJtPRaCGc (set id `v3`).

## Calibrated tiers for v1/v2/v3 (Table 3)
`experiments/snapshots/20261113_naacl_v3/calibrated_tiers.json`: `configs/difficulty_v3.json` applied to each
export's reference Cypher.
- v1 `20260604_live_full_qwen9b_reviewfix`: 889 / 1,781 / 330.
- v2 `naacl_v2_heldout`: 679 / 854 / 547.
- v3 `naacl_v3_full`: 1,068 / 1,104 / 866 (the export's own tier field: 1,065 / 1,104 / 869).

## Independent review (06:00Z) and fixes
- Generator-swap retrieval could show sibling items' GLM references. Re-run with signature-held-out retrieval
  (`--exclude-same-signature`) into `artifacts/naacl_v3/genswap_sigout/`.
- The Rogan-Gladen-corrected auditor error rate (0% [0, 7%]) was dropped because it is degenerate: the flag rate is
  below the auditor's false-reject rate.
- Wide-schema items audited by gpt-6-luna: 23 of 80 flagged (29%).
- Numeric fixes: cell counts, pair shares, Gemma-3-4B T2C rounding, and the matched 9B comparison (78%).
