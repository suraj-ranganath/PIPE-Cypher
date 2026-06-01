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

## Reviewer-Defensible Calibration Design

The audit is a calibration sample, not a hidden generation stage. Accepted and
rejected candidates are both present so the paper can estimate false accepts and
false rejects instead of only checking accepted examples. The v2 packet should
remain frozen for the first reported calibration run; do not resample after
seeing labels unless the paper explicitly reports the first packet as a pilot
and declares a new packet before labeling.

Preferred labeling design:

1. Use two independent annotators when possible. Each annotator should label the
   same `human_accept` decision without seeing the other annotator's label.
2. Annotators may see `judge_accept` because the audit evaluates judge agreement,
   but the paper must state this. If a blinded variant is run later, keep it as a
   separate audit file and report it separately.
3. Disagreements should be adjudicated into a final `human_accept` label only
   after recording the original labels in a separate sidecar file. Do not replace
   the raw individual labels without preserving them.
4. Rows should be judged against the schema and execution sample available to the
   pipeline, not against assumptions about the data generator that are absent
   from the candidate record.

Minimum acceptable paper evidence:

- all 80 rows labeled, or an explicit reason and coverage table if any row is
  excluded;
- coverage by graph, category, difficulty, strategy, and judge decision;
- agreement rate, precision, recall, specificity, negative predictive value,
  balanced accuracy, Cohen's kappa, false accepts, and false rejects;
- a short failure taxonomy for false accepts and false rejects.

Claims that remain invalid until labels exist:

- "the LLM judge is reliable";
- "human audit confirms semantic correctness";
- "judge calibration improves generation quality."

The defensible claim before labels are complete is narrower: the benchmark
generation gate is automated, and the repository includes a frozen post-hoc
audit packet and analysis tooling that will expose judge risk.

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
