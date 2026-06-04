# EMNLP Industry Paper Directory

Target: EMNLP 2026 Industry Track.

Canonical submission source: `main_acl.tex`. Treat `main.tex` and `paper.md`
as convenience mirrors only after the canonical source is stable.

Core claim: PIPE-Cypher is a local-model, execution-grounded, Cypher-specific
pipeline for generating private enterprise NL-to-Cypher benchmarks.

Page accounting: for the EMNLP Industry submission, the counted main paper is
at most 6 pages and `Conclusion` must end by the end of page 6. `Limitations`,
ethical considerations, references, and appendices are excluded from this
limit. The appendix should carry full ablations, diversity diagnostics, failure
analysis, graph/category breakdowns, judge calibration material,
reproducibility details, and examples.

## Build and Audit

From the project root:

```bash
cd paper_emnlp2026_industry
latexmk -pdf -interaction=nonstopmode main_acl.tex
cd ..
python scripts/audit_emnlp_page_budget.py \
  --pdf paper_emnlp2026_industry/main_acl.pdf
python scripts/audit_paper_evidence_provenance.py
python scripts/verify_submission_package.py \
  --paper-tex paper_emnlp2026_industry/main_acl.tex \
  --evidence-manifest experiments/snapshots/20260604_review_remediation/clean_qwen9b_submission_evidence_manifest.json \
  --records \
    artifacts/runs/20260601_142318_20260601_full_qwen9b_finbench \
    artifacts/runs/20260601_165047_20260601_full_qwen9b_snb \
    artifacts/runs/20260604_131025_20260604_qwen9b_reviewfix_finbench_negation_difference \
    artifacts/runs/20260604_132554_20260604_qwen9b_reviewfix_snb_4096_negation_difference \
    artifacts/runs/20260604_134817_20260604_qwen9b_reviewfix_snb_negation_extra \
    artifacts/runs/20260604_132921_20260604_qwen9b_reviewfix_snb_path_2048 \
    artifacts/runs/20260604_133010_20260604_qwen9b_reviewfix_snb_ranking_2048 \
  --approved-model Qwen/Qwen3.5-9B
```

## Clean Evidence Namespace

Use `artifacts/benchmarks/20260604_live_full_qwen9b_reviewfix` or a later
manifest that passes the approved-model provenance guard. The older June 1
export name is not acceptable for final paper evidence because its source
lineage included larger-model top-ups.

Paper-facing clean summaries currently live under:

- `experiments/snapshots/20260604_review_remediation/`
- `experiments/snapshots/20260604_diversity_governed_target50_reviewfix/`
- `experiments/snapshots/20260604_clean_downstream_model_transfer/` after the
  clean downstream rerun finishes and is collected.

Do not promote partial or sampled runs into the main paper or appendix.
Research-quality reported results need complete run directories, logs, code
revision or manifest evidence, model IDs, graph workloads, audit status, and
enough scale or uncertainty analysis to be reviewer-defensible.

## Rerender Core Tables

```bash
python scripts/render_paper_artifact_tables.py \
  --benchmark-dir artifacts/benchmarks/20260604_live_full_qwen9b_reviewfix \
  --evaluation-summary artifacts/evaluations/20260604_clean_downstream_qwen35_9b_zero_fewshot/zero_shot_summary.json \
  --downstream-errors experiments/snapshots/20260604_clean_downstream_model_transfer/downstream_error_report.json \
  --failure-taxonomy experiments/snapshots/20260604_review_remediation/failure_taxonomy.json \
  --paper-dir paper_emnlp2026_industry
```

## Rerender Diversity and Governance Evidence

```bash
python scripts/analyze_benchmark_diversity.py \
  --benchmark artifacts/benchmarks/20260604_live_full_qwen9b_reviewfix/all.jsonl \
  --schema configs/schema_finbench.json \
  --schema configs/schema_snb.json \
  --output-json experiments/snapshots/20260604_review_remediation/diversity_report.json \
  --output-tex paper_emnlp2026_industry/tables_diversity.tex

python scripts/audit_gate_impact.py \
  --records \
    artifacts/runs/20260601_142318_20260601_full_qwen9b_finbench \
    artifacts/runs/20260601_165047_20260601_full_qwen9b_snb \
    artifacts/runs/20260604_131025_20260604_qwen9b_reviewfix_finbench_negation_difference \
    artifacts/runs/20260604_132554_20260604_qwen9b_reviewfix_snb_4096_negation_difference \
    artifacts/runs/20260604_134817_20260604_qwen9b_reviewfix_snb_negation_extra \
    artifacts/runs/20260604_132921_20260604_qwen9b_reviewfix_snb_path_2048 \
    artifacts/runs/20260604_133010_20260604_qwen9b_reviewfix_snb_ranking_2048 \
  --output-json experiments/snapshots/20260604_review_remediation/gate_impact.json \
  --output-tex paper_emnlp2026_industry/tables_gate_impact.tex

python scripts/audit_redaction_policy.py \
  --benchmark artifacts/benchmarks/20260604_live_full_qwen9b_reviewfix/all.jsonl \
  --output-json experiments/snapshots/20260604_review_remediation/redaction_audit.json \
  --output-tex paper_emnlp2026_industry/tables_redaction_audit.tex
```

## Rerender Downstream Controls

After all clean downstream run directories exist under `artifacts/evaluations/`
with the `20260604_clean_*` prefix, build the control summaries and figures:

```bash
python scripts/build_downstream_control_manifest.py
python scripts/summarize_downstream_fewshot_controls.py \
  --zero-run-dir artifacts/evaluations/20260604_clean_downstream_<model>_zero_fewshot \
  --control-run-dir artifacts/evaluations/20260604_clean_control_<model>_ordered_logged \
  --control-run-dir artifacts/evaluations/20260604_clean_control_<model>_scored_no_signature \
  --control-run-dir artifacts/evaluations/20260604_clean_control_<model>_random_seed13 \
  --control-run-dir artifacts/evaluations/20260604_clean_control_<model>_random_seed17 \
  --control-run-dir artifacts/evaluations/20260604_clean_control_<model>_random_seed23 \
  --output-json experiments/snapshots/20260604_clean_downstream_model_transfer/fewshot_control_summary.json \
  --output-md experiments/snapshots/20260604_clean_downstream_model_transfer/fewshot_control_summary.md \
  --output-tex paper_emnlp2026_industry/tables_downstream_fewshot_controls.tex
```

Use all completed local-model run directories, not the literal `<model>`
placeholder above. The same clean summaries should then feed
`render_downstream_transfer_controls.py`,
`render_downstream_fewshot_control_uncertainty.py`,
`render_fewshot_leakage_controls.py`, and `render_paper_figures.py`.

## Figure Style

All matplotlib figures should import `pipecypher.paper_style` and use its
shared palette, graph colors, metric colors, and sequential/quality colormaps.
Figure 1's TikZ colors are kept in the same palette. Regenerate vector PDFs
after style changes and visually inspect the first six pages plus appendix
figure pages before submission.
