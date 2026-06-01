# Completion Audit

Status: goal is not complete yet.

## Evidence Already Present

- Clean repo scaffold with package, configs, scripts, tests, docs, experiment matrix, and paper directory.
- Deterministic tests pass: `108 passed`.
- Offline smoke runs prove the CLI path, built-in FinBench and SNB reference schemas, deterministic validation, contextual return warnings, mock execution, deterministic judge, JSONL logging, strategy tags, and summary metrics.
- LDBC FinBench SF0.1 has been generated on `ds-serv6`, transformed to snapshot CSVs, and loaded into a user-space Neo4j Community 5.26 smoke database.
- The loaded FinBench smoke graph contains 10,006 nodes and 57,622 relationships.
- Live FinBench schema introspection produced `configs/schema_finbench.json`.
- `Qwen/Qwen3.5-9B` has been served through vLLM on `ds-serv6` and used for a live LLM-judged FinBench smoke run.
- The live run `artifacts/runs/20260601_122841_live_finbench_qwen9b_defaultslots` accepted 4/4 examples with graph-backed slot values and non-empty Neo4j execution.
- The live run `artifacts/runs/20260601_124531_live_finbench_qwen9b_8cat_seeded` accepted 8/8 examples across all planned FinBench categories, with four easy and four medium examples.
- LDBC SNB official Cypher test-data has been converted and loaded into a second user-space Neo4j Community instance on Bolt port 7688.
- The loaded SNB smoke graph contains 34,735 nodes and 70,842 relationships.
- Live SNB schema introspection produced `configs/schema_snb.json`.
- The live run `artifacts/runs/20260601_124201_live_snb_qwen9b_ids_template` accepted 4/4 examples with graph-backed slot values, non-empty Neo4j execution, and Qwen judge JSON.
- The live run `artifacts/runs/20260601_135706_live_snb_qwen9b_8cat_seeded_fixed` accepted 8/8 examples across all planned SNB categories after fixing ambiguous complex-aggregation wording.
- `LLMJudge` now slices schema context per candidate Cypher, which avoids Qwen3.5-9B smoke endpoint context-limit failures on the larger live SNB schema.
- `artifacts/audits/20260601_live_snb_qwen9b_judgeslice_audit.csv` is a deduplicated judge-calibration sample with blank human labels.
- Live mini-ablation runs are recorded:
  - `artifacts/runs/20260601_133302_live_finbench_llm_only_probe_generic_scan_tag`: 0/16 accepted, with 16/16 `generic_node_scan` validation warnings.
  - `artifacts/runs/20260601_132232_live_finbench_mixed_mini_full_coverage`: 16/29 accepted.
  - `artifacts/runs/20260601_130456_live_snb_mixed_mini_diverse`: 8/8 accepted.
  - `artifacts/runs/20260601_135706_live_snb_qwen9b_8cat_seeded_fixed`: 8/8 accepted across all planned categories.
  - `artifacts/runs/20260601_140632_20260601_midscale_finbench`: 40/46 accepted, five accepted examples in every planned category.
  - `artifacts/runs/20260601_140855_20260601_midscale_snb`: 40/47 accepted, five accepted examples in every planned category.
- A materialized FinBench+SNB target-five ablation suite is recorded in `knowledge_base/target5_ablation_results.md` and rendered as `paper_emnlp2026_industry/tables_ablation5_results.tex`. The strict unconstrained local-LLM baseline produced 0/0 records on both graphs without seeded template fallback; reverse-only, validators+repair, no-retrieval, no-rewrite, no-LLM-judge, and full PIPE-Cypher all reached 5 accepted examples in all eight categories on both FinBench and SNB.
- `artifacts/benchmarks/20260601_live_all_category_mini` exports 24 accepted examples with stable IDs, train/dev/test JSONL splits, stats, a manifest hash, and exactly three accepted examples in every planned category across FinBench+SNB.
- `artifacts/benchmarks/20260601_live_midscale` exports 80 accepted examples with stable IDs, train/dev/test JSONL splits, stats, a manifest hash, and ten accepted examples in every planned category across FinBench+SNB.
- The EMNLP draft compiles with `pdflatex`/`bibtex`; generated PDF: `paper_emnlp2026_industry/main.pdf`.
- Downstream Text2Cypher artifacts are recorded in `knowledge_base/downstream_evaluation.md`; local Qwen3.5-9B reached 0.189 execution accuracy and answer F1 on the 296-example full exported test split, with 0.622 execution success.
- `knowledge_base/model_availability.md` records that `Qwen/Qwen3.5-35B-A3B` exists remotely and has now been staged under `/home/suraj/pipecypher-models/Qwen3.5-35B-A3B`; `Qwen/Qwen3.5-9B` and `BAAI/bge-m3` are cached.
- `scripts/check_vllm_capacity.py` and `pipecypher/gpu_capacity.py` estimate whether a staged model can be served with currently safe GPUs; the script now supports `--remote` for local-to-`ds-serv6` checks. The latest June 1, 2026 35B check found 68,573 MiB of safetensor weights, four required A5000 GPUs under the conservative vLLM budget, and only GPU 3 safely free; details are in `knowledge_base/qwen35b_capacity_snapshot_20260601.md`, with tracked JSON evidence at `experiments/snapshots/qwen35b_capacity_20260601_latest.json`.
- Full-run launch and monitoring scripts now exist: `scripts/run_live_full_generation.sh`, `scripts/launch_live_full_generation_tmux.sh`, and `scripts/monitor_generation_run.py`.
- Full-run finalization scripting now exists: `scripts/finalize_live_full_run.sh` exports the benchmark, samples a judge-audit packet, and optionally runs downstream Text2Cypher evaluation after FinBench and SNB full runs complete.
- Full-run recovery scripting now exists: `scripts/fill_missing_categories.py` counts unique accepted examples in existing run artifacts and launches category-specific top-up runs for any underfilled category. It supports multiple passes, and each pass counts earlier top-up outputs before deciding what is still missing.
- Full-run auto-finalization scripting now exists: `scripts/auto_finalize_full_run_after_main.sh` waits for the main sequential tmux run, launches patched multi-pass FinBench/SNB top-ups for missing categories, and finalizes the combined benchmark with the top-up run directories included.
- The full Qwen3.5-9B fallback benchmark is exported at `artifacts/benchmarks/20260601_live_full_qwen9b` with exactly 3,000 accepted examples, 2,000 FinBench examples, 1,000 SNB examples, 375 examples per category, 2,408/296/296 train/dev/test splits, and manifest hash `8bc79a53a06b291a81974d7859d1a02d013c1e7dfc401e447b2897259aeaa47c`.
- A tracked lightweight full-export snapshot now exists at `experiments/snapshots/20260601_live_full_qwen9b` with the export manifest hash, file-level SHA-256 checksums, aggregate stats, and 16 representative examples selected by stable ID, one for each FinBench/SNB graph-category cell.
- Diversity diagnostics now exist at `experiments/snapshots/20260601_live_full_qwen9b/diversity_report.json`, with Distinct-n, sampled self-BLEU-2, query-signature diversity, normalized entropy, schema coverage, and structural feature rates. The paper appendix includes `paper_emnlp2026_industry/tables_diversity.tex` plus `figures/diversity_diagnostics.pdf`, `figures/ablation_acceptance.pdf`, `figures/full_export_distribution.pdf`, and `figures/downstream_breakdown.pdf`.
- The final full export has 3,000/3,000 accepted examples passing read-only, syntax, schema, execution, and judge gates; the judge audit packet is `artifacts/audits/20260601_full_qwen9b_judge_audit.csv` with 80 sampled rows plus header.
- `scripts/render_paper_artifact_tables.py` regenerates paper tables for benchmark export, distribution/gate summary, and downstream Text2Cypher results directly from `stats.json`, `manifest.json`, and the evaluation summary.
- `knowledge_base/citation_verification.md` records the verified source for every paper bibliography entry used by the EMNLP/arXiv draft; no unverified placeholder citations remain in `paper_emnlp2026_industry/references.bib`.
- `knowledge_base/judge_audit_protocol.md` defines the human calibration labeling rubric. `scripts/analyze_judge_audit.py` now reports audit coverage and exits non-zero with `--require-labels` when no labels are complete.
- Benchmark export now deduplicates accepted examples by graph, category, and normalized question text before assigning stable example IDs, preventing equivalent recovery-run duplicates from entering the released benchmark.
- Relationship-direction validation now handles both outgoing and incoming Cypher arrow syntax. It accepts `(:A)<-[:R]-(:B)` only when the schema contains `(:B)-[:R]->(:A)`, rejects reversed incoming patterns, and rejects untyped or undirected relationship patterns as benchmark-invalid.
- Categorical property validation now rejects generated Cypher that uses unsupported schema-provided enum-like values in node maps or `WHERE` predicates. The tracked FinBench schema records categorical values for `Account.accountType`, `Company.business`, and `Medium.mediumType`; a full-export check found zero categorical-value violations among existing FinBench examples.
- FinBench negation/difference seeds now include additional company- and account-scoped slotted templates, raising theoretical seed capacity for that category from 302 to 1202 under the full config.
- Slot binding now skips bindings whose filled question is already present in `--seen-records`, so patched top-up runs do not waste early attempts replaying accepted examples from the original run.
- FinBench ranking/top-k seeds now include additional company-, person-withdrawal-, and account-type-scoped templates, raising theoretical seed capacity for that category from 302 to 1202 under the full config.
- SNB negation/difference seeds now include person-neighborhood and tag-scoped forum anti-join templates, raising theoretical seed capacity for that category from 201 to 601 under the full config.
- The ACL-style submission draft now exists at `paper_emnlp2026_industry/main_acl.tex`, with `acl.sty` and `acl_natbib.bst` staged locally.
- `knowledge_base/emnlp_industry_requirements.md` records the EMNLP 2026 Industry Track constraints checked on June 1, 2026.
- `scripts/stage_qwen35b_model.sh` exists, and `Qwen/Qwen3.5-35B-A3B` has been staged under root-backed storage.
- The pipeline now tries each template once before random reuse, cycles reverse-query slot bindings, rejects duplicate accepted questions, and includes a second SNB ranking seed to prevent duplicate no-slot accepted examples.
- Reverse slot binding now uses the configured generation limit rather than a hard-coded 10-row execution cap; `scripts/estimate_seed_capacity.py` shows that the full FinBench and SNB configs have enough built-in seed capacity for their per-category targets.
- Built-in FinBench schema is grounded in `external/ldbc_finbench_datagen/transformation/snapshot.sql`, including real node/relationship directions and typed properties.
- Built-in SNB schema is grounded in `external/ldbc_snb_interactive_v1_impls/cypher/scripts/headers.txt` and the official Cypher query files.
- `scripts/generate_finbench_import_cypher.py` generates a Neo4j `LOAD CSV` script that preserves transaction multiedges with relationship `CREATE`.
- LDBC FinBench and SNB source repositories have been fetched and commit hashes recorded.
- `scripts/check_gpu_host.py` confirms SSH access to `ds-serv6` and current GPU/storage state.
- `scripts/materialize_experiments.py` creates concrete baseline/ablation configs and commands. `configs/generated/finbench` now contains 15 runnable configs, `configs/generated/snb` contains 14 runnable configs, all 29 generated configs load through `load_config`, and `knowledge_base/ablation_materialization.md` records the materialized baseline, retrieval, judge, rewrite, model, and graph-mix suite.
- The detached full-generation fallback run on `ds-serv6` completed, and final run/export/downstream status is recorded in `knowledge_base/full_run_status.md`.
- The default boolean templates now use clearer `OPTIONAL MATCH` boolean checks rather than counting matched subject variables; this patch was copied to `ds-serv6` before the sequential SNB run starts, and remote compile/template checks passed.
- The template scheduler now avoids random reuse of exhausted no-slot templates after their exact question has already been accepted, reducing duplicate-question waste in high-target categories.
- Paper draft has abstract, introduction, related work with verified citations, method, implementation, experiments, limitations, ethics, conclusion, and references.
- `knowledge_base/codex_goal_prompt.md` preserves the reusable `/goal` prompt for continuing the project in future Codex threads, with outcome, verification surface, constraints, and work loop.

## Missing For Full Goal Completion

- Qwen3.5-9B has been used for live FinBench/SNB smokes, mini-ablation, an 80-example mid-scale generation/evaluation run, and the full 3,000-example fallback benchmark.
- Qwen3.5-35B-A3B has been staged locally, but it has not yet been served successfully through vLLM or used for generation/judging because the latest capacity check found only one safely free A5000 GPU and four required under the current serving budget.
- Full-scale baselines and ablations have not yet been run on live graphs. The repo now has mini-ablation evidence, mid-scale generation evidence, and a materialized FinBench+SNB target-five ablation suite, but not full 3,000-example ablations for every setting.
- Full downstream Text2Cypher model evaluation has completed on the 296-example full test split.
- Judge calibration CSV tooling exists, the full-run audit packet has 80 sampled rows, and the labeling protocol is documented, but no completed human labels yet.
- Paper results tables now contain full-generation, full-export, and full downstream test numbers; judge human-label calibration remains pending.

## Smallest Next Step

1. Fill human labels for `artifacts/audits/20260601_full_qwen9b_judge_audit.csv`, then run `scripts/analyze_judge_audit.py`.
2. Start and smoke-check a `Qwen/Qwen3.5-35B-A3B` vLLM endpoint from `/home/suraj/pipecypher-models/Qwen3.5-35B-A3B`, or explicitly finalize the study as a 9B fallback study.
3. Update the paper tables with judge calibration metrics and any larger ablation yields.
