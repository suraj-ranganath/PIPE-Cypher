# NAACL 2027 v2 Experiment Status

Started 2026-11-12 (UTC 08:30). Host: `jamming` (Tailscale; 32 cores, 125 GB RAM;
CPU only; its RTX 4090 belongs to another job and was not used). All LLM calls go to
hosted endpoints; graph execution is local Neo4j 5.26 Community bound to 127.0.0.1.

## Owner decisions (2026-11-11/12)
- No GPU access (ds-serv6 key revoked). Generator and primary judge: **GLM-5.3-Flash**
  (`z-ai/glm-5.3-flash`, open weights `zai-org/GLM-5.3-Flash`, MIT, 321B params,
  released in FP8). Accessed through OpenRouter, **pinned to Z.ai's own FP8 endpoint**
  (`provider.order=["z-ai/fp8"], allow_fallbacks=false, require_parameters=true`).
  No FP4/NVFP4 or unknown-precision endpoints ("no quantized versions").
- Reasoning is mandatory for GLM-5.3-Flash (`effort:"none"` returns HTTP 400). We use
  `effort:"low"`, with reasoning text excluded from responses.
- gpt-6-luna (OpenAI, hosted) is used as (a) independent frontier judge, (b) swap
  generator for the self-preference slice, and (c) downstream frontier reference.
  Public graphs only. It rejects `temperature=0`, so the provider default is used.
- Downstream open-weight models run at their released precision: BF16 endpoints, or the
  vendor's official FP8 release (Qwen3-Coder-30B-A3B).
- Budget: OpenRouter key limit $10; about $7.25 remaining at start. A spend ledger
  with a shared hard cap (`PIPE_CYPHER_MAX_COST_USD`) guards every hosted call.

## Graphs (jamming, loopback only)
| Graph | Bolt | Nodes | Rels | Notes |
| --- | --- | ---: | ---: | --- |
| SNB (LDBC interactive test data) | 7688 | 34,735 | 70,842 | identical to v1 |
| FinBench SF0.1 (datagen e32675a) | 7687 | (pending) | (pending) | regenerated; v1: 10,006 / 57,622 |
| T2C recommendations / northwind / fincen | 7701-7703 | | | pinned dumps; live schemas show no drift vs the dataset schema |

## Verified facts
- SNB `KNOWS` direction check (30 persons): directed 2-hop reach 352 vs undirected
  1,920; 24/30 persons miss friends under directed traversal. v1's 140 directed
  `KNOWS` references under-returned. v2 declares `KNOWS` symmetric.
- T2C-2024 anchor: 596 test rows -> 569 after the reference audit (25 empty, 2
  execution failures). The oracle self-check scores 1.000 once references and
  predictions are both executed as written. An earlier 0.954 was an evaluator
  asymmetry (normalized `RETURN DISTINCT` on the reference only), fixed in
  `pipecypher/evaluation.py`.

## E0.1: re-scoring v1 predictions with the fixed evaluator (DB only)
Valid June predictions on the v1 test split (296 items), scored by
`scripts/evaluate_benchmark_predictions.py` (outputs in
`artifacts/evaluations/naacl_v1_rescore/` on jamming):

| Model (v1 test) | Strict EX | Projected EX | Exec. success |
| --- | ---: | ---: | ---: |
| Qwen3.5-9B zero-shot | 0.189 | 0.486 | 0.696 |
| Neo4j Gemma-2 T2C LoRA zero-shot | 0.203 | 0.449 | 0.892 |
| Qwen2.5-Coder-7B zero-shot | 0.007 | 0.007 | 0.794 |
| Qwen3.5-9B few-shot (same-category, ordered) | 0.993 | 0.997 | 1.000 |
| Qwen2.5-Coder-7B few-shot | 0.983 | 0.990 | 1.000 |

More than half of v1's apparent zero-shot failures were the context-column artifact.
Qwen2.5-Coder's failure is real: it reverses relationship directions, and its
queries execute but return nothing. Few-shot at about 0.99 reflects v1's
template-copying.

## Pilots (engineering only; not paper evidence)
- pilot_glm_snb (target 5): 40/111 accepted. Found unbound LLM-template slots,
  extra answer columns, "within N hops" written as exactly N, quoted numeric IDs.
- Fixes: schema-aware slot typing; `require_slot_bindings`; prompt rules for
  requested columns only, `*1..N` for "within N hops", undirected symmetric types,
  no added quotes; id slots phrased as "<label> with id <value>"; unique slot
  properties.
- pilot2_glm_snb (target 5): 40/56 accepted (8 categories). 0 fallback-judge
  acceptances, 0 tracebacks, all calls served by Z.AI FP8.

## Runs
| Run prefix | Config | Target | Status |
| --- | --- | --- | --- |
| naacl_v2_snb | configs/snb_v2_glm.yaml | 125/cat | running (started 08:59:36Z) |
| naacl_genswap_snb | configs/snb_v2_genswap_gpt6luna.yaml | 25/cat | running |
| naacl_anchor (gpt6_luna) | T2C-2024 audited test, zero_pipe_standard | 569 | running |
| naacl_v2_finbench | configs/finbench_v2_glm.yaml | 4 shards x 63/cat, shard quota 2 | running (relaunched ~09:25Z) |
| naacl_genswap_finbench | configs/finbench_v2_genswap_gpt6luna.yaml | 25/cat | running |
| naacl_t2c_{recommendations,northwind,fincen} | configs/t2c_*_glm.yaml | 15/cat | running (E3.5 ranking agreement) |
| refresh copy | FinBench copy on bolt 7697 + pristine dump | n/a | setup running |

FinBench was regenerated with the pinned datagen (SF0.1). It is identical to v1:
10,006 nodes, 57,622 relationships, and the same per-label counts.

The first FinBench main launch (one process per category, quota 8) ran at about 0.6
accepted items per minute per category, which is too slow for 250 per category. It
was stopped after about 50 items. Those records are kept under
`artifacts/runs_superseded/` and **excluded** from the export. FinBench was
relaunched with 4 shards per category. Each shard has its own seed, a binding
offset of `shard*53`, and a per-shard signature quota of 2, so the global quota is
at most 8 per signature, the same as SNB. Export dedups identical questions across
shards.

### Budget event (about 09:40Z)
Generation processes had read the spend cap of $4.80 at launch. The cap was later
raised to $6.90 in the env file, but only for new processes. When the early
evaluation tracks (anchor, generator-swap eval, public-graph PIPE eval) pushed the
shared ledger past $4.80, every generation process stopped cleanly with
`BudgetExceededError`. No item was degraded; accepted records up to that point are
valid. OpenRouter had $2.36 remaining (key limit $10).

Counts at the stop:
- SNB: 939 accepted (cells 90-152).
- FinBench: 1,529 accepted (cells 111-252).

Decision: run small top-ups for the short cells only, under the $6.90 cap. These are
`naacl_v2_snbt` (SNB complex_retrieval), `naacl_v2_snbu` (SNB boolean/ranking), and
`naacl_v2_finbencht` (FinBench simple_retrieval/path_temporal). Then export with
balanced caps of SNB 110/cell and FinBench 150/cell (2,080 items).

Launch manifests (config sha256, code-tree sha256, UTC time) are in
`logs/<prefix>/launch_manifest.txt` on jamming. The code tree is uncommitted, so the
tree hash stands in for a git revision.


## Final status (2026-11-12, about 10:30Z): all planned runs complete

### Benchmark v2 (exported)
- `artifacts/benchmarks/naacl_v2_random`: 2,080 items. FinBench 8 x 150, SNB 8 x 110.
  Caps: at most 8 per signature globally (14 items dropped); balanced cells (482 dropped).
  1,312 unique signatures.
- `artifacts/benchmarks/naacl_v2_heldout`: same items, signature-disjoint split.
  Test has 216 items in 132 signatures, 0 shared with train (dev: 2).
- Generation yield, main runs: 5,031 candidates, 2,609 accepted, 0 accepted via the
  rule-based fallback. Cost $3.23; 18,405 calls; median latency 3.1 s; 09:00-09:54Z.
- Diversity v1 -> v2: 123 -> 1,312 signatures; 36 -> 712 families; top-10 share
  67% -> 3.8%; Distinct-2 0.085 -> 0.236; sampled self-BLEU-2 0.81 -> 0.87 (worse);
  hard tier 0 -> 16 items (0.8%).
- Generator-swap slice `naacl_v2_genswap_gpt6luna`: 395 items. SNB complex_retrieval
  reached 20/25; the run was stopped at the time limit.
- Public-graph PIPE benchmarks: recommendations 120, northwind 120, fincen 109.
  FinCEN path_temporal has only 4 items because the graph has few multi-hop patterns.

### Validity
- Self-preference (projected EX, DiD with signature-cluster CI):
  - GLM: -0.002 [-0.085, 0.077], placebo p=0.91.
  - gpt-6-luna: -0.008 [-0.098, 0.077], placebo p=0.45.
- Rank agreement vs curated T2C-2024 (11 models, projected EX):
  - recommendations tau 0.87 [0.64, 0.92];
  - northwind 0.82 [0.60, 0.91];
  - fincen 0.76 [0.52, 0.82];
  - all p < 0.001. Strict EX gives tau 0.57-0.64.
- Judges (2,483 items):
  - Pass rates: gpt-6-luna 60.1%, Qwen3.5-9B 84.1%, GLM 83.8%.
  - Flags on the 2,080 accepted items: gpt-6-luna 609, Qwen 261, both 143.
  - Agreement: gpt-6-luna vs Qwen kappa 0.22.
- Robustness: dropping the 143 items flagged by both judges leaves the zero-shot
  ranking unchanged (tau 1.00). Keeping only items gpt-6-luna accepts gives tau 0.96
  (few-shot 0.89). See `artifacts/naacl_results/judge_filter_robustness.json`.
- Judge-slice bug: `schema_slice_for_cypher` dropped `symmetric_relationships`.
  Fixed after the runs; 24 gpt-6-luna flags cite KNOWS direction.

### Downstream (v2 held-out test, 216 items)
- Zero-shot projected EX: median 0.352, IQR [0.29, 0.50], range 0.153-0.644.
- Governed prompt: median 0.403. Gemma-3-12B collapses to 0.074 because it copies
  the `Label.property` rule notation.
- Few-shot (no shared signature): median 0.569, range 0.39-0.72.
- Neo4j T2C Gemma-3-4B (local MLX, native prompt): 0.176 strict / 0.347 projected.
  With the standard PIPE prompt: 0.167 strict / 0.287 projected (0 request failures;
  `artifacts/evaluations/naacl_v2_heldout_local_neo4j_gemma3_t2c/standard_summary.json`).
- Anchor (curated T2C-2024, 569 rows, oracle 1.000): hosted median 0.33 projected.
  gpt-6-luna 0.515, GLM 0.489, T2C Gemma-3-4B native 0.506.

### Post-build determinism audit (2026-11-12, after all runs)
- `scripts/audit_limit_ties.py` reran every v2 reference that has ORDER BY ... LIMIT n
  with LIMIT n+1 and compared order keys at the cutoff (`pipecypher/limit_ties.py`).
- 283 of 2,080 items have ORDER BY ... LIMIT. All 283 were checkable (0 unresolved).
  65 tie at the cutoff (FinBench 45, SNB 20; ranking_topk 62/260); 53 of them are
  LIMIT 1.
- 3 items (2 train, 1 held-out test) bind an entity id as the k of "top k" (for
  example, "Which 175358910490739502 loans have the highest balance?"). An
  LLM-induced template's reverse query returned an id column aliased `k`, and the GLM
  judge passed it.
- Held-out test: 9 tied plus 1 malformed. Dropping these 10 moves no model by more
  than 2.1 pp projected EX. Ranking tau versus the full test set: zero-shot 0.96,
  governed 1.00, few-shot 1.00. Medians: 0.352 -> 0.345, 0.403 -> 0.393, 0.569 -> 0.549.
- Fixes, both off by default and not active in the reported build:
  - `generation.reject_limit_boundary_ties`;
  - `generation.max_rank_slot_value` (rank slots must bind to an integer in 1..bound).

  Both appear as commented lines in the v2 configs, ready for the next build.
- Artifacts: `artifacts/naacl_results/limit_ties/{summary.json,items.jsonl,rescore_heldout.json}`.

### Refresh (1,200 v2 FinBench items, copy on bolt 7697)

| Change | Broken | Silently changed | Now empty |
| --- | ---: | ---: | ---: |
| M0 identity | 0 | 0 | 0 |
| M1 rename TRANSFER_TO | 306 | | |
| M2 rename isBlocked | 463 | 5 | |
| M3 Merchant relabel | | 89 | 27 |
| M4 drop GUARANTEE | 88 | | |
| D1 delete 10% transfers | | 137 | 8 |
| D2 add 5% transfers | | 110 | 3 |

- Of the 306 M1-broken items, Neo4j returned 172 empty, 101 changed, and 33 unchanged
  (no errors).
- Accuracy misestimate (Qwen3.5-9B strict, 123 FinBench test items): after M1, stale
  0.228 vs refreshed 0.146 (+8.1 pp); after M2, +0.8 pp; after D1, 0.

### Privacy
- Redaction audit: the default string-only policy leaves 924/7,740 values (11.9%)
  because of numeric ids. With numeric literals redacted: 81 (1.0%), almost all
  schema identifiers. v2 configs now set `redact_numeric_literals: true`.

### Spend
- OpenRouter total $6.22 of the $7.25 available ($10 key limit).
  - Generation (incl. pilots, superseded run, genswap judge, t2c): $4.07.
  - Evaluation: $1.94.
  - Qwen judge: $0.21.
- OpenAI gpt-6-luna: about 10.7M tokens. The API does not report cost; check the
  OpenAI dashboard.

### Not done
- Human validation labels. Packets are prepared in `artifacts/human_validation_v2/`:
  200 stratified items and 2 annotator sheets.
- Re-exporting v2 without the 65 tied and 3 malformed items. The gates now exist (see the
  determinism audit), but the paper reports the build as run, with the robustness check.
- 100+ label schema stress test.
- T2C fine-tunes other than Neo4j Gemma-3-4B: not hosted anywhere, and jamming's GPU
  was occupied by another user.

All artifacts were copied from jamming into this repo (`artifacts/benchmarks/naacl_*`,
`artifacts/evaluations/naacl_*`, `artifacts/judges/`, `artifacts/refresh_v2*`,
`artifacts/naacl_results/`, `logs/naacl_jamming/`). The spend ledger is
`artifacts/naacl_results/spend_ledger.jsonl`; it holds no keys.

Cleanup (2026-11-12): `~/.pipecypher_env` deleted on jamming; Neo4j instances on jamming
stopped (restart with `scripts/start_neo4j_community.sh`); local MLX server stopped.
