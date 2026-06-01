# Target-Five Ablation Results

Date run: June 1, 2026, on `ds-serv6`.

Runtime:

- graphs: live LDBC FinBench SF0.1 Neo4j database on Bolt `7687`, and live LDBC SNB Neo4j database on Bolt `7688`;
- generation/judge endpoint: local `Qwen/Qwen3.5-9B` served through vLLM;
- target: five accepted examples per category across eight categories for each graph and setting;
- configs: materialized from `configs/experiment_matrix.yaml` under `configs/generated/finbench` and `configs/generated/snb`.

| Setting | Graph | Run directory | Records | Accepted | Acceptance | Categories at target |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| Strict unconstrained LLM | FinBench | `20260601_182730_20260601_ablation5_finbench_unconstrained_local_llm_strict` | 0 | 0 | 0.000 | 0/8 |
| Strict unconstrained LLM | SNB | `20260601_183657_20260601_ablation5_snb_unconstrained_local_llm` | 0 | 0 | 0.000 | 0/8 |
| Reverse-only | FinBench | `20260601_182553_20260601_ablation5_finbench_reverse_only` | 40 | 40 | 1.000 | 8/8 |
| Reverse-only | SNB | `20260601_183656_20260601_ablation5_snb_reverse_only` | 40 | 40 | 1.000 | 8/8 |
| Validators+repair | FinBench | `20260601_182551_20260601_ablation5_finbench_validators_repair` | 40 | 40 | 1.000 | 8/8 |
| Validators+repair | SNB | `20260601_183655_20260601_ablation5_snb_validators_repair` | 40 | 40 | 1.000 | 8/8 |
| No retrieval | FinBench | `20260601_182245_20260601_ablation5_finbench_ablation_retrieval_topk_0` | 41 | 40 | 0.976 | 8/8 |
| No retrieval | SNB | `20260601_183401_20260601_ablation5_snb_ablation_retrieval_topk_0` | 40 | 40 | 1.000 | 8/8 |
| No rewrite | FinBench | `20260601_182417_20260601_ablation5_finbench_ablation_rewrite_false` | 41 | 40 | 0.976 | 8/8 |
| No rewrite | SNB | `20260601_183527_20260601_ablation5_snb_ablation_rewrite_false` | 40 | 40 | 1.000 | 8/8 |
| No LLM judge | FinBench | `20260601_182549_20260601_ablation5_finbench_ablation_judge_false` | 40 | 40 | 1.000 | 8/8 |
| No LLM judge | SNB | `20260601_183653_20260601_ablation5_snb_ablation_judge_false` | 40 | 40 | 1.000 | 8/8 |
| Full PIPE-Cypher | FinBench | `20260601_182058_20260601_ablation5_finbench_full_pipe_cypher` | 41 | 40 | 0.976 | 8/8 |
| Full PIPE-Cypher | SNB | `20260601_183236_20260601_ablation5_snb_full_pipe_cypher` | 40 | 40 | 1.000 | 8/8 |

Interpretation:

- Strict unconstrained local template generation produced no usable records on either graph once seeded template fallback was disabled. This is the strongest small-ablation signal: raw local LLM generation is not enough for reliable private benchmark construction.
- Once reverse grounding and seeded workload structure are available, target-five generation saturates across FinBench and SNB variants. This makes the target-five ablation a sanity check for component removal, not a substitute for full-scale ablation.
- Treat this as an engineering sanity-check record only. The paper should not cite this table as experimental evidence; use scaled ablations, the full 3,000-example export, downstream evaluation, diversity statistics, and judge calibration for empirical claims.

An archival LaTeX table can be reproduced with:

```bash
python scripts/render_ablation_paper_table.py \
  artifacts/runs/20260601_182730_20260601_ablation5_finbench_unconstrained_local_llm_strict \
  artifacts/runs/20260601_182553_20260601_ablation5_finbench_reverse_only \
  artifacts/runs/20260601_182551_20260601_ablation5_finbench_validators_repair \
  artifacts/runs/20260601_182245_20260601_ablation5_finbench_ablation_retrieval_topk_0 \
  artifacts/runs/20260601_182417_20260601_ablation5_finbench_ablation_rewrite_false \
  artifacts/runs/20260601_182549_20260601_ablation5_finbench_ablation_judge_false \
  artifacts/runs/20260601_182058_20260601_ablation5_finbench_full_pipe_cypher \
  artifacts/runs/20260601_183657_20260601_ablation5_snb_unconstrained_local_llm \
  artifacts/runs/20260601_183656_20260601_ablation5_snb_reverse_only \
  artifacts/runs/20260601_183655_20260601_ablation5_snb_validators_repair \
  artifacts/runs/20260601_183401_20260601_ablation5_snb_ablation_retrieval_topk_0 \
  artifacts/runs/20260601_183527_20260601_ablation5_snb_ablation_rewrite_false \
  artifacts/runs/20260601_183653_20260601_ablation5_snb_ablation_judge_false \
  artifacts/runs/20260601_183236_20260601_ablation5_snb_full_pipe_cypher \
  --target-per-category 5 \
  --output artifacts/reports/tables_ablation5_results.tex
```
