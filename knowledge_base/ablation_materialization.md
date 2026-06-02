# Ablation Materialization

Date checked: June 1, 2026.

The experiment matrix in `configs/experiment_matrix.yaml` is now materialized into runnable per-graph configs:

```bash
python scripts/materialize_experiments.py \
  --matrix configs/experiment_matrix.yaml \
  --base-config configs/finbench_full.yaml \
  --output-dir configs/generated/finbench \
  --target-per-category 5

python scripts/materialize_experiments.py \
  --matrix configs/experiment_matrix.yaml \
  --base-config configs/snb_full.yaml \
  --output-dir configs/generated/snb \
  --target-per-category 5
```

Observed output:

```text
wrote_configs=15 output_dir=configs/generated/finbench
wrote_configs=14 output_dir=configs/generated/snb
loaded_generated_configs=29
```

The generated configs cover:

- baselines: `unconstrained_local_llm`, `reverse_only`, `validators_repair`, and `full_pipe_cypher`;
- retrieval ablations: `retrieval_top_k` in `{0, 2, 4}`;
- judge ablations: judge disabled/enabled;
- rewrite ablations: `generation.normalize_cypher` disabled/enabled;
- model ablations: current reported runs standardize on `Qwen/Qwen3.5-9B`; do not queue larger-model comparisons unless the owner explicitly reopens that study;
- graph-mix ablations: FinBench-only and FinBench+SNB.

Each generated config targets one graph profile. `finbench_only` is emitted only under `configs/generated/finbench`; `finbench_plus_snb` is emitted under both graph directories and should be exported as a combined benchmark after both graph runs complete.

The rewrite ablation is now a real pipeline switch. Default configs preserve Cypher normalization, including adding `RETURN DISTINCT` when a query returns without `DISTINCT`. Setting `generation.normalize_cypher: false` leaves generated Cypher cleaned but not normalized, allowing the paper to measure the contribution of parser-aware rewrite/normalization separately from validation, execution, and judge gates.

The unconstrained local-LLM baseline now sets `generation.allow_seed_template_fallback: false`, `generation.deterministic_cypher_fallback: false`, `generation.normalize_cypher: false`, `generation.retrieval_top_k: 0`, and `judge.enabled: false`. This prevents the baseline from silently recovering with PIPE-Cypher seed templates when local template generation fails.
