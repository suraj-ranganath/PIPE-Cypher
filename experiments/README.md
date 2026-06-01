# Experiment Plan

The final experiment suite targets 3,000 accepted NL-Cypher benchmark pairs:

- 2,000 from LDBC FinBench.
- 1,000 from LDBC SNB.
- Balanced across eight categories and three difficulty levels.

## Baselines

1. `unconstrained_local_llm`: local Qwen generation with schema text only.
2. `reverse_only`: PIPE-KG-style reverse grounding ported to Cypher.
3. `validators_repair`: deterministic validation, execution, and repair without judge.
4. `full_pipe_cypher`: constrained prompting, retrieval, rewrite, execution validation, diversity caps, and LLM judge.

## Core Metrics

- generation yield;
- syntax-valid rate;
- schema-valid rate;
- read-only safety rate;
- execution success rate;
- non-empty result rate;
- repair success rate;
- judge pass rate;
- label/relationship/property coverage;
- entity repetition and template signature diversity;
- downstream Text2Cypher execution accuracy and answer F1.

## First Smoke Commands

```bash
python scripts/inspect_schema.py --config configs/local_smoke.yaml --reference-only --output artifacts/smoke/schema_finbench_reference.json
python scripts/run_pipeline.py --config configs/local_smoke.yaml --offline-smoke --run-name offline_smoke
pytest
```

## Full Run Sketch

```bash
# On ds-serv6 in tmux
CUDA_VISIBLE_DEVICES=2,3 bash scripts/serve_qwen_vllm.sh Qwen/Qwen3.5-9B

# After graph loading and schema introspection
python scripts/run_pipeline.py --config configs/finbench_full.yaml --run-name finbench_full
python scripts/run_pipeline.py --config configs/snb_full.yaml --run-name snb_full
```

Materialize baseline and ablation configs:

```bash
python scripts/materialize_experiments.py \
  --matrix configs/experiment_matrix.yaml \
  --base-config configs/finbench_full.yaml \
  --output-dir configs/generated/finbench \
  --target-per-category 50

python scripts/materialize_experiments.py \
  --matrix configs/experiment_matrix.yaml \
  --base-config configs/snb_full.yaml \
  --output-dir configs/generated/snb \
  --target-per-category 50

bash configs/generated/finbench/run_commands.sh
bash configs/generated/snb/run_commands.sh
```

The generated configs now cover all ablations in `configs/experiment_matrix.yaml`: retrieval depth, judge on/off, rewrite on/off, model choice, and graph mix. Since each `run_pipeline.py` config targets one graph profile, `finbench_only` materializes only under `configs/generated/finbench`, while `finbench_plus_snb` materializes under both graph directories and should be exported as a combined benchmark after both runs complete.

The June 1, 2026 target-five FinBench+SNB ablation run is summarized in `../knowledge_base/target5_ablation_results.md`. It is a live graph sanity check rather than a substitute for full-scale ablations.

For paper-facing ablations, target-50 is the minimum scale and target-100 or
repeated target-50 is preferred when compute permits. The active remote queue is
tracked in `remote_ablation_queue.yaml` and can be monitored without fetching
partial artifacts. The monitor prints each suite's `next_action` and safe
`collection_command`:

Repeated suites should set `RUN_SEED` and include the seed in `RUN_PREFIX`.
Seeded ablation launches pass the seed into `run_pipeline.py --random-seed` and
store it in run summaries, suite metadata, and collection manifests. This makes
repeated target-50 or target-100 evidence auditable as repeated-seed evidence
rather than an uncontrolled rerun.

```bash
python scripts/monitor_remote_ablation_queue.py \
  --queue experiments/remote_ablation_queue.yaml
```

## Tracked Full-Run Snapshot

The full Qwen3.5-9B fallback export is not committed as JSONL because generated
artifacts are ignored. A compact verification snapshot is tracked in:

```text
snapshots/20260601_live_full_qwen9b/
```

It contains the full export manifest hash, file checksums, aggregate counts, and
16 representative examples: one per graph/category cell.

## Downstream Text2Cypher Evaluation

Predictions should be JSONL with:

```json
{"question": "...", "predicted_cypher": "MATCH ... RETURN DISTINCT ..."}
```

Evaluate with:

```bash
python scripts/evaluate_predictions.py \
  --config configs/finbench_full.yaml \
  --gold artifacts/runs/<run_id>/records.jsonl \
  --predictions artifacts/predictions/<model>.jsonl \
  --output artifacts/evaluations/<model>_finbench.jsonl
```

## Judge Calibration Audit

The generation gate is automated, but the paper should include a small human audit
to estimate judge reliability.

```bash
python scripts/sample_judge_audit.py \
  --records artifacts/runs/<run_id>/records.jsonl \
  --output artifacts/audits/<run_id>_judge_audit.csv \
  --n 100

# After filling human_accept in the CSV:
python scripts/analyze_judge_audit.py \
  --audit artifacts/audits/<run_id>_judge_audit.csv
```
