# Live Ablation Suite Summary

- Target per category: 100
- Expected graph workloads: finbench, snb
- Expected variants: unconstrained_local_llm, reverse_only, validators_repair, ablation_retrieval_topk_0, ablation_rewrite_false, ablation_judge_false, full_pipe_cypher
- Runs found: 14
- All expected runs finished: true
- Research reporting status: candidate paper evidence after claim/evidence audit
- Metadata:
  - code_revision: `4df5175396352e7ad695f6ad1c8ce14c493d6955`
  - generation_model: `Qwen/Qwen3.5-9B`
  - judge_model: `Qwen/Qwen3.5-9B`
  - log_file: `logs/20260602_ablation100_qwen9b_catfix.log`
  - run_prefix: `20260602_ablation100_qwen9b_catfix`

| Setting | Graph | Run | Records | Accepted | Acceptance | Categories at target | Finished |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| Unconstrained LLM | finbench | `20260602_081452_20260602_ablation100_qwen9b_catfix_finbench_unconstrained_local_llm` | 0 | 0 | 0.000 | 0/8 | yes |
| Reverse-only | finbench | `20260602_081453_20260602_ablation100_qwen9b_catfix_finbench_reverse_only` | 815 | 800 | 0.982 | 8/8 | yes |
| Validators+repair | finbench | `20260602_081531_20260602_ablation100_qwen9b_catfix_finbench_validators_repair` | 833 | 800 | 0.960 | 8/8 | yes |
| No retrieval | finbench | `20260602_081724_20260602_ablation100_qwen9b_catfix_finbench_ablation_retrieval_topk_0` | 819 | 800 | 0.977 | 8/8 | yes |
| No rewrite | finbench | `20260602_085052_20260602_ablation100_qwen9b_catfix_finbench_ablation_rewrite_false` | 826 | 800 | 0.969 | 8/8 | yes |
| No LLM judge | finbench | `20260602_092549_20260602_ablation100_qwen9b_catfix_finbench_ablation_judge_false` | 812 | 800 | 0.985 | 8/8 | yes |
| Full PIPE-Cypher | finbench | `20260602_092703_20260602_ablation100_qwen9b_catfix_finbench_full_pipe_cypher` | 824 | 800 | 0.971 | 8/8 | yes |
| Unconstrained LLM | snb | `20260602_100133_20260602_ablation100_qwen9b_catfix_snb_unconstrained_local_llm` | 0 | 0 | 0.000 | 0/8 | yes |
| Reverse-only | snb | `20260602_100133_20260602_ablation100_qwen9b_catfix_snb_reverse_only` | 820 | 800 | 0.976 | 8/8 | yes |
| Validators+repair | snb | `20260602_100206_20260602_ablation100_qwen9b_catfix_snb_validators_repair` | 824 | 800 | 0.971 | 8/8 | yes |
| No retrieval | snb | `20260602_100239_20260602_ablation100_qwen9b_catfix_snb_ablation_retrieval_topk_0` | 809 | 800 | 0.989 | 8/8 | yes |
| No rewrite | snb | `20260602_103304_20260602_ablation100_qwen9b_catfix_snb_ablation_rewrite_false` | 834 | 800 | 0.959 | 8/8 | yes |
| No LLM judge | snb | `20260602_110508_20260602_ablation100_qwen9b_catfix_snb_ablation_judge_false` | 828 | 800 | 0.966 | 8/8 | yes |
| Full PIPE-Cypher | snb | `20260602_110543_20260602_ablation100_qwen9b_catfix_snb_full_pipe_cypher` | 824 | 800 | 0.971 | 8/8 | yes |

## Gate Rates

| Setting | Graph | Read-only | Syntax | Schema | Execution | Judge |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Unconstrained LLM | finbench | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| Reverse-only | finbench | 1.000 | 1.000 | 0.982 | 0.982 | 0.982 |
| Validators+repair | finbench | 1.000 | 1.000 | 1.000 | 1.000 | 0.960 |
| No retrieval | finbench | 1.000 | 1.000 | 1.000 | 1.000 | 0.977 |
| No rewrite | finbench | 1.000 | 1.000 | 1.000 | 1.000 | 0.969 |
| No LLM judge | finbench | 1.000 | 1.000 | 1.000 | 1.000 | 0.985 |
| Full PIPE-Cypher | finbench | 1.000 | 1.000 | 1.000 | 1.000 | 0.971 |
| Unconstrained LLM | snb | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| Reverse-only | snb | 1.000 | 1.000 | 0.998 | 0.998 | 0.976 |
| Validators+repair | snb | 1.000 | 1.000 | 0.998 | 0.998 | 0.971 |
| No retrieval | snb | 1.000 | 1.000 | 0.998 | 0.998 | 0.989 |
| No rewrite | snb | 1.000 | 1.000 | 0.998 | 0.998 | 0.959 |
| No LLM judge | snb | 1.000 | 1.000 | 0.998 | 0.998 | 0.966 |
| Full PIPE-Cypher | snb | 1.000 | 1.000 | 0.998 | 0.998 | 0.971 |

## Reporting Rule

This suite is large enough to be considered for paper reporting after a claim/evidence audit verifies run logs, model IDs, graph workloads, code revision, and failure analysis.
