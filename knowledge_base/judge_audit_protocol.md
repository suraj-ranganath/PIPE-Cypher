# Judge Audit Protocol

Date: June 1, 2026.

This protocol turns the sampled audit CSV into a reproducible post-hoc calibration check for the LLM-judge gate. Human labels are not part of dataset generation; they are used only to estimate judge reliability for the paper.

## Audit File

Current full-run audit packet:

```text
artifacts/audits/20260601_full_qwen9b_judge_audit_v2.csv
```

The file has 80 rows: 40 judge-accepted and 40 judge-rejected candidates sampled from the full Qwen3.5-9B generation artifacts. The current v2 packet is stratified by judge outcome first, then graph/category coverage within each outcome. It contains 48 FinBench rows, 32 SNB rows, and all eight benchmark categories. The older `artifacts/audits/20260601_full_qwen9b_judge_audit.csv` packet is retained locally but lacked graph coverage in the CSV, so v2 should be used for paper calibration.

## Labeling Rule

Fill `human_accept` with one of:

- `true`: the natural-language question is clear, the Cypher is read-only, schema-grounded, directionally plausible, and semantically answers the question.
- `false`: the pair is ambiguous, uses the wrong schema element, reverses an important relationship direction, mismatches an exact literal, returns inadequate context columns, is unsafe, or otherwise should not appear in the benchmark.

Use `human_notes` for a short reason when `human_accept=false`, or when a row is borderline. Do not edit `graph_profile`, `judge_accept`, `question`, `cypher`, `category`, or `difficulty`.

## Review Checklist

For each row, inspect:

1. Does the question have a single reasonable Cypher interpretation?
2. Does the query use only labels, relationship types, and properties from the intended graph profile?
3. Are quoted values matched exactly rather than fuzzily or by substring?
4. Are relationship directions consistent with the schema and question wording?
5. Are result columns useful for an enterprise analyst, not just opaque internal nodes?
6. Does the query avoid write, admin, or non-read operations?
7. If the judge rejected the row, is the failure reason actually valid?

## Analysis Command

Before labels are filled, this command should report `labeled_rows=0`:

```bash
python scripts/analyze_judge_audit.py \
  --audit artifacts/audits/20260601_full_qwen9b_judge_audit_v2.csv
```

To render a local browser review packet with radio buttons and a label CSV download:

```bash
python scripts/render_judge_audit_packet.py \
  --audit artifacts/audits/20260601_full_qwen9b_judge_audit_v2.csv \
  --output-html artifacts/audits/20260601_full_qwen9b_judge_audit_v2.html \
  --output-json experiments/snapshots/20260601_live_full_qwen9b/judge_audit_packet_v2.json \
  --output-tex paper_emnlp2026_industry/tables_judge_audit_coverage.tex
```

After labels are filled, require labels and save the output:

```bash
python scripts/analyze_judge_audit.py \
  --audit artifacts/audits/20260601_full_qwen9b_judge_audit_v2.csv \
  --require-labels \
  > artifacts/audits/20260601_full_qwen9b_judge_audit_v2_metrics.json
```

Report coverage by graph/category/difficulty plus `total_labeled`, agreement rate, judge precision, judge recall, judge specificity, negative predictive value, balanced accuracy, Cohen's kappa, false accepts, and false rejects in the paper. The strongest paper claim is not that the judge is perfect, but that the pipeline is automated and the post-hoc audit makes judge risk visible.
