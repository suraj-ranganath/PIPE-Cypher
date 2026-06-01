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

Status: running on `ds-serv6` in tmux session `pipecypher_ablation50_qwen9b`.

The session was launched with `WAIT_FOR_SESSION=pipecypher_ablation25_qwen9b`, so it started only after the target-25 suite exited. It reuses the existing local Qwen3.5-9B endpoint rather than starting another model server.

Runtime metadata:

- run prefix: `20260601_ablation50_qwen9b`
- target per category: 50
- generation model: `Qwen/Qwen3.5-9B`
- judge model: `Qwen/Qwen3.5-9B`
- recorded code revision: `b5d4898e4a5f5043c33114a7746e319590f38de1`
- log: `/home/suraj/PIPE-Cypher/logs/20260601_ablation50_qwen9b.log`

Observed at latest inspection:

- 11/14 graph/variant cells had been observed.
- 10/14 graph/variant cells were complete.
- The tmux session was still running.

Completed at latest inspection:

- All FinBench variants: `unconstrained_local_llm`, `reverse_only`, `validators_repair`,
  `ablation_retrieval_topk_0`, `ablation_rewrite_false`, and
  `ablation_judge_false`, and `full_pipe_cypher`.
- SNB `unconstrained_local_llm`, `reverse_only`, and `validators_repair`.

Active at latest inspection:

- SNB `ablation_retrieval_topk_0`; the active records file
  `artifacts/runs/20260601_225522_20260601_ablation50_qwen9b_snb_ablation_retrieval_topk_0/records.jsonl`
  had passed 100 records during local inspection and continued advancing
  afterward. Treat it as active/incomplete until the suite advances and the
  collector/audit confirms the final status; use the monitor command below for
  the exact live count.

Still missing at latest inspection:

- SNB `ablation_rewrite_false`, `ablation_judge_false`, and
  `full_pipe_cypher`.

Reporting note: once the suite finishes, `scripts/run_live_ablation_suite.sh` now writes
`ablation_suite_summary.json`, `ablation_suite_summary.md`, `ablation_suite_summary.csv`,
`ablation_suite_audit.json`, and `ablation_suite_audit.md`. The CSV preserves yield
and gate-quality rates for each graph/variant cell. The audit enforces completeness,
target scale, metadata, run summaries, category-target coverage, known graph/variant
labels, and core gate-rate availability. `scripts/summarize_live_ablation_suite.py
--output-quality-tex` and `scripts/render_ablation_suite_figure.py` now refuse
non-paper-ready suites by default; use their diagnostic override flags only for
internal checks.

Because the active target-50 tmux session was launched from an older checkout, it may
not write the audit packet itself. After it exits, collect and summarize from the
local repo with:

```bash
python scripts/collect_remote_ablation_suite.py \
  --run-prefix 20260601_ablation50_qwen9b \
  --target-per-category 50 \
  --wait-session pipecypher_ablation50_qwen9b \
  --poll-seconds 60
```

The collector writes `collection_manifest.json` alongside the summary and audit
files, with SHA-256 checksums for fetched run records, run summaries, the copied
remote log, summary/audit files, and any rendered paper ablation artifacts.

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

Status: queued on `ds-serv6` in tmux session `pipecypher_ablation100_qwen9b`.
The session waits for `pipecypher_ablation50_qwen9b` to exit before it starts
generation, so it does not compete with the active target-50 suite.

Runtime metadata:

- run prefix: `20260601_ablation100_qwen9b`
- target per category: 100
- generation model: `Qwen/Qwen3.5-9B`
- judge model: `Qwen/Qwen3.5-9B`
- recorded code revision: `75c99d8e41d5fee3466c5521d3597e3d965804a8`
- remote root: `/home/suraj/PIPE-Cypher-75c99d8-target100`
- log: `/home/suraj/PIPE-Cypher-75c99d8-target100/logs/20260601_ablation100_qwen9b.log`

The code snapshot was staged separately from `/home/suraj/PIPE-Cypher` because
the active target-50 directory is not a Git checkout and should not be mutated
while the older suite is still running. Remote validation before launch:

```bash
cd /home/suraj/PIPE-Cypher-75c99d8-target100
/home/suraj/pipecypher-tools/runtime-venv/bin/python -m compileall -q pipecypher scripts
/home/suraj/pipecypher-tools/runtime-venv/bin/python -c "import pipecypher; print('import_ok')"
```

Launch command:

```bash
cd /home/suraj/PIPE-Cypher-75c99d8-target100
CODE_REVISION=75c99d8e41d5fee3466c5521d3597e3d965804a8 \
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
  --remote-root /home/suraj/PIPE-Cypher-75c99d8-target100 \
  --run-prefix 20260601_ablation100_qwen9b \
  --target-per-category 100 \
  --wait-session pipecypher_ablation100_qwen9b \
  --poll-seconds 60
```

## Monitoring Commands

```bash
ssh suraj@ds-serv6.ucsd.edu
cd /home/suraj/PIPE-Cypher

tmux has-session -t pipecypher_ablation25_qwen9b && echo target25_running || echo target25_done
tmux has-session -t pipecypher_ablation25_finalize && echo target25_finalize_running || echo target25_finalize_done
tmux has-session -t pipecypher_ablation50_qwen9b && echo target50_running || echo target50_done
tmux has-session -t pipecypher_ablation100_qwen9b && echo target100_running_or_waiting || echo target100_done

tail -f logs/20260601_ablation25_qwen9b_retry1.log
tail -f logs/20260601_ablation25_finalize.log
tail -f logs/20260601_ablation50_qwen9b.log
tmux capture-pane -pt pipecypher_ablation100_qwen9b -S -20
```

From the local repo, use the read-only remote monitor without fetching partial
artifacts:

```bash
python scripts/monitor_remote_ablation_suite.py \
  --run-prefix 20260601_ablation50_qwen9b \
  --target-per-category 50 \
  --session pipecypher_ablation50_qwen9b
```
