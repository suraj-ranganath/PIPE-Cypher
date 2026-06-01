# Live Ablation Suite Summary

- Target per category: 50
- Expected graph workloads: finbench, snb
- Expected variants: unconstrained_local_llm, reverse_only, validators_repair, ablation_retrieval_topk_0, ablation_rewrite_false, ablation_judge_false, full_pipe_cypher
- Runs found: 14
- All expected runs finished: true
- Research reporting status: candidate paper evidence after claim/evidence audit
- Metadata:
  - code_revision: `b5d4898e4a5f5043c33114a7746e319590f38de1`
  - generation_model: `Qwen/Qwen3.5-9B`
  - judge_model: `Qwen/Qwen3.5-9B`
  - log_file: `logs/20260601_ablation50_qwen9b.log`
  - run_prefix: `20260601_ablation50_qwen9b`

| Setting | Graph | Run | Records | Accepted | Acceptance | Categories at target | Finished |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| Unconstrained LLM | finbench | `20260601_220246_20260601_ablation50_qwen9b_finbench_unconstrained_local_llm` | 0 | 0 | 0.000 | 0/8 | yes |
| Reverse-only | finbench | `20260601_220247_20260601_ablation50_qwen9b_finbench_reverse_only` | 400 | 400 | 1.000 | 8/8 | yes |
| Validators+repair | finbench | `20260601_220302_20260601_ablation50_qwen9b_finbench_validators_repair` | 400 | 400 | 1.000 | 8/8 | yes |
| No retrieval | finbench | `20260601_220318_20260601_ablation50_qwen9b_finbench_ablation_retrieval_topk_0` | 429 | 400 | 0.932 | 8/8 | yes |
| No rewrite | finbench | `20260601_222119_20260601_ablation50_qwen9b_finbench_ablation_rewrite_false` | 423 | 400 | 0.946 | 8/8 | yes |
| No LLM judge | finbench | `20260601_223821_20260601_ablation50_qwen9b_finbench_ablation_judge_false` | 401 | 400 | 0.998 | 8/8 | yes |
| Full PIPE-Cypher | finbench | `20260601_223836_20260601_ablation50_qwen9b_finbench_full_pipe_cypher` | 416 | 400 | 0.962 | 8/8 | yes |
| Unconstrained LLM | snb | `20260601_225457_20260601_ablation50_qwen9b_snb_unconstrained_local_llm` | 0 | 0 | 0.000 | 0/8 | yes |
| Reverse-only | snb | `20260601_225458_20260601_ablation50_qwen9b_snb_reverse_only` | 402 | 400 | 0.995 | 8/8 | yes |
| Validators+repair | snb | `20260601_225510_20260601_ablation50_qwen9b_snb_validators_repair` | 402 | 400 | 0.995 | 8/8 | yes |
| No retrieval | snb | `20260601_225522_20260601_ablation50_qwen9b_snb_ablation_retrieval_topk_0` | 402 | 400 | 0.995 | 8/8 | yes |
| No rewrite | snb | `20260601_231001_20260601_ablation50_qwen9b_snb_ablation_rewrite_false` | 402 | 400 | 0.995 | 8/8 | yes |
| No LLM judge | snb | `20260601_232445_20260601_ablation50_qwen9b_snb_ablation_judge_false` | 406 | 400 | 0.985 | 8/8 | yes |
| Full PIPE-Cypher | snb | `20260601_232457_20260601_ablation50_qwen9b_snb_full_pipe_cypher` | 402 | 400 | 0.995 | 8/8 | yes |

## Gate Rates

| Setting | Graph | Read-only | Syntax | Schema | Execution | Judge |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Unconstrained LLM | finbench | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| Reverse-only | finbench | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| Validators+repair | finbench | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| No retrieval | finbench | 1.000 | 1.000 | 1.000 | 1.000 | 0.932 |
| No rewrite | finbench | 1.000 | 1.000 | 1.000 | 1.000 | 0.946 |
| No LLM judge | finbench | 1.000 | 1.000 | 1.000 | 1.000 | 0.998 |
| Full PIPE-Cypher | finbench | 1.000 | 1.000 | 1.000 | 1.000 | 0.962 |
| Unconstrained LLM | snb | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| Reverse-only | snb | 1.000 | 1.000 | 0.995 | 0.995 | 0.995 |
| Validators+repair | snb | 1.000 | 1.000 | 0.995 | 0.995 | 0.995 |
| No retrieval | snb | 1.000 | 1.000 | 0.995 | 0.995 | 0.995 |
| No rewrite | snb | 1.000 | 1.000 | 0.995 | 0.995 | 0.995 |
| No LLM judge | snb | 1.000 | 1.000 | 0.995 | 0.995 | 0.985 |
| Full PIPE-Cypher | snb | 1.000 | 1.000 | 0.995 | 0.995 | 0.995 |

## Reporting Rule

This suite is large enough to be considered for paper reporting after a claim/evidence audit verifies run logs, model IDs, graph workloads, code revision, and failure analysis.
