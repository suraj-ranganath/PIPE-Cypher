# Scaled Ablation Status

Date: June 1, 2026.

## Target-25 Suite

Status: running on `ds-serv6` in tmux session `pipecypher_ablation25_qwen9b`.

Runtime metadata:

- run prefix: `20260601_ablation25_qwen9b_retry1`
- target per category: 25
- graphs: LDBC FinBench and LDBC SNB live Neo4j databases
- variants: `unconstrained_local_llm`, `reverse_only`, `validators_repair`, `ablation_retrieval_topk_0`, `ablation_rewrite_false`, `ablation_judge_false`, `full_pipe_cypher`
- generation model: `Qwen/Qwen3.5-9B`
- judge model: `Qwen/Qwen3.5-9B`
- recorded code revision: `2122a86e457a3c0039367a09290dde120c660d68`
- log: `/home/suraj/PIPE-Cypher/logs/20260601_ablation25_qwen9b_retry1.log`

Completed at latest inspection:

- all FinBench variants;
- SNB `unconstrained_local_llm`, `reverse_only`, `validators_repair`, and `ablation_retrieval_topk_0`.

Active at latest inspection:

- SNB `ablation_rewrite_false`.

Post-processing:

- tmux session `pipecypher_ablation25_finalize` is waiting for `pipecypher_ablation25_qwen9b` to end.
- After completion it will write:
  - `/home/suraj/PIPE-Cypher/experiments/snapshots/20260601_ablation25_qwen9b_retry1/ablation_suite_summary.json`
  - `/home/suraj/PIPE-Cypher/experiments/snapshots/20260601_ablation25_qwen9b_retry1/ablation_suite_summary.md`
  - `/home/suraj/PIPE-Cypher/experiments/snapshots/20260601_ablation25_qwen9b_retry1/ablation_suite_target25.pdf`

Research-use note: target-25 is an interim scaled checkpoint, not final paper evidence unless later claim/evidence audit determines that it is sufficient for a narrow appendix claim. Larger target-per-category runs remain preferred.

## Target-50 Suite

Status: queued on `ds-serv6` in tmux session `pipecypher_ablation50_qwen9b`.

The session was launched with `WAIT_FOR_SESSION=pipecypher_ablation25_qwen9b`, so it should start only after the target-25 suite exits. It reuses the existing local Qwen3.5-9B endpoint rather than starting another model server.

Runtime metadata:

- run prefix: `20260601_ablation50_qwen9b`
- target per category: 50
- generation model: `Qwen/Qwen3.5-9B`
- judge model: `Qwen/Qwen3.5-9B`
- recorded code revision: `b5d4898e4a5f5043c33114a7746e319590f38de1`
- log: `/home/suraj/PIPE-Cypher/logs/20260601_ablation50_qwen9b.log`

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

## Monitoring Commands

```bash
ssh suraj@ds-serv6.ucsd.edu
cd /home/suraj/PIPE-Cypher

tmux has-session -t pipecypher_ablation25_qwen9b && echo target25_running || echo target25_done
tmux has-session -t pipecypher_ablation25_finalize && echo target25_finalize_running || echo target25_finalize_done
tmux has-session -t pipecypher_ablation50_qwen9b && echo target50_running || echo target50_done

tail -f logs/20260601_ablation25_qwen9b_retry1.log
tail -f logs/20260601_ablation25_finalize.log
tail -f logs/20260601_ablation50_qwen9b.log
```
