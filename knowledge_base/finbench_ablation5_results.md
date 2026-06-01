# FinBench Target-Five Ablation Results

Note: `knowledge_base/target5_ablation_results.md` is now the combined FinBench+SNB target-five ablation record. This file preserves the FinBench-only subset.

Date run: June 1, 2026, on `ds-serv6`.

Runtime:

- graph: live LDBC FinBench SF0.1 Neo4j database on Bolt `7687`;
- generation/judge endpoint: local `Qwen/Qwen3.5-9B` served through vLLM;
- target: five accepted examples per category across eight categories;
- configs: materialized from `configs/experiment_matrix.yaml` under `configs/generated/finbench`.

| Setting | Run directory | Records | Accepted | Acceptance | Categories at target |
| --- | --- | ---: | ---: | ---: | ---: |
| Strict unconstrained LLM | `20260601_182730_20260601_ablation5_finbench_unconstrained_local_llm_strict` | 0 | 0 | 0.000 | 0/8 |
| Reverse-only | `20260601_182553_20260601_ablation5_finbench_reverse_only` | 40 | 40 | 1.000 | 8/8 |
| Validators+repair | `20260601_182551_20260601_ablation5_finbench_validators_repair` | 40 | 40 | 1.000 | 8/8 |
| No retrieval | `20260601_182245_20260601_ablation5_finbench_ablation_retrieval_topk_0` | 41 | 40 | 0.976 | 8/8 |
| No rewrite | `20260601_182417_20260601_ablation5_finbench_ablation_rewrite_false` | 41 | 40 | 0.976 | 8/8 |
| No LLM judge | `20260601_182549_20260601_ablation5_finbench_ablation_judge_false` | 40 | 40 | 1.000 | 8/8 |
| Full PIPE-Cypher | `20260601_182058_20260601_ablation5_finbench_full_pipe_cypher` | 41 | 40 | 0.976 | 8/8 |

Interpretation:

- The strict unconstrained local-LLM baseline disables seeded template fallback, retrieval, normalization/rewrite, repair, deterministic Cypher fallback, and the LLM judge. It produced no records because the local model did not return parseable template JSON.
- Once reverse grounding and seeded workload structure are available, target-five FinBench generation saturates across variants. This means the small ablation is useful as a sanity check but not strong enough to separate later pipeline gates by yield.
- The paper should use this table to justify the need for structured workload generation and should rely on the 3,000-example full export, full-test downstream evaluation, diversity statistics, and judge calibration for the main contribution claims.

The paper table is reproducibly generated with:

```bash
python scripts/render_ablation_paper_table.py \
  artifacts/runs/20260601_182730_20260601_ablation5_finbench_unconstrained_local_llm_strict \
  artifacts/runs/20260601_182553_20260601_ablation5_finbench_reverse_only \
  artifacts/runs/20260601_182551_20260601_ablation5_finbench_validators_repair \
  artifacts/runs/20260601_182245_20260601_ablation5_finbench_ablation_retrieval_topk_0 \
  artifacts/runs/20260601_182417_20260601_ablation5_finbench_ablation_rewrite_false \
  artifacts/runs/20260601_182549_20260601_ablation5_finbench_ablation_judge_false \
  artifacts/runs/20260601_182058_20260601_ablation5_finbench_full_pipe_cypher \
  --target-per-category 5 \
  --output paper_emnlp2026_industry/tables_ablation5_results.tex
```
