# Reproducibility

Everything below runs on public graphs. Steps 1 to 4 rebuild the benchmark and
need a graph and model endpoints; step 5 recomputes the paper's analyses from
the files under `release/` and needs neither models nor, for most scripts, a
graph.

## 0. Environment

Python 3.11 or later. `pip install -e ".[dev]"`, then `python -m pytest -q`.
Neo4j 5.26 Community was used for all experiments.

## 1. Graphs

- LDBC FinBench: `scripts/generate_finbench_import_cypher.py`, `scripts/load_finbench_neo4j.sh`
- LDBC SNB: `scripts/generate_snb_import_cypher.py`, `scripts/load_snb_neo4j.sh`
- Recommendations, Northwind, FinCEN: `scripts/fetch_neo4j_example_graphs.sh`
- `scripts/start_neo4j_community.sh` starts a local instance. Use a read-only user.

## 2. Build

Configs: `configs/finbench_v3.yaml`, `configs/snb_v3.yaml` (main build),
`configs/t2c_*_v3.yaml` (public graphs), `configs/*_v3_nobind.yaml` (reverse
querying switched off), `configs/*_v3_gen_qwen35_9b.yaml` (9B generator),
`configs/wide_v3.yaml` (132-label schema). Set the graph URI and the model
endpoint in the config or through the environment variables named in
`.env.example`.

```bash
# PREFIX  COST_CAP_USD  PARALLEL  "CONFIG|NEO4J_URI|TARGET_PER_CATEGORY|SEEDS"
scripts/launch_cells.sh my_build 5 16 "configs/finbench_v3.yaml|bolt://127.0.0.1:7687|125|1 2"
python scripts/export_benchmark.py --help
```

The convention sheet and the frozen checklist judge prompt are in
`pipecypher/prompts.py`; the difficulty model is `configs/difficulty_v3.json`.

## 3. Outside audit

`scripts/audit_checklist_judge.py` re-judges candidates with any chat model;
`scripts/audit_decisions_model.py` does the same with a decision model
(`--format v3` is the compact item-first state).

## 4. Downstream evaluation

```bash
python scripts/generate_text2cypher_predictions.py --help
python scripts/evaluate_benchmark_predictions.py --help
```

Model lists: `configs/downstream_models_naacl2027.yaml` and
`configs/downstream_models_hosted_naacl2027.yaml`.

## 5. Analyses from the released files

| Paper result | Script | Input |
|---|---|---|
| Scores on subsets with fewer doubtful references | `scripts/reference_quality_sensitivity.py` | predictions, audit verdicts, human labels |
| Corrected-reference rescoring | `scripts/corrected_reference_rescoring.py` | predictions, live graphs |
| Row-order rescoring | `scripts/order_aware_rescoring.py` | predictions, live graphs |
| Text metrics against execution | `scripts/query_metric_comparison.py`, `scripts/text_vs_execution_metrics.py` | predictions |
| Refresh after schema migration | `scripts/audit_benchmark_refresh.py`, `configs/migrations/` | live graph copy |
| Aggregated tables | `scripts/collect_naacl_v3_results.py` | run and evaluation directories |

Scripts default to paths under `artifacts/`; pass the corresponding
`release/` paths, or copy `release/` to `artifacts/` with the layout the
script's `--help` describes. The outputs we obtained are in
`release/results/`.

## 6. Refresh

`configs/migrations/finbench/` holds the four schema migrations and two data
edits of the refresh study; `scripts/audit_benchmark_refresh.py` re-executes
stale references, rewrites renamed ones, and lists the items to regenerate.

## Human validation

`release/human_validation/items_70.jsonl` holds the audited items,
`key.jsonl` the strata and weights, `labels.jsonl` each annotator's label
(annotators A and B), and `adjudicated_labels.json` the labels resolved after
discussion. `pipecypher/human_validation.py` computes the reweighted
estimates and intervals.
