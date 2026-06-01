# EMNLP Industry Paper Directory

Target: EMNLP 2026 Industry Track.

Core claim: PIPE-Cypher is a local-model, execution-grounded, Cypher-specific pipeline for generating private enterprise NL-to-Cypher benchmarks.

Page accounting: for the EMNLP Industry submission, the counted main paper is at most 6 pages and `Conclusion` must end by the end of page 6. `Limitations`, ethical considerations, references, and appendices are excluded from this limit. The appendix should carry full ablations, diversity diagnostics, failure analysis, graph/category breakdowns, judge calibration material, reproducibility details, and examples.

Files:

- `paper.md`: current paper draft for rapid editing.
- `main.tex`: ACL/EMNLP-style LaTeX draft skeleton.
- `references.bib`: working references.
- `tables_*.tex`: current method, experiment, full-generation, export, diversity, failure-taxonomy, judge-audit, distribution, downstream evaluation, and downstream uncertainty tables.
- `appendix_claim_evidence.tex`, `appendix_prompt_contracts.tex`, and `appendix_example_cards.tex`: generated appendix material for claim/evidence traceability, prompt contracts, and representative accepted benchmark examples.
- `figures/*.pdf`: appendix-ready diversity, failure-taxonomy, export-distribution, and downstream-evaluation figures.
- `main.pdf`: compiled local draft when LaTeX is available.

Citation provenance is tracked in `../knowledge_base/citation_verification.md`; no placeholder citations are currently present in `references.bib`.

Regenerate artifact-derived result tables with:

```bash
python ../scripts/render_paper_artifact_tables.py \
  --benchmark-dir ../artifacts/benchmarks/20260601_live_full_qwen9b \
  --evaluation-summary ../artifacts/evaluations/20260601_full_qwen9b_test_summary.json \
  --paper-dir .
```

From the project root, regenerate downstream-evaluation uncertainty intervals
from the full row-level evaluation artifact:

```bash
python scripts/analyze_evaluation_uncertainty.py \
  --evaluation artifacts/evaluations/20260601_full_qwen9b_test_eval.jsonl \
  --output-json experiments/snapshots/20260601_live_full_qwen9b/downstream_uncertainty.json \
  --output-md experiments/snapshots/20260601_live_full_qwen9b/downstream_uncertainty.md \
  --output-tex paper_emnlp2026_industry/tables_downstream_uncertainty.tex \
  --iterations 2000 \
  --seed 13
```

Target-five and smaller ablations are engineering sanity checks, not paper
results. Target-25 is an interim checkpoint. Do not include
`tables_ablation5_results.tex`, `tables_smoke.tex`, `tables_mini_results.tex`,
or `tables_midscale_results.tex` in the paper. Run a scaled ablation suite from
the project root before adding ablation tables:

```bash
SESSION=pipecypher_ablation50_qwen9b \
TARGET_PER_CATEGORY=50 \
PYTHON_BIN=/home/suraj/pipecypher-tools/runtime-venv/bin/python \
GENERATION_MODEL=Qwen/Qwen3.5-9B \
JUDGE_MODEL=Qwen/Qwen3.5-9B \
RUN_PREFIX=20260601_ablation50_qwen9b \
  scripts/launch_live_ablation_suite_tmux.sh
```

Use `TARGET_PER_CATEGORY=25` only as an interim scaled checkpoint. Treat
`TARGET_PER_CATEGORY=50` as the minimum paper-readiness threshold, not the ideal
scale. Prefer `TARGET_PER_CATEGORY=100`, repeated target-50 suites, or another
scale-equivalent design for final appendix claims when the endpoint is stable
enough.

While a remote suite is running, inspect progress without copying partial
artifacts:

```bash
python scripts/monitor_remote_ablation_suite.py \
  --run-prefix 20260601_ablation50_qwen9b \
  --target-per-category 50 \
  --session pipecypher_ablation50_qwen9b
```

After the suite finishes, create a non-paper audit summary first. The audit
defaults to a target-50 minimum for paper-style reporting:

```bash
python scripts/collect_remote_ablation_suite.py \
  --run-prefix 20260601_ablation50_qwen9b \
  --target-per-category 50 \
  --wait-session pipecypher_ablation50_qwen9b \
  --poll-seconds 60
```

The collector fetches matching remote run directories from `ds-serv6`, copies
the remote log into `experiments/snapshots/<run_prefix>/remote_run.log`, and
writes `ablation_suite_summary.{json,md,csv}` plus
`ablation_suite_audit.{json,md}` and `collection_manifest.json` locally. The
manifest fingerprints fetched records, run summaries, summary/audit files, the
remote log, and any rendered paper ablation artifacts. If the run directories
are already local, the lower-level summary command is:

```bash
python scripts/summarize_live_ablation_suite.py \
  --glob 'artifacts/runs/*20260601_ablation50_qwen9b*' \
  --target-per-category 50 \
  --output-json experiments/snapshots/20260601_ablation50_qwen9b/ablation_suite_summary.json \
  --output-md experiments/snapshots/20260601_ablation50_qwen9b/ablation_suite_summary.md \
  --output-csv experiments/snapshots/20260601_ablation50_qwen9b/ablation_suite_summary.csv \
  --output-audit-json experiments/snapshots/20260601_ablation50_qwen9b/ablation_suite_audit.json \
  --output-audit-md experiments/snapshots/20260601_ablation50_qwen9b/ablation_suite_audit.md \
  --metadata run_prefix=20260601_ablation50_qwen9b \
  --metadata generation_model=Qwen/Qwen3.5-9B \
  --metadata judge_model=Qwen/Qwen3.5-9B \
  --metadata code_revision=<RECORDED_REVISION> \
  --metadata log_file=logs/20260601_ablation50_qwen9b.log
```

Only after the suite is complete and the audit reports `paper_ready=true`
should it be considered for manuscript reporting. For final claims, also check
whether the run is sufficiently scaled, graph-stratified, and accompanied by
failure analysis and uncertainty or variance evidence. Render accepted suites
into `tables_ablation_results.tex` and `tables_ablation_quality.tex`:

```bash
python scripts/summarize_live_ablation_suite.py \
  --glob 'artifacts/runs/*20260601_ablation50_qwen9b*' \
  --target-per-category 50 \
  --output-tex paper_emnlp2026_industry/tables_ablation_results.tex \
  --output-quality-tex paper_emnlp2026_industry/tables_ablation_quality.tex \
  --metadata run_prefix=20260601_ablation50_qwen9b \
  --metadata generation_model=Qwen/Qwen3.5-9B \
  --metadata judge_model=Qwen/Qwen3.5-9B \
  --metadata code_revision=<RECORDED_REVISION> \
  --metadata log_file=logs/20260601_ablation50_qwen9b.log
```

The matching ablation figure is also generated separately, not by the default
paper-figure script, so partial ablation evidence is not accidentally pulled
into the manuscript:

```bash
python scripts/render_ablation_suite_figure.py \
  --suite-summary experiments/snapshots/20260601_ablation50_qwen9b/ablation_suite_summary.json \
  --output paper_emnlp2026_industry/figures/ablation_suite_target50.pdf
```

Regenerate the diversity table and appendix figures from the project root:

```bash
python scripts/analyze_benchmark_diversity.py \
  --benchmark artifacts/benchmarks/20260601_live_full_qwen9b/all.jsonl \
  --schema configs/schema_finbench.json \
  --schema configs/schema_snb.json \
  --output-json experiments/snapshots/20260601_live_full_qwen9b/diversity_report.json \
  --output-tex paper_emnlp2026_industry/tables_diversity.tex

python scripts/analyze_failure_taxonomy.py \
  --records \
    artifacts/runs/20260601_142318_20260601_full_qwen9b_finbench \
    artifacts/runs/20260601_165047_20260601_full_qwen9b_snb \
    artifacts/runs/20260601_173836_20260601_full_qwen9b_finbench_fill_20260601_173235_negation_difference \
    artifacts/runs/20260601_173838_20260601_full_qwen9b_snb_fill_20260601_173235_negation_difference \
    artifacts/runs/20260601_173842_20260601_full_qwen9b_snb_fill_20260601_173235_path_temporal \
    artifacts/runs/20260601_173848_20260601_full_qwen9b_snb_fill_20260601_173235_ranking_topk \
  --output-json experiments/snapshots/20260601_live_full_qwen9b/failure_taxonomy.json \
  --output-tex paper_emnlp2026_industry/tables_failure_taxonomy.tex

python scripts/render_paper_figures.py \
  --diversity-report experiments/snapshots/20260601_live_full_qwen9b/diversity_report.json \
  --failure-taxonomy experiments/snapshots/20260601_live_full_qwen9b/failure_taxonomy.json \
  --benchmark-stats artifacts/benchmarks/20260601_live_full_qwen9b/stats.json \
  --downstream-summary artifacts/evaluations/20260601_full_qwen9b_test_summary.json \
  --output-dir paper_emnlp2026_industry/figures
```

Regenerate the judge-audit coverage table and local HTML review packet from the project root:

```bash
python scripts/render_judge_audit_packet.py \
  --audit artifacts/audits/20260601_full_qwen9b_judge_audit_v2.csv \
  --output-html artifacts/audits/20260601_full_qwen9b_judge_audit_v2.html \
  --output-json experiments/snapshots/20260601_live_full_qwen9b/judge_audit_packet_v2.json \
  --output-tex paper_emnlp2026_industry/tables_judge_audit_coverage.tex
```

Regenerate the appendix prompt contracts and representative accepted examples:

```bash
python scripts/render_appendix_material.py \
  --claim-map knowledge_base/claim_evidence_map.yaml \
  --output-claims paper_emnlp2026_industry/appendix_claim_evidence.tex \
  --examples experiments/snapshots/20260601_live_full_qwen9b/sample_examples.json \
  --output-prompts paper_emnlp2026_industry/appendix_prompt_contracts.tex \
  --output-examples paper_emnlp2026_industry/appendix_example_cards.tex \
  --max-examples 16
```

Current caveat: the paper is structurally complete for serious revision and now includes the 3,000-example full FinBench/SNB benchmark export, full-test Qwen3.5-9B downstream evaluation with bootstrap uncertainty intervals, diversity diagnostics, full-run failure taxonomy, judge-audit coverage, claim/evidence traceability, prompt contracts, and representative accepted examples. Judge calibration labels and scaled ablations remain pending. Do not promote partial ablation suites or sampled downstream evaluations into the main paper or appendix; research-quality reported results need complete run directories, logs, code revisions, model IDs, graph workloads, audit status, and enough scale or uncertainty analysis to be reviewer-defensible.
