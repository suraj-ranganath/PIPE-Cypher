# EMNLP Industry Paper Directory

Target: EMNLP 2026 Industry Track.

Core claim: PIPE-Cypher is a local-model, execution-grounded, Cypher-specific pipeline for generating private enterprise NL-to-Cypher benchmarks.

Files:

- `paper.md`: current paper draft for rapid editing.
- `main.tex`: ACL/EMNLP-style LaTeX draft skeleton.
- `references.bib`: working references.
- `tables_*.tex`: current method, experiment, full-generation, export, diversity, distribution, ablation, and downstream tables.
- `figures/*.pdf`: appendix-ready ablation, diversity, export-distribution, and downstream-evaluation figures.
- `main.pdf`: compiled local draft when LaTeX is available.

Citation provenance is tracked in `../knowledge_base/citation_verification.md`; no placeholder citations are currently present in `references.bib`.

Regenerate artifact-derived result tables with:

```bash
python ../scripts/render_paper_artifact_tables.py \
  --benchmark-dir ../artifacts/benchmarks/20260601_live_full_qwen9b \
  --evaluation-summary ../artifacts/evaluations/20260601_full_qwen9b_test_summary.json \
  --paper-dir .
```

Regenerate the target-five FinBench+SNB ablation table with:

```bash
python ../scripts/render_ablation_paper_table.py \
  ../artifacts/runs/20260601_182730_20260601_ablation5_finbench_unconstrained_local_llm_strict \
  ../artifacts/runs/20260601_182553_20260601_ablation5_finbench_reverse_only \
  ../artifacts/runs/20260601_182551_20260601_ablation5_finbench_validators_repair \
  ../artifacts/runs/20260601_182245_20260601_ablation5_finbench_ablation_retrieval_topk_0 \
  ../artifacts/runs/20260601_182417_20260601_ablation5_finbench_ablation_rewrite_false \
  ../artifacts/runs/20260601_182549_20260601_ablation5_finbench_ablation_judge_false \
  ../artifacts/runs/20260601_182058_20260601_ablation5_finbench_full_pipe_cypher \
  ../artifacts/runs/20260601_183657_20260601_ablation5_snb_unconstrained_local_llm \
  ../artifacts/runs/20260601_183656_20260601_ablation5_snb_reverse_only \
  ../artifacts/runs/20260601_183655_20260601_ablation5_snb_validators_repair \
  ../artifacts/runs/20260601_183401_20260601_ablation5_snb_ablation_retrieval_topk_0 \
  ../artifacts/runs/20260601_183527_20260601_ablation5_snb_ablation_rewrite_false \
  ../artifacts/runs/20260601_183653_20260601_ablation5_snb_ablation_judge_false \
  ../artifacts/runs/20260601_183236_20260601_ablation5_snb_full_pipe_cypher \
  --target-per-category 5 \
  --output tables_ablation5_results.tex
```

Regenerate the diversity table and appendix figures from the project root:

```bash
python scripts/analyze_benchmark_diversity.py \
  --benchmark artifacts/benchmarks/20260601_live_full_qwen9b/all.jsonl \
  --schema configs/schema_finbench.json \
  --schema configs/schema_snb.json \
  --output-json experiments/snapshots/20260601_live_full_qwen9b/diversity_report.json \
  --output-tex paper_emnlp2026_industry/tables_diversity.tex

python scripts/render_paper_figures.py \
  --diversity-report experiments/snapshots/20260601_live_full_qwen9b/diversity_report.json \
  --benchmark-stats artifacts/benchmarks/20260601_live_full_qwen9b/stats.json \
  --downstream-summary artifacts/evaluations/20260601_full_qwen9b_test_summary.json \
  --output-dir paper_emnlp2026_industry/figures
```

Current caveat: the paper is structurally complete for serious revision and now includes the 3,000-example full FinBench/SNB benchmark export, full-test Qwen3.5-9B downstream evaluation, live target-five FinBench/SNB ablation suites, and diversity diagnostics. Judge calibration labels and full-scale ablations remain pending.
