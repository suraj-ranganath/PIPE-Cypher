# Full Run Status

Date: June 1, 2026

## Completed 9B Fallback Run

The first detached full-generation run completed on `ds-serv6` using the local Qwen3.5-9B fallback:

```text
run prefix: 20260601_full_qwen9b
model: Qwen/Qwen3.5-9B for generation and judge
log: /home/suraj/PIPE-Cypher/logs/20260601_full_qwen9b_full_generation.log
FinBench run dir: /home/suraj/PIPE-Cypher/artifacts/runs/20260601_142318_20260601_full_qwen9b_finbench
SNB partial run dir: /home/suraj/PIPE-Cypher/artifacts/runs/20260601_165047_20260601_full_qwen9b_snb
export: /home/suraj/PIPE-Cypher/artifacts/benchmarks/20260601_live_full_qwen9b
```

Final FinBench main-run snapshot:

```text
records=3376 accepted=1978 accept_rate=0.586
accepted_by_category={"boolean_existence": 250, "complex_aggregation": 250, "complex_retrieval": 250, "negation_difference": 228, "path_temporal": 250, "ranking_topk": 250, "simple_aggregation": 250, "simple_retrieval": 250}
coverage={"boolean_existence": "250/250", "complex_aggregation": "250/250", "complex_retrieval": "250/250", "negation_difference": "228/250", "path_temporal": "250/250", "ranking_topk": "250/250", "simple_aggregation": "250/250"}
latest={"accepted": true, "category": "ranking_topk", "judge_failure_reason": "", "question": "For accounts owned by person 'Salome', which account sent the highest total transfer amount?"}
```

The FinBench built-in pass completed all categories except `negation_difference`, which exhausted at 228/250 because the active process predated later seed/scheduler patches. A patched top-up run filled the missing 22 negation examples.

## SNB Phase And Recovery

The sequential SNB pass was intentionally interrupted after it spent many attempts on an old low-yield forum-negation seed. The accepted partial records were kept and the patched multi-pass top-up mechanism filled missing categories:

```text
SNB run dir: /home/suraj/PIPE-Cypher/artifacts/runs/20260601_165047_20260601_full_qwen9b_snb
records=1011 accepted=698 accept_rate=0.690
accepted_by_category={"boolean_existence": 125, "complex_aggregation": 125, "complex_retrieval": 125, "negation_difference": 73, "simple_aggregation": 125, "simple_retrieval": 125}
coverage={"boolean_existence": "125/125", "complex_aggregation": "125/125", "complex_retrieval": "125/125", "negation_difference": "73/125", "simple_aggregation": "125/125", "simple_retrieval": "125/125"}
```

Recovery outputs:

```text
FinBench negation top-up: 22/28 accepted
SNB negation top-up: 52/106 accepted
SNB path/temporal top-up: 125/125 accepted
SNB ranking/top-k top-up: 125/131 accepted
```

The final exported benchmark contains exactly 3,000 accepted examples:

```text
total=3000
by_graph={"finbench": 2000, "snb": 1000}
by_category=375 accepted examples in each of the 8 categories
by_split={"train": 2408, "dev": 296, "test": 296}
gate_counts={"accepted": 3000, "execution_success": 3000, "judge_pass": 3000, "read_only": 3000, "schema_valid": 3000, "syntax_valid": 3000}
manifest_sha256=8bc79a53a06b291a81974d7859d1a02d013c1e7dfc401e447b2897259aeaa47c
judge_audit=artifacts/audits/20260601_full_qwen9b_judge_audit.csv, 80 sampled rows plus header
```

## Target Model Staging

The 35B-A3B staging download completed on `ds-serv6`:

```text
tmux session: pipecypher_stage_qwen35b (completed)
model: Qwen/Qwen3.5-35B-A3B
local dir: /home/suraj/pipecypher-models/Qwen3.5-35B-A3B
log: /home/suraj/PIPE-Cypher/logs/qwen35b_stage.log
latest observed disk usage: 67G
staged files: 14 safetensor shards plus tokenizer/config files
```

## Monitor Commands

Run these on `ds-serv6`:

```bash
cd /home/suraj/PIPE-Cypher
cat artifacts/benchmarks/20260601_live_full_qwen9b/stats.json
tail -f logs/20260601_full_qwen9b_downstream.log
tmux ls | grep pipecypher_downstream_qwen9b
```

## Downstream Evaluation

The full downstream Text2Cypher evaluation completed on the 296-example full test split:

```text
predictions: /home/suraj/PIPE-Cypher/artifacts/predictions/20260601_full_qwen9b_test_predictions.jsonl
evaluation: /home/suraj/PIPE-Cypher/artifacts/evaluations/20260601_full_qwen9b_test_eval.jsonl
summary: /home/suraj/PIPE-Cypher/artifacts/evaluations/20260601_full_qwen9b_test_summary.json
log: /home/suraj/PIPE-Cypher/logs/20260601_full_qwen9b_downstream.log
parse_valid=0.959
schema_valid=0.905
execution_success=0.622
execution_accuracy=0.189
answer_f1=0.189
```
