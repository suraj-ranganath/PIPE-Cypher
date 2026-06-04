# Live Ablation Suite Summary

- Target per category: 100
- Expected graph workloads: snb
- Expected variants: unconstrained_local_llm
- Runs found: 2
- All expected runs finished: false
- Research reporting status: incomplete; do not report as paper evidence
- Metadata:
  - code_revision: `9c90c18d84509ed0048b0f45876b814ae9e7460d-dirty-3927676a640f9ad550eb07a1e24911462978630e`
  - generation_model: `Qwen/Qwen3.5-9B`
  - judge_model: `Qwen/Qwen3.5-9B`
  - log_file: `logs/20260603_unconstrained_attempts_qwen9b_snb.log`
  - run_prefix: `20260603_unconstrained_attempts_qwen9b_snb`
  - run_seed: ``

| Setting | Graph | Run | Attempts | Records | Accepted | Acceptance | Categories at target | Finished |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| Unconstrained LLM | snb | `20260603_041956_20260603_unconstrained_attempts_qwen9b_snb_snb_unconstrained_local_llm` | 2000 | 2000 | 50 | 0.025 | 0/8 | yes |
| Unconstrained LLM | snb | `20260603_044238_20260603_unconstrained_attempts_qwen9b_snb_unconstrained_local_llm` | 49 | 49 | 0 | 0.000 | 0/8 | no |

## Gate Rates

| Setting | Graph | Read-only | Syntax | Schema | Execution | Judge |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Unconstrained LLM | snb | 1.000 | 0.998 | 0.599 | 0.478 | 0.144 |
| Unconstrained LLM | snb | 1.000 | 1.000 | 0.776 | 0.449 | 0.327 |

## Incomplete Runs

- snb / unconstrained_local_llm: `20260603_044238_20260603_unconstrained_attempts_qwen9b_snb_unconstrained_local_llm`

## Reporting Rule

Do not include this suite in the paper or appendix: at least one expected graph/variant run is missing or still active.
