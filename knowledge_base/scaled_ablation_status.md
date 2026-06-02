# Scaled Ablation Status

Date: June 2, 2026.

## Target-25 Suite

Status: complete on `ds-serv6`; local audit artifacts are tracked under `experiments/snapshots/20260601_ablation25_qwen9b_retry1/`.

Runtime metadata:

- run prefix: `20260601_ablation25_qwen9b_retry1`
- target per category: 25
- graphs: LDBC FinBench and LDBC SNB live Neo4j databases
- variants: `unconstrained_local_llm`, `reverse_only`, `validators_repair`, `ablation_retrieval_topk_0`, `ablation_rewrite_false`, `ablation_judge_false`, `full_pipe_cypher`
- generation model: `Qwen/Qwen3.5-9B`
- judge model: `Qwen/Qwen3.5-9B`
- recorded code revision: `2122a86e457a3c0039367a09290dde120c660d68`
- log: `/home/suraj/PIPE-Cypher/logs/20260601_ablation25_qwen9b_retry1.log`

Completed runs:

- all FinBench variants;
- all SNB variants.

Outcome summary:

- 14/14 expected graph/variant cells finished.
- `unconstrained_local_llm` produced 0 records on both graphs under strict no-fallback settings.
- every reverse-grounded or full pipeline variant reached 8/8 categories at the target of 25 accepted examples per category.
- acceptance rates were 0.966--1.000 on FinBench non-unconstrained variants and 0.990--1.000 on SNB non-unconstrained variants.

Audit artifacts:

- JSON: `experiments/snapshots/20260601_ablation25_qwen9b_retry1/ablation_suite_summary.json`
- Markdown: `experiments/snapshots/20260601_ablation25_qwen9b_retry1/ablation_suite_summary.md`
- Figure: `experiments/snapshots/20260601_ablation25_qwen9b_retry1/ablation_suite_target25.pdf`

SHA-256:

- `ablation_suite_summary.json`: `906a501b87f0d78dc6cc0fbd7e6dc2906bfb6a25b150b7381d019ed2b1853776`
- `ablation_suite_summary.md`: `d5848c5c91946d725ab062ebaeb45d6caebb7192599ced53e0d93a594b56e653`
- `ablation_suite_target25.pdf`: `fc398b5f2e31a3e2489d3bb89f59e667b52a6593e183454bb9c3b785bac20975`

Research-use note: target-25 is an interim scaled checkpoint, not final paper evidence. Use it for engineering diagnosis and planning only; paper claims should wait for an audited target-50-or-larger suite, preferably target-100 or repeated target-50 if compute allows.

## Target-50 Suite

Status: complete, collected locally, and paper-readiness audited. Local audit
artifacts are tracked under
`experiments/snapshots/20260601_ablation50_qwen9b/`.

Runtime metadata:

- run prefix: `20260601_ablation50_qwen9b`
- target per category: 50
- graphs: LDBC FinBench and LDBC SNB live Neo4j databases
- variants: `unconstrained_local_llm`, `reverse_only`, `validators_repair`, `ablation_retrieval_topk_0`, `ablation_rewrite_false`, `ablation_judge_false`, `full_pipe_cypher`
- generation model: `Qwen/Qwen3.5-9B`
- judge model: `Qwen/Qwen3.5-9B`
- recorded code revision: `b5d4898e4a5f5043c33114a7746e319590f38de1`
- log: `/home/suraj/PIPE-Cypher/logs/20260601_ablation50_qwen9b.log`

Outcome summary:

- 14/14 expected graph/variant cells finished.
- `unconstrained_local_llm` produced 0 records on both graphs under strict no-fallback settings.
- every reverse-grounded or full pipeline variant reached 8/8 categories at the target of 50 accepted examples per category.
- FinBench non-unconstrained variants accepted 400 examples each, with 400--429 generated records.
- SNB non-unconstrained variants accepted 400 examples each, with 402--406 generated records.
- Paper-readiness audit status: `paper_ready=true`.

Audit artifacts:

- JSON summary: `experiments/snapshots/20260601_ablation50_qwen9b/ablation_suite_summary.json`
- Markdown summary: `experiments/snapshots/20260601_ablation50_qwen9b/ablation_suite_summary.md`
- CSV summary: `experiments/snapshots/20260601_ablation50_qwen9b/ablation_suite_summary.csv`
- JSON audit: `experiments/snapshots/20260601_ablation50_qwen9b/ablation_suite_audit.json`
- Markdown audit: `experiments/snapshots/20260601_ablation50_qwen9b/ablation_suite_audit.md`
- Collection manifest: `experiments/snapshots/20260601_ablation50_qwen9b/collection_manifest.json`
- Copied remote log: `experiments/snapshots/20260601_ablation50_qwen9b/remote_run.log`

Rendered appendix artifacts:

- Results table: `paper_emnlp2026_industry/tables_ablation_results.tex`
- Quality table: `paper_emnlp2026_industry/tables_ablation_quality.tex`
- Figure: `paper_emnlp2026_industry/figures/ablation_suite_target50.pdf`

SHA-256 from the collection manifest:

- `figures/ablation_suite_target50.pdf`: `922d9ef1b5ed51744fade3fef59a09286e7857d8ab9233e8ee7fe53da787a8f7`
- `tables_ablation_quality.tex`: `7134fd5f99547872fc2656825bd88f97acbf542757ab30eda119b787f16c694b`
- `tables_ablation_results.tex`: `47b5269f4695d235a5b2c9690851645c0bf3eb5fbea75e51927454241296deeb`

Research-use note: target-50 is now acceptable appendix evidence after
claim/evidence audit, but it should not be treated as the final scale ceiling.
The target-100 and seeded target-50 follow-up suites remain important for
stronger reviewer-facing reliability and variance claims.

Collection command used:

```bash
python scripts/collect_remote_ablation_suite.py \
  --remote-root /home/suraj/PIPE-Cypher \
  --run-prefix 20260601_ablation50_qwen9b \
  --target-per-category 50 \
  --wait-session pipecypher_ablation50_qwen9b \
  --poll-seconds 60 \
  --render-paper
```

Launch command:

```bash
CODE_REVISION=b5d4898e4a5f5043c33114a7746e319590f38de1 \
SESSION=pipecypher_ablation50_qwen9b \
WAIT_FOR_SESSION=pipecypher_ablation25_qwen9b \
TARGET_PER_CATEGORY=50 \
RUN_PREFIX=20260601_ablation50_qwen9b \
PYTHON_BIN=/home/suraj/pipecypher-tools/runtime-venv/bin/python \
GENERATION_MODEL=Qwen/Qwen3.5-9B \
JUDGE_MODEL=Qwen/Qwen3.5-9B \
scripts/launch_live_ablation_suite_tmux.sh
```

## Retired Large-Scale Attempts

Status: excluded from paper evidence. These runs are intentionally tracked so
failed or weak cells are visible rather than silently omitted.

- `20260601_ablation100_qwen9b` at revision
  `150f596f68dd530869efb497250610a40d3570ee` was retired on June 2, 2026.
  Its FinBench no-retrieval cell crossed the 800-record target without a run
  summary; the remote monitor now reports 1,237 rows and 348 accepted examples,
  and manual inspection at 1,216 rows showed the accepted distribution, with
  `simple_retrieval` at 0/400 and `complex_retrieval` at 14/400 accepted. The
  dominant failure pattern came from the old judge/schema treatment of
  relationship properties and observed categorical execution-result values.
- `20260601_ablation50_qwen9b_seed17` at revision
  `e9301cc08afaea5668291aee7bdbc26c9f1e7296` was retired before generation
  because it queued behind the old target-100 suite and used a pre-patch
  revision.
- `20260602_ablation100_qwen9b_postpatch` at revision
  `f079ff596bcb5be17c251dad991c5e7972e5497b` was retired on June 2, 2026
  after the new relationship-property validator exposed a schema-loading bug:
  Neo4j relationship metadata such as ``:`TRANSFER_TO``` was not normalized to
  `TRANSFER_TO`, so valid `TRANSFER_TO.amount` templates were rejected. Remote
  inspection of the FinBench `reverse_only` cell showed 1,400 records, 600
  accepted examples, and 0 accepted examples for `complex_aggregation` and
  `ranking_topk` because they depended on `t.amount`.
- `20260602_ablation50_qwen9b_seed17_postpatch` at revision
  `f079ff596bcb5be17c251dad991c5e7972e5497b` was retired before generation
  because it queued behind the schema-loading-bug target-100 suite.

## Target-100 Schemafix Suite

Status: running on `ds-serv6` in tmux session
`pipecypher_ablation100_qwen9b_schemafix`.

Research-use note: this is the current preferred target-100 ablation suite for
reviewer-facing reliability. It should be collected only after the tmux session
exits, then audited with the paper-readiness guard before any result is reported
in the manuscript or appendix.

Runtime metadata:

- run prefix: `20260602_ablation100_qwen9b_schemafix`
- target per category: 100
- generation model: `Qwen/Qwen3.5-9B`
- judge model: `Qwen/Qwen3.5-9B`
- recorded code revision: `389e7e09af06bbdcc48c6a4bc80f8f2c7af3b944`
- remote root: `/home/suraj/PIPE-Cypher-389e7e0-schemafix`
- log: `/home/suraj/PIPE-Cypher-389e7e0-schemafix/logs/20260602_ablation100_qwen9b_schemafix.log`

Remote validation before launch:

```bash
cd /home/suraj/PIPE-Cypher-389e7e0-schemafix
/home/suraj/pipecypher-tools/runtime-venv/bin/python -m compileall -q pipecypher scripts
/home/suraj/pipecypher-tools/runtime-venv/bin/python - <<'PY'
from pipecypher.schema import load_schema
from pipecypher.validator import validate_cypher
schema = load_schema("configs/schema_finbench.json")
assert "amount" in schema.properties_for_relationship("TRANSFER_TO")
result = validate_cypher("MATCH (:Account)-[t:TRANSFER_TO]->(:Account) RETURN DISTINCT SUM(t.amount) AS TotalAmount", schema)
assert result.ok, [issue.code for issue in result.issues]
print("remote_schemafix_ok")
PY
```

Launch command:

```bash
cd /home/suraj/PIPE-Cypher-389e7e0-schemafix
CODE_REVISION=389e7e09af06bbdcc48c6a4bc80f8f2c7af3b944 \
SESSION=pipecypher_ablation100_qwen9b_schemafix \
WAIT_FOR_SESSION= \
TARGET_PER_CATEGORY=100 \
RUN_PREFIX=20260602_ablation100_qwen9b_schemafix \
PYTHON_BIN=/home/suraj/pipecypher-tools/runtime-venv/bin/python \
GENERATION_MODEL=Qwen/Qwen3.5-9B \
JUDGE_MODEL=Qwen/Qwen3.5-9B \
bash scripts/launch_live_ablation_suite_tmux.sh
```

After it completes, collect from the staged remote root:

```bash
python scripts/collect_remote_ablation_suite.py \
  --remote-root /home/suraj/PIPE-Cypher-389e7e0-schemafix \
  --run-prefix 20260602_ablation100_qwen9b_schemafix \
  --target-per-category 100 \
  --wait-session pipecypher_ablation100_qwen9b_schemafix \
  --poll-seconds 60
```

## Target-50 Schemafix Seeded Repeat

Status: queued on `ds-serv6` in tmux session
`pipecypher_ablation50_qwen9b_seed17_schemafix`. The session waits for
`pipecypher_ablation100_qwen9b_schemafix` to exit before it starts generation.

Research-use note: this repeated-seed target-50 suite is intended to provide
variance/sensitivity evidence on the corrected schema-normalized revision. It
should not be reported until collected and audited.

Runtime metadata:

- run prefix: `20260602_ablation50_qwen9b_seed17_schemafix`
- target per category: 50
- run seed: 17
- generation model: `Qwen/Qwen3.5-9B`
- judge model: `Qwen/Qwen3.5-9B`
- recorded code revision: `389e7e09af06bbdcc48c6a4bc80f8f2c7af3b944`
- remote root: `/home/suraj/PIPE-Cypher-389e7e0-schemafix`
- log: `/home/suraj/PIPE-Cypher-389e7e0-schemafix/logs/20260602_ablation50_qwen9b_seed17_schemafix.log`
- wait dependency: `pipecypher_ablation100_qwen9b_schemafix`

Launch command:

```bash
cd /home/suraj/PIPE-Cypher-389e7e0-schemafix
CODE_REVISION=389e7e09af06bbdcc48c6a4bc80f8f2c7af3b944 \
SESSION=pipecypher_ablation50_qwen9b_seed17_schemafix \
WAIT_FOR_SESSION=pipecypher_ablation100_qwen9b_schemafix \
TARGET_PER_CATEGORY=50 \
RUN_PREFIX=20260602_ablation50_qwen9b_seed17_schemafix \
RUN_SEED=17 \
PYTHON_BIN=/home/suraj/pipecypher-tools/runtime-venv/bin/python \
GENERATION_MODEL=Qwen/Qwen3.5-9B \
JUDGE_MODEL=Qwen/Qwen3.5-9B \
bash scripts/launch_live_ablation_suite_tmux.sh
```

After it completes, collect from the staged remote root:

```bash
python scripts/collect_remote_ablation_suite.py \
  --remote-root /home/suraj/PIPE-Cypher-389e7e0-schemafix \
  --run-prefix 20260602_ablation50_qwen9b_seed17_schemafix \
  --target-per-category 50 \
  --wait-session pipecypher_ablation50_qwen9b_seed17_schemafix \
  --poll-seconds 60
```

## Target-Size And Seed Sensitivity Comparison

After target-100 or the seeded target-50 repeat has completed, been collected,
and passed its paper-readiness audit, compare it against the collected
target-50 suite before writing variance or sensitivity claims:

```bash
python scripts/compare_ablation_suites.py \
  experiments/snapshots/20260601_ablation50_qwen9b/ablation_suite_summary.json \
  experiments/snapshots/20260602_ablation100_qwen9b_schemafix/ablation_suite_summary.json \
  experiments/snapshots/20260602_ablation50_qwen9b_seed17_schemafix/ablation_suite_summary.json \
  --output-json experiments/snapshots/ablation_suite_comparison.json \
  --output-md experiments/snapshots/ablation_suite_comparison.md \
  --output-csv experiments/snapshots/ablation_suite_comparison.csv \
  --output-tex paper_emnlp2026_industry/tables_ablation_comparison.tex
```

The comparison uses target-normalized coverage rather than raw accepted counts,
so target-100 is not treated as better merely because it contains more planned
examples. The LaTeX output is guarded and refuses to render unless at least two
suites have sibling `ablation_suite_audit.json` and `collection_manifest.json`
evidence; use `--allow-diagnostic-tex` only for internal layout checks.

## Monitoring Commands

```bash
ssh suraj@ds-serv6.ucsd.edu

tmux has-session -t =pipecypher_ablation50_qwen9b && echo target50_running || echo target50_done
tmux has-session -t =pipecypher_ablation100_qwen9b_schemafix && echo target100_schemafix_running || echo target100_schemafix_done
tmux has-session -t =pipecypher_ablation50_qwen9b_seed17_schemafix && echo target50_seed17_schemafix_running_or_waiting || echo target50_seed17_schemafix_done

tail -f /home/suraj/PIPE-Cypher-389e7e0-schemafix/logs/20260602_ablation100_qwen9b_schemafix.log
tmux capture-pane -pt pipecypher_ablation100_qwen9b_schemafix -S -20
tmux capture-pane -pt pipecypher_ablation50_qwen9b_seed17_schemafix -S -20
```

From the local repo, use the read-only remote monitor without fetching partial
artifacts. The queue monitor covers completed, retired, active, and queued
suites across their different remote roots. It prints `next_action`,
generated-record and accepted-record progress, over-target incomplete cell
diagnostics, and a safe `collection_command` with `--wait-session` for active
or waiting suites. Already collected or retired suites report
`collection_command=not_applicable`:

```bash
python scripts/monitor_remote_ablation_queue.py \
  --queue experiments/remote_ablation_queue.yaml
```

For focused target-100 inspection:

```bash
python scripts/monitor_remote_ablation_suite.py \
  --remote-root /home/suraj/PIPE-Cypher-389e7e0-schemafix \
  --run-prefix 20260602_ablation100_qwen9b_schemafix \
  --target-per-category 100 \
  --session pipecypher_ablation100_qwen9b_schemafix
```
