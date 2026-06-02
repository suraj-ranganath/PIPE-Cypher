# Scaled Ablation Status

Date: June 1, 2026.

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

## Target-100 Suite

Status: running on `ds-serv6` in tmux session
`pipecypher_ablation100_qwen9b`.

This suite was restarted from a fixed checkout after the earlier queued
target-100 session was blocked by tmux prefix matching: `tmux has-session -t
pipecypher_ablation50_qwen9b` matched the longer seeded repeat session
`pipecypher_ablation50_qwen9b_seed17`. The launcher and collector now use exact
tmux targets with `=<session>`.

Research-use note: target-100 is the preferred next ablation scale for
reviewer-facing reliability. Do not cancel it merely because target-50 finishes
unless a real compute, model, graph-backend, or storage blocker is documented.
If target-100 completes, collect and audit it before deciding whether target-50
is still needed in the manuscript.

Runtime metadata:

- run prefix: `20260601_ablation100_qwen9b`
- target per category: 100
- generation model: `Qwen/Qwen3.5-9B`
- judge model: `Qwen/Qwen3.5-9B`
- recorded code revision: `150f596f68dd530869efb497250610a40d3570ee`
- remote root: `/home/suraj/PIPE-Cypher-150f596-target100-exact`
- log: `/home/suraj/PIPE-Cypher-150f596-target100-exact/logs/20260601_ablation100_qwen9b.log`

Monitor snapshot recorded during the June 2, 2026 00:52 UTC update:

- the tmux session is running;
- 4/14 graph/variant cells have been observed;
- 3/14 graph/variant cells are complete;
- FinBench `ablation_retrieval_topk_0` was active at 470/800 target records in that snapshot;
- completed cells are FinBench `unconstrained_local_llm`, `reverse_only`, and `validators_repair`.

Remote validation before launch:

```bash
cd /home/suraj/PIPE-Cypher-150f596-target100-exact
/home/suraj/pipecypher-tools/runtime-venv/bin/python -m compileall -q pipecypher scripts
/home/suraj/pipecypher-tools/runtime-venv/bin/python -c "import pipecypher; print('import_ok')"
```

Launch command:

```bash
cd /home/suraj/PIPE-Cypher-150f596-target100-exact
CODE_REVISION=150f596f68dd530869efb497250610a40d3570ee \
SESSION=pipecypher_ablation100_qwen9b \
WAIT_FOR_SESSION=pipecypher_ablation50_qwen9b \
TARGET_PER_CATEGORY=100 \
RUN_PREFIX=20260601_ablation100_qwen9b \
PYTHON_BIN=/home/suraj/pipecypher-tools/runtime-venv/bin/python \
GENERATION_MODEL=Qwen/Qwen3.5-9B \
JUDGE_MODEL=Qwen/Qwen3.5-9B \
bash scripts/launch_live_ablation_suite_tmux.sh
```

After it completes, collect from the staged remote root rather than the older
target-50 root:

```bash
python scripts/collect_remote_ablation_suite.py \
  --remote-root /home/suraj/PIPE-Cypher-150f596-target100-exact \
  --run-prefix 20260601_ablation100_qwen9b \
  --target-per-category 100 \
  --wait-session pipecypher_ablation100_qwen9b \
  --poll-seconds 60
```

## Target-50 Seeded Repeat

Status: queued on `ds-serv6` in tmux session
`pipecypher_ablation50_qwen9b_seed17`. The session waits for
`pipecypher_ablation100_qwen9b` to exit before it starts generation, so it will
not compete with the active target-100 follow-up.

Research-use note: this is a repeated-seed target-50 suite intended to provide
variance/sensitivity evidence if target-100 finishes cleanly and enough compute
time remains. It should not be reported until collected and audited.

Runtime metadata:

- run prefix: `20260601_ablation50_qwen9b_seed17`
- target per category: 50
- run seed: 17
- generation model: `Qwen/Qwen3.5-9B`
- judge model: `Qwen/Qwen3.5-9B`
- recorded code revision: `e9301cc08afaea5668291aee7bdbc26c9f1e7296`
- remote root: `/home/suraj/PIPE-Cypher-e9301cc-target50-seed17`
- log: `/home/suraj/PIPE-Cypher-e9301cc-target50-seed17/logs/20260601_ablation50_qwen9b_seed17.log`

Remote validation before launch:

```bash
cd /home/suraj/PIPE-Cypher-e9301cc-target50-seed17
/home/suraj/pipecypher-tools/runtime-venv/bin/python -m compileall -q pipecypher scripts
/home/suraj/pipecypher-tools/runtime-venv/bin/python -c "import pipecypher; from pipecypher.config import RunConfig; print(RunConfig().generation.random_seed)"
```

Launch command:

```bash
cd /home/suraj/PIPE-Cypher-e9301cc-target50-seed17
CODE_REVISION=e9301cc08afaea5668291aee7bdbc26c9f1e7296 \
SESSION=pipecypher_ablation50_qwen9b_seed17 \
WAIT_FOR_SESSION=pipecypher_ablation100_qwen9b \
TARGET_PER_CATEGORY=50 \
RUN_PREFIX=20260601_ablation50_qwen9b_seed17 \
RUN_SEED=17 \
PYTHON_BIN=/home/suraj/pipecypher-tools/runtime-venv/bin/python \
GENERATION_MODEL=Qwen/Qwen3.5-9B \
JUDGE_MODEL=Qwen/Qwen3.5-9B \
bash scripts/launch_live_ablation_suite_tmux.sh
```

After it completes, collect from the staged remote root:

```bash
python scripts/collect_remote_ablation_suite.py \
  --remote-root /home/suraj/PIPE-Cypher-e9301cc-target50-seed17 \
  --run-prefix 20260601_ablation50_qwen9b_seed17 \
  --target-per-category 50 \
  --wait-session pipecypher_ablation50_qwen9b_seed17 \
  --poll-seconds 60
```

## Target-Size And Seed Sensitivity Comparison

After target-100 or the seeded target-50 repeat has completed, been collected,
and passed its paper-readiness audit, compare it against the collected
target-50 suite before writing variance or sensitivity claims:

```bash
python scripts/compare_ablation_suites.py \
  experiments/snapshots/20260601_ablation50_qwen9b/ablation_suite_summary.json \
  experiments/snapshots/20260601_ablation100_qwen9b/ablation_suite_summary.json \
  experiments/snapshots/20260601_ablation50_qwen9b_seed17/ablation_suite_summary.json \
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
cd /home/suraj/PIPE-Cypher

tmux has-session -t =pipecypher_ablation25_qwen9b && echo target25_running || echo target25_done
tmux has-session -t =pipecypher_ablation25_finalize && echo target25_finalize_running || echo target25_finalize_done
tmux has-session -t =pipecypher_ablation50_qwen9b && echo target50_running || echo target50_done
tmux has-session -t =pipecypher_ablation100_qwen9b && echo target100_running_or_waiting || echo target100_done
tmux has-session -t =pipecypher_ablation50_qwen9b_seed17 && echo target50_seed17_running_or_waiting || echo target50_seed17_done

tail -f logs/20260601_ablation25_qwen9b_retry1.log
tail -f logs/20260601_ablation25_finalize.log
tail -f logs/20260601_ablation50_qwen9b.log
tmux capture-pane -pt pipecypher_ablation100_qwen9b -S -20
tmux capture-pane -pt pipecypher_ablation50_qwen9b_seed17 -S -20
```

From the local repo, use the read-only remote monitor without fetching partial
artifacts. The queue monitor covers the completed target-50 suite, the active
target-100 suite, and the queued seeded target-50 repeat, including their
different remote roots. It also prints
`next_action` and a safe `collection_command` with `--wait-session` for active
or waiting suites. Already collected paper-ready suites report
`collection_command=not_applicable`:

```bash
python scripts/monitor_remote_ablation_queue.py \
  --queue experiments/remote_ablation_queue.yaml
```

For focused target-100 inspection:

```bash
python scripts/monitor_remote_ablation_suite.py \
  --remote-root /home/suraj/PIPE-Cypher-150f596-target100-exact \
  --run-prefix 20260601_ablation100_qwen9b \
  --target-per-category 100 \
  --session pipecypher_ablation100_qwen9b
```
