# Live Ablation Suite Summary

- Target per category: 100
- Expected graph workloads: finbench, snb
- Expected variants: unconstrained_local_llm
- Runs found: 2
- All expected runs finished: true
- Research reporting status: candidate paper evidence after claim/evidence audit
- Metadata:
  - code_revision: `9c90c18d84509ed0048b0f45876b814ae9e7460d-dirty-3927676a640f9ad550eb07a1e24911462978630e`
  - generation_model: `Qwen/Qwen3.5-9B`
  - judge_model: `Qwen/Qwen3.5-9B`
  - log_file: `logs/20260603_unconstrained_attempts_qwen9b.log,logs/20260603_unconstrained_attempts_qwen9b_snb.log`
  - note: `completed_unconstrained_stress_baselines_only_aborted_duplicate_excluded`
  - run_prefix: `20260603_unconstrained_attempts_qwen9b_stress_baseline`

| Setting | Graph | Run | Attempts | Records | Accepted | Acceptance | Categories at target | Finished |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| Unconstrained LLM | finbench | `20260603_041459_20260603_unconstrained_attempts_qwen9b_finbench_unconstrained_local_llm` | 422 | 422 | 200 | 0.474 | 2/8 | yes |
| Unconstrained LLM | snb | `20260603_041956_20260603_unconstrained_attempts_qwen9b_snb_snb_unconstrained_local_llm` | 2000 | 2000 | 50 | 0.025 | 0/8 | yes |

## Gate Rates

| Setting | Graph | Read-only | Syntax | Schema | Execution | Judge |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Unconstrained LLM | finbench | 1.000 | 1.000 | 0.806 | 0.723 | 0.557 |
| Unconstrained LLM | snb | 1.000 | 0.998 | 0.599 | 0.478 | 0.144 |

## Reporting Rule

This suite is large enough to be considered for paper reporting after a claim/evidence audit verifies run logs, model IDs, graph workloads, code revision, and failure analysis.
