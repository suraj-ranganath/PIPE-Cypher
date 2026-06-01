# Live Ablation Suite Summary

- Target per category: 25
- Expected graph workloads: finbench, snb
- Expected variants: unconstrained_local_llm, reverse_only, validators_repair, ablation_retrieval_topk_0, ablation_rewrite_false, ablation_judge_false, full_pipe_cypher
- Runs found: 14
- All expected runs finished: true
- Research reporting status: interim scaled checkpoint; larger final ablations preferred
- Metadata:
  - code_revision: `2122a86e457a3c0039367a09290dde120c660d68`
  - generation_model: `Qwen/Qwen3.5-9B`
  - judge_model: `Qwen/Qwen3.5-9B`
  - log_file: `logs/20260601_ablation25_qwen9b_retry1.log`
  - run_prefix: `20260601_ablation25_qwen9b_retry1`

| Setting | Graph | Run | Records | Accepted | Acceptance | Categories at target | Finished |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| Unconstrained LLM | finbench | `20260601_211604_20260601_ablation25_qwen9b_retry1_finbench_unconstrained_local_llm` | 0 | 0 | 0.000 | 0/8 | yes |
| Reverse-only | finbench | `20260601_211605_20260601_ablation25_qwen9b_retry1_finbench_reverse_only` | 200 | 200 | 1.000 | 8/8 | yes |
| Validators+repair | finbench | `20260601_211613_20260601_ablation25_qwen9b_retry1_finbench_validators_repair` | 200 | 200 | 1.000 | 8/8 | yes |
| No retrieval | finbench | `20260601_211624_20260601_ablation25_qwen9b_retry1_finbench_ablation_retrieval_topk_0` | 204 | 200 | 0.980 | 8/8 | yes |
| No rewrite | finbench | `20260601_212403_20260601_ablation25_qwen9b_retry1_finbench_ablation_rewrite_false` | 206 | 200 | 0.971 | 8/8 | yes |
| No LLM judge | finbench | `20260601_213153_20260601_ablation25_qwen9b_retry1_finbench_ablation_judge_false` | 200 | 200 | 1.000 | 8/8 | yes |
| Full PIPE-Cypher | finbench | `20260601_213159_20260601_ablation25_qwen9b_retry1_finbench_full_pipe_cypher` | 207 | 200 | 0.966 | 8/8 | yes |
| Unconstrained LLM | snb | `20260601_213959_20260601_ablation25_qwen9b_retry1_snb_unconstrained_local_llm` | 0 | 0 | 0.000 | 0/8 | yes |
| Reverse-only | snb | `20260601_214000_20260601_ablation25_qwen9b_retry1_snb_reverse_only` | 202 | 200 | 0.990 | 8/8 | yes |
| Validators+repair | snb | `20260601_214006_20260601_ablation25_qwen9b_retry1_snb_validators_repair` | 202 | 200 | 0.990 | 8/8 | yes |
| No retrieval | snb | `20260601_214012_20260601_ablation25_qwen9b_retry1_snb_ablation_retrieval_topk_0` | 202 | 200 | 0.990 | 8/8 | yes |
| No rewrite | snb | `20260601_214743_20260601_ablation25_qwen9b_retry1_snb_ablation_rewrite_false` | 202 | 200 | 0.990 | 8/8 | yes |
| No LLM judge | snb | `20260601_215512_20260601_ablation25_qwen9b_retry1_snb_ablation_judge_false` | 202 | 200 | 0.990 | 8/8 | yes |
| Full PIPE-Cypher | snb | `20260601_215518_20260601_ablation25_qwen9b_retry1_snb_full_pipe_cypher` | 202 | 200 | 0.990 | 8/8 | yes |

## Reporting Rule

Treat this as an interim scaled checkpoint. It can guide debugging and appendix planning, but larger target-per-category runs are preferred for final reviewer-facing ablation claims when compute permits.
