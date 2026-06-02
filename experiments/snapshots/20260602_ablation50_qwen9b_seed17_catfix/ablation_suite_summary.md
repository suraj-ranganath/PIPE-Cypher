# Live Ablation Suite Summary

- Target per category: 50
- Expected graph workloads: finbench, snb
- Expected variants: unconstrained_local_llm, reverse_only, validators_repair, ablation_retrieval_topk_0, ablation_rewrite_false, ablation_judge_false, full_pipe_cypher
- Runs found: 14
- All expected runs finished: true
- Research reporting status: candidate paper evidence after claim/evidence audit
- Metadata:
  - code_revision: `4df5175396352e7ad695f6ad1c8ce14c493d6955`
  - generation_model: `Qwen/Qwen3.5-9B`
  - judge_model: `Qwen/Qwen3.5-9B`
  - log_file: `logs/20260602_ablation50_qwen9b_seed17_catfix.log`
  - run_prefix: `20260602_ablation50_qwen9b_seed17_catfix`
  - run_seed: `17`

| Setting | Graph | Run | Records | Accepted | Acceptance | Categories at target | Finished |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| Unconstrained LLM | finbench | `20260602_081452_20260602_ablation50_qwen9b_seed17_catfix_finbench_unconstrained_local_llm` | 0 | 0 | 0.000 | 0/8 | yes |
| Reverse-only | finbench | `20260602_081453_20260602_ablation50_qwen9b_seed17_catfix_finbench_reverse_only` | 400 | 400 | 1.000 | 8/8 | yes |
| Validators+repair | finbench | `20260602_081512_20260602_ablation50_qwen9b_seed17_catfix_finbench_validators_repair` | 400 | 400 | 1.000 | 8/8 | yes |
| No retrieval | finbench | `20260602_081531_20260602_ablation50_qwen9b_seed17_catfix_finbench_ablation_retrieval_topk_0` | 403 | 400 | 0.993 | 8/8 | yes |
| No rewrite | finbench | `20260602_083135_20260602_ablation50_qwen9b_seed17_catfix_finbench_ablation_rewrite_false` | 403 | 400 | 0.993 | 8/8 | yes |
| No LLM judge | finbench | `20260602_084732_20260602_ablation50_qwen9b_seed17_catfix_finbench_ablation_judge_false` | 400 | 400 | 1.000 | 8/8 | yes |
| Full PIPE-Cypher | finbench | `20260602_084749_20260602_ablation50_qwen9b_seed17_catfix_finbench_full_pipe_cypher` | 403 | 400 | 0.993 | 8/8 | yes |
| Unconstrained LLM | snb | `20260602_090358_20260602_ablation50_qwen9b_seed17_catfix_snb_unconstrained_local_llm` | 0 | 0 | 0.000 | 0/8 | yes |
| Reverse-only | snb | `20260602_090358_20260602_ablation50_qwen9b_seed17_catfix_snb_reverse_only` | 402 | 400 | 0.995 | 8/8 | yes |
| Validators+repair | snb | `20260602_090414_20260602_ablation50_qwen9b_seed17_catfix_snb_validators_repair` | 402 | 400 | 0.995 | 8/8 | yes |
| No retrieval | snb | `20260602_090430_20260602_ablation50_qwen9b_seed17_catfix_snb_ablation_retrieval_topk_0` | 402 | 400 | 0.995 | 8/8 | yes |
| No rewrite | snb | `20260602_092019_20260602_ablation50_qwen9b_seed17_catfix_snb_ablation_rewrite_false` | 402 | 400 | 0.995 | 8/8 | yes |
| No LLM judge | snb | `20260602_093604_20260602_ablation50_qwen9b_seed17_catfix_snb_ablation_judge_false` | 402 | 400 | 0.995 | 8/8 | yes |
| Full PIPE-Cypher | snb | `20260602_093620_20260602_ablation50_qwen9b_seed17_catfix_snb_full_pipe_cypher` | 402 | 400 | 0.995 | 8/8 | yes |

## Gate Rates

| Setting | Graph | Read-only | Syntax | Schema | Execution | Judge |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Unconstrained LLM | finbench | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| Reverse-only | finbench | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| Validators+repair | finbench | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| No retrieval | finbench | 1.000 | 1.000 | 1.000 | 1.000 | 0.993 |
| No rewrite | finbench | 1.000 | 1.000 | 1.000 | 1.000 | 0.993 |
| No LLM judge | finbench | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| Full PIPE-Cypher | finbench | 1.000 | 1.000 | 1.000 | 1.000 | 0.993 |
| Unconstrained LLM | snb | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| Reverse-only | snb | 1.000 | 1.000 | 0.995 | 0.995 | 0.995 |
| Validators+repair | snb | 1.000 | 1.000 | 0.995 | 0.995 | 0.995 |
| No retrieval | snb | 1.000 | 1.000 | 0.995 | 0.995 | 0.995 |
| No rewrite | snb | 1.000 | 1.000 | 0.995 | 0.995 | 0.995 |
| No LLM judge | snb | 1.000 | 1.000 | 0.995 | 0.995 | 0.995 |
| Full PIPE-Cypher | snb | 1.000 | 1.000 | 0.995 | 0.995 | 0.995 |

## Reporting Rule

This suite is large enough to be considered for paper reporting after a claim/evidence audit verifies run logs, model IDs, graph workloads, code revision, and failure analysis.
