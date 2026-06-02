# Ablation Suite Comparison

- Suites compared: 3
- Complete suites: 3
- Evidence-ready suites: 3
- Reporting note: Use this comparison only after each contributing suite has its own collection manifest and paper-readiness audit. Target-normalized coverage is the primary scale-comparison metric; raw accepted counts are expected to grow when target_per_category grows. Partial or target-25 suites are diagnostic inputs, not paper evidence.

## Suite Inventory

| Run prefix | Target/category | Target records | Seed | Complete | Evidence-ready | Model | Revision |
| --- | ---: | ---: | --- | --- | --- | --- | --- |
| 20260601_ablation50_qwen9b | 50 | 400 |  | yes | yes | Qwen/Qwen3.5-9B | b5d4898e4a5f5043c33114a7746e319590f38de1 |
| 20260602_ablation100_qwen9b_catfix | 100 | 800 |  | yes | yes | Qwen/Qwen3.5-9B | 4df5175396352e7ad695f6ad1c8ce14c493d6955 |
| 20260602_ablation50_qwen9b_seed17_catfix | 50 | 400 | 17 | yes | yes | Qwen/Qwen3.5-9B | 4df5175396352e7ad695f6ad1c8ce14c493d6955 |

## Cell Variation

| Graph | Setting | Suites | Target cov. mean | Target cov. range | Acceptance mean | Acceptance SD | Cat. target mean | Exec. mean | Judge mean | Missing suites |
| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |
| finbench | No LLM judge | 3 | 1.000 | 1.000-1.000 | 0.994 | 0.008 | 1.000 | 1.000 | 0.994 |  |
| finbench | No retrieval | 3 | 1.000 | 1.000-1.000 | 0.967 | 0.031 | 1.000 | 1.000 | 0.967 |  |
| finbench | No rewrite | 3 | 1.000 | 1.000-1.000 | 0.969 | 0.023 | 1.000 | 1.000 | 0.969 |  |
| finbench | Full PIPE-Cypher | 3 | 1.000 | 1.000-1.000 | 0.975 | 0.016 | 1.000 | 1.000 | 0.975 |  |
| finbench | Reverse-only | 3 | 1.000 | 1.000-1.000 | 0.994 | 0.011 | 1.000 | 0.994 | 0.994 |  |
| finbench | Unconstrained LLM | 3 | 0.000 | 0.000-0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |  |
| finbench | Validators+repair | 3 | 1.000 | 1.000-1.000 | 0.987 | 0.023 | 1.000 | 1.000 | 0.987 |  |
| snb | No LLM judge | 3 | 1.000 | 1.000-1.000 | 0.982 | 0.015 | 1.000 | 0.996 | 0.982 |  |
| snb | No retrieval | 3 | 1.000 | 1.000-1.000 | 0.993 | 0.004 | 1.000 | 0.996 | 0.993 |  |
| snb | No rewrite | 3 | 1.000 | 1.000-1.000 | 0.983 | 0.021 | 1.000 | 0.996 | 0.983 |  |
| snb | Full PIPE-Cypher | 3 | 1.000 | 1.000-1.000 | 0.987 | 0.014 | 1.000 | 0.996 | 0.987 |  |
| snb | Reverse-only | 3 | 1.000 | 1.000-1.000 | 0.989 | 0.011 | 1.000 | 0.996 | 0.989 |  |
| snb | Unconstrained LLM | 3 | 0.000 | 0.000-0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |  |
| snb | Validators+repair | 3 | 1.000 | 1.000-1.000 | 0.987 | 0.014 | 1.000 | 0.996 | 0.987 |  |
