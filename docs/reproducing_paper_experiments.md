# Reproducing the PIPE-Cypher Experiments

This page documents the paper experiments from the public library branch. The
research branch contains the frozen paper source and submission artifacts; this
branch contains the code, configs, and operational instructions needed to rerun
the same study or adapt it to a new enterprise graph.

For anonymous review, include the benchmark export archive in the supplementary
materials or through an anonymous artifact link. To reproduce results from
scratch, load the graphs below, serve the listed local models, run the configs
at the stated targets, and regenerate the summaries with the scripts in this
repository. The public release may replace this note with the permanent dataset
URL.

## Paper Experiment Matrix

| Experiment | Graphs | Main configs/scripts | Paper-scale target | Primary outputs |
| --- | --- | --- | --- | --- |
| Full benchmark generation | FinBench, SNB | `configs/finbench_full.yaml`, `configs/snb_full.yaml`, `scripts/run_pipeline.py`, `scripts/export_benchmark.py` | 2,000 FinBench + 1,000 SNB accepted examples | Benchmark JSONL splits, benchmark card, generation/gate summaries |
| ICIJ onboarding | ICIJ Offshore Leaks | `configs/icij_offshoreleaks_full.yaml`, `scripts/run_pipeline.py` | 800 accepted examples, 100 per category | Third-graph onboarding summary |
| Target-100 ablations | FinBench, SNB | `configs/generated/*/*.yaml`, scaled to target 100 | 7 variants x 2 graphs | Acceptance, gate, and category-completion tables |
| Repeated target-size ablations | FinBench, SNB | Same ablation configs, scaled to target 50 and 100 | 3 governed suites | Stability and target-coverage summaries |
| Diversity-governed selection | Full benchmark export | `scripts/select_diverse_benchmark_subset.py`, `scripts/analyze_benchmark_diversity.py` | Balanced graph/category subset | Distinct-n, self-BLEU, signature, schema, and operator coverage |
| Judge calibration | FinBench, SNB | `scripts/sample_judge_audit.py`, `scripts/analyze_judge_audit.py` | 80 stratified rows, external annotator | Agreement, kappa, precision/recall/specificity CIs |
| Downstream transfer | Full benchmark test split | `scripts/generate_text2cypher_predictions.py`, `scripts/evaluate_benchmark_predictions.py` | 296 held-out examples per model/mode | Execution accuracy, answer F1, parse/schema/execution success |
| Few-shot controls | Full benchmark train/test split | `scripts/generate_text2cypher_predictions.py`, `scripts/audit_downstream_fewshot_leakage.py`, `scripts/summarize_downstream_fewshot_controls.py` | Zero-shot, ordered, no-signature, random seeds 13/17/23 | Leakage-aware example-bank results |
| Governance, rewrite, redaction, runtime audits | Full run records and benchmark export | `scripts/audit_governance_failures.py`, `scripts/audit_rewrite_impact.py`, `scripts/audit_redaction_policy.py`, `scripts/summarize_runtime_accounting.py` | Complete paper-facing export | Audit tables and safety/privacy evidence |

## Environment

Install the package and deterministic test dependencies:

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

Serve the generation/judge model as a local OpenAI-compatible endpoint. The
paper generation and judge runs used local `Qwen/Qwen3.5-9B`; the default
configs point at `http://localhost:8000/v1`.

```bash
CUDA_VISIBLE_DEVICES=0,1 \
PORT=8000 \
scripts/serve_qwen_vllm.sh Qwen/Qwen3.5-9B

python scripts/check_llm_endpoint.py \
  --base-url http://localhost:8000/v1 \
  --model Qwen/Qwen3.5-9B
```

The paper configs use:

| Setting | Value |
| --- | --- |
| Generation model | `Qwen/Qwen3.5-9B` |
| Judge model | `Qwen/Qwen3.5-9B` |
| Embeddings | BGE-M3 or another local embedding model |
| Generation temperature | `0.2` |
| Judge temperature | `0.0` |
| Generation max tokens | `1024` |
| Endpoint timeout | `180` seconds |
| Reasoning traces | disabled and stripped before JSON parsing |
| Repair attempts | `2` in full governed runs |
| Retrieval examples | `4` in full governed runs |
| Non-empty execution | required for generated benchmark examples |
| Generated query limit | `300` for FinBench/ICIJ, `200` for SNB |

For downstream model evaluation, serve each local model at an
OpenAI-compatible endpoint and pass its exact model name to
`scripts/generate_text2cypher_predictions.py`. Do not mix endpoints or model
IDs within a run directory.

## Graph Setup

The paper used three public proxy graphs. FinBench and SNB are the benchmark
generation graphs; ICIJ Offshore Leaks is a third-graph onboarding audit.

| Graph | Role | Nodes | Relationships | Labels | Relationship types | Patterns | Node props | Rel props |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| LDBC FinBench | Primary finance/risk workload | 10,006 | 57,622 | 5 | 9 | 13 | 37 | 32 |
| LDBC SNB | Secondary social/general workload | 34,735 | 70,842 | 14 | 15 | 59 | 62 | 5 |
| ICIJ Offshore Leaks | Third-graph onboarding | 2,016,523 | 3,339,267 | 5 | 14 | 64 | 82 | 48 |

The loader scripts default to Neo4j Community `5.26.0`. The ICIJ script loads
the public `icij-offshoreleaks-5.13.0.dump`; FinBench uses the generated
`SCALE_FACTOR=0.1` snapshot; SNB uses the public Cypher implementation's
`test-data/vanilla` CSVs.

Fetch public graph sources:

```bash
GIT_DEPTH=1 scripts/fetch_ldbc_sources.sh external
```

Generate the FinBench snapshot used by the loader. The public script defaults
to `SCALE_FACTOR=0.1`, which is the scale used for the paper graph statistics
above.

```bash
SCALE_FACTOR=0.1 scripts/run_finbench_datagen.sh
```

Start separate Neo4j Community instances and load FinBench and SNB on their
paper ports:

```bash
# FinBench on bolt://localhost:7687
RUN_ROOT=$HOME/pipecypher-neo4j \
SESSION=pipecypher_finbench \
BOLT_PORT=7687 \
HTTP_PORT=7474 \
AUTH_ENABLED=false \
scripts/start_neo4j_community.sh

SNAPSHOT_DIR=$HOME/pipecypher-runs/finbench_sf0.1/data/snapshot \
BOLT_URI=bolt://localhost:7687 \
AUTH_ENABLED=false \
scripts/load_finbench_neo4j.sh

# SNB on bolt://localhost:7688
RUN_ROOT=$HOME/pipecypher-neo4j-snb \
SESSION=pipecypher_snb \
BOLT_PORT=7688 \
HTTP_PORT=7475 \
AUTH_ENABLED=false \
scripts/start_neo4j_community.sh

BOLT_URI=bolt://localhost:7688 \
AUTH_ENABLED=false \
scripts/load_snb_neo4j.sh
```

Load ICIJ Offshore Leaks on a separate instance:

```bash
FETCH_DUMP=true scripts/fetch_icij_offshoreleaks.sh

RUN_ROOT=$HOME/pipecypher-neo4j-icij \
BOLT_PORT=7689 \
HTTP_PORT=7476 \
HEAP_INITIAL=6G \
HEAP_MAX=12G \
PAGECACHE=8G \
scripts/load_icij_neo4j_dump.sh
```

After each graph is live, introspect or refresh the schema files used by the
configs:

```bash
python scripts/inspect_schema.py \
  --config configs/finbench_full.yaml \
  --output configs/schema_finbench.json

python scripts/inspect_schema.py \
  --config configs/snb_full.yaml \
  --output configs/schema_snb.json

python scripts/inspect_schema.py \
  --config configs/icij_offshoreleaks_full.yaml \
  --output configs/schema_icij_offshoreleaks_live.json
```

## Full Benchmark Generation

The full paper benchmark used eight workload categories:

```text
simple_retrieval
complex_retrieval
simple_aggregation
complex_aggregation
boolean_existence
negation_difference
path_temporal_transaction
ranking_topk
```

Run the two full configs:

```bash
python scripts/validate_config.py --check-paths configs/finbench_full.yaml
python scripts/estimate_run_capacity.py \
  --config configs/finbench_full.yaml \
  --target-per-category 250 \
  --assumed-accept-rate 0.60 \
  --format markdown
python scripts/run_pipeline.py \
  --config configs/finbench_full.yaml \
  --run-name finbench_full_qwen35_9b

python scripts/validate_config.py --check-paths configs/snb_full.yaml
python scripts/estimate_run_capacity.py \
  --config configs/snb_full.yaml \
  --target-per-category 125 \
  --assumed-accept-rate 0.65 \
  --format markdown
python scripts/run_pipeline.py \
  --config configs/snb_full.yaml \
  --run-name snb_full_qwen35_9b
```

Export the accepted rows into a single benchmark package:

```bash
python scripts/export_benchmark.py \
  --records artifacts/runs/<finbench_run_id>/records.jsonl \
            artifacts/runs/<snb_run_id>/records.jsonl \
  --output-dir artifacts/benchmarks/pipe_cypher_full_qwen35_9b \
  --split-seed 20260604_live_full_qwen9b_reviewfix \
  --result-sample-limit 5

python scripts/render_benchmark_card.py \
  --config configs/finbench_full.yaml \
  --benchmark-dir artifacts/benchmarks/pipe_cypher_full_qwen35_9b \
  --title "PIPE-Cypher full benchmark" \
  --output artifacts/benchmarks/pipe_cypher_full_qwen35_9b/BENCHMARK_CARD.md
```

Expected paper-scale result:

| Graph | Candidates | Accepted | Acceptance | Categories at target |
| --- | ---: | ---: | ---: | ---: |
| FinBench | 3,405 | 2,000 | 0.587 | 8/8 |
| SNB | 1,520 | 1,000 | 0.658 | 8/8 |
| Total | 4,925 | 3,000 | 0.609 | 16/16 |

All 3,000 accepted examples passed read-only, syntax, schema, execution, and
judge gates. The final artifact contained 250 FinBench examples and 125 SNB
examples per category, with 1,569 easy and 1,431 medium examples.

## ICIJ Third-Graph Onboarding

ICIJ uses the same pipeline on a larger and structurally different public
finance/compliance graph:

```bash
python scripts/validate_config.py --check-paths configs/icij_offshoreleaks_full.yaml
python scripts/estimate_run_capacity.py \
  --config configs/icij_offshoreleaks_full.yaml \
  --target-per-category 100 \
  --assumed-accept-rate 0.80 \
  --format markdown
python scripts/run_pipeline.py \
  --config configs/icij_offshoreleaks_full.yaml \
  --run-name icij_offshoreleaks_target100_qwen35_9b
```

Expected paper-scale result:

| Graph | Candidates | Accepted | Acceptance | Categories at target | Sparse schema-derived accepts |
| --- | ---: | ---: | ---: | ---: | ---: |
| ICIJ Offshore Leaks | 983 | 800 | 0.814 | 8/8 | complex aggregation 97, negation 28, ranking 98 |

This run is important for enterprise onboarding because it exercises arbitrary
schema introspection, sparse-category augmentation, value redaction, and
category balance outside the two LDBC workloads.

## Target-100 Ablations

The checked-in generated ablation configs under `configs/generated/` are small
templates. For the paper-scale target-100 suite, copy them to a run directory
and set `generation.target_per_category: 100` before launch:

```bash
mkdir -p artifacts/configs/ablation_target100/finbench
cp configs/generated/finbench/*.yaml artifacts/configs/ablation_target100/finbench/

mkdir -p artifacts/configs/ablation_target100/snb
cp configs/generated/snb/*.yaml artifacts/configs/ablation_target100/snb/

python - <<'PY'
from pathlib import Path
import yaml

for path in Path("artifacts/configs/ablation_target100").glob("*/*.yaml"):
    data = yaml.safe_load(path.read_text())
    data.setdefault("generation", {})["target_per_category"] = 100
    path.write_text(yaml.safe_dump(data, sort_keys=False))
PY
```

Validate and run every graph/variant cell:

```bash
for graph in finbench snb; do
  for config in artifacts/configs/ablation_target100/$graph/*.yaml; do
    python scripts/validate_config.py --check-paths "$config"
    variant=$(basename "$config" .yaml)
    python scripts/run_pipeline.py \
      --config "$config" \
      --run-name "target100_${graph}_${variant}"
  done
done
```

Summarize the suite:

```bash
python scripts/summarize_live_ablation_suite.py \
  --glob 'artifacts/runs/target100_*' \
  --target-per-category 100 \
  --category-count 8 \
  --min-paper-target 50 \
  --output-json artifacts/reports/ablation_target100_summary.json \
  --output-md artifacts/reports/ablation_target100_summary.md \
  --output-tex artifacts/reports/ablation_target100_summary.tex \
  --output-quality-tex artifacts/reports/ablation_target100_quality.tex
```

Expected target-100 headline results:

| Variant | FinBench accepted/records | SNB accepted/records | Interpretation |
| --- | ---: | ---: | --- |
| Unconstrained local LLM | 200/422 | 50/2,000 | Weak baseline; poor category completion |
| Reverse-only | 800/815 | 800/820 | Reverse grounding makes examples answerable |
| Validators + repair | 800/833 | 800/824 | Deterministic governance keeps quality high |
| No retrieval | 800/819 | 800/809 | Retrieval is not required for yield at this scale |
| No rewrite | 800/826 | 800/834 | Rewrites were conservative in this run |
| No LLM judge | 800/812 | 800/828 | Post-hoc judge analysis separates yield from review |
| Full PIPE-Cypher | 800/824 | 800/824 | Reliable category completion with all gates enabled |

The variant names correspond to these config changes:

| Variant | `template_source` | Retrieval `top_k` | Repair attempts | Deterministic fallback | Seed-template fallback | Normalize/rewrite | Judge gate |
| --- | --- | ---: | ---: | --- | --- | --- | --- |
| Unconstrained local LLM | `llm` | 0 | 0 | false | false | false | false |
| Reverse-only | `default` | 0 | 0 | true | true | false | false |
| Validators + repair | `mixed` | 0 | 2 | true | true | true | false |
| No retrieval | `mixed` | 0 | 2 | true | true | true | true |
| No rewrite | `mixed` | 4 | 2 | true | true | false | true |
| No LLM judge | `mixed` | 4 | 2 | true | true | true | false |
| Full PIPE-Cypher | `mixed` | 4 | 2 | true | true | true | true |

For repeated target-size evidence, run the governed variants at
`target_per_category: 50` and `target_per_category: 100`, recording explicit
seeds such as:

```bash
python scripts/run_pipeline.py \
  --config artifacts/configs/ablation_target50/finbench/full_pipe_cypher.yaml \
  --run-name target50_seed17_finbench_full_pipe_cypher \
  --random-seed 17
```

The paper reports three complete governed suites with full target coverage in
all governed graph/variant cells.

## Diversity-Governed Selection and Diagnostics

Run diversity diagnostics on the full export:

```bash
python scripts/analyze_benchmark_diversity.py \
  --benchmark artifacts/benchmarks/pipe_cypher_full_qwen35_9b/all.jsonl \
  --schema configs/schema_finbench.json \
  --schema configs/schema_snb.json \
  --self-bleu-sample-size 200 \
  --output-json artifacts/reports/diversity_full.json \
  --output-tex artifacts/reports/diversity_full.tex \
  --output-signature-tex artifacts/reports/diversity_signatures.tex
```

Select a diversity-governed, signature-disjoint subset:

```bash
python scripts/select_diverse_benchmark_subset.py \
  --benchmark artifacts/benchmarks/pipe_cypher_full_qwen35_9b/all.jsonl \
  --schema configs/schema_finbench.json \
  --schema configs/schema_snb.json \
  --output-dir artifacts/benchmarks/pipe_cypher_diverse_signature_disjoint \
  --target-per-graph-category 50 \
  --split-mode signature_disjoint \
  --seed 13 \
  --self-bleu-sample-size 200 \
  --max-signature-share 0.20 \
  --max-template-family-share 0.25
```

Expected diversity comparison:

| Metric | Random balanced subset | Diversity-governed subset |
| --- | ---: | ---: |
| PIPE-Diversity index | 0.557 | 0.575 |
| Unique query-signature ratio | 0.062 | 0.135 |
| Structural substructures | 97 | 134 |
| Adjusted Distinct-2 | 0.266 | 0.284 |
| Property coverage | 0.407 | 0.426 |

The paper frames diversity honestly: category and difficulty balance are strong
by construction, while query-signature concentration remains an auditable
quantity to monitor during benchmark refresh.

## Judge Calibration

Generate a stratified audit packet from accepted and rejected records:

```bash
python scripts/sample_judge_audit.py \
  --records artifacts/runs/<finbench_run_id>/records.jsonl \
            artifacts/runs/<snb_run_id>/records.jsonl \
  --output artifacts/audits/judge_audit_packet.csv \
  --n 80 \
  --seed 20260604
```

After an external annotator fills the human-label columns, analyze agreement:

```bash
python scripts/analyze_judge_audit.py \
  --audit artifacts/audits/judge_audit_packet_filled.csv \
  --require-complete-labels
```

Paper result:

| Rows | Annotators | Agreement | Cohen kappa | Judge precision | Judge recall | False accept | False reject |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 80 | 1 external annotator | 0.800 | 0.600 | 1.000 [0.912, 1.000] | 0.714 [0.585, 0.816] | 0.000 [0.000, 0.138] | 0.286 [0.184, 0.415] |

The judge is a conservative generation gate: in the completed audit sample it
had no observed false accepts, at the cost of rejecting some examples a human
would accept.

## Safety, Rewrite, Redaction, and Runtime Audits

Run governance failure summaries across generation records, ablation summaries,
and downstream error reports:

```bash
python scripts/audit_governance_failures.py \
  --records artifacts/runs/<finbench_run_id>/records.jsonl \
            artifacts/runs/<snb_run_id>/records.jsonl \
  --ablation-summary artifacts/reports/ablation_target100_summary.json \
  --downstream-error-report artifacts/reports/downstream_error_report.json \
  --output-json artifacts/reports/governance_audit.json \
  --output-tex artifacts/reports/governance_audit.tex
```

Run rewrite impact checks:

```bash
python scripts/audit_rewrite_impact.py \
  --records artifacts/runs/<finbench_run_id>/records.jsonl \
            artifacts/runs/<snb_run_id>/records.jsonl \
  --config-by-graph finbench=configs/finbench_full.yaml \
  --config-by-graph snb=configs/snb_full.yaml \
  --max-executions 5000 \
  --output-json artifacts/reports/rewrite_audit.json \
  --output-tex artifacts/reports/rewrite_audit.tex
```

Run redaction residual checks on the exported benchmark:

```bash
python scripts/audit_redaction_policy.py \
  --benchmark artifacts/benchmarks/pipe_cypher_full_qwen35_9b/all.jsonl \
  --output-json artifacts/reports/redaction_audit.json \
  --output-tex artifacts/reports/redaction_audit.tex
```

Summarize execution/runtime accounting:

```bash
python scripts/summarize_runtime_accounting.py \
  --records artifacts/runs/<finbench_run_id>/records.jsonl \
            artifacts/runs/<snb_run_id>/records.jsonl \
  --output-json artifacts/reports/runtime_accounting.json \
  --output-tex artifacts/reports/runtime_accounting.tex
```

After downstream evaluation is complete, render strategy-conditioned diagnostics:

```bash
python scripts/analyze_strategy_diagnostics.py \
  --benchmark artifacts/benchmarks/pipe_cypher_full_qwen35_9b/all.jsonl \
  --evaluation artifacts/evaluations/qwen35_9b_zero_fewshot/zero_shot_evaluation.jsonl \
  --output-json artifacts/reports/strategy_diagnostics.json \
  --output-tex artifacts/reports/strategy_diagnostics.tex \
  --coverage-figure artifacts/reports/strategy_coverage.pdf \
  --downstream-figure artifacts/reports/strategy_downstream.pdf
```

Paper audit results:

| Audit | Result |
| --- | --- |
| Governance failures | 285 direction, 999 schema/value, 17 syntax/parser, 0 read-only failures across generation, ablation, and downstream artifacts |
| Rewrite impact | 4,925 generation records inspected; 0 accepted examples changed by normalization; 196 rewrites skipped conservatively |
| Redaction | 3,000 examples audited; 10,956 sensitive values; 0 residual raw sensitive values; residual rate 0.000 |
| Runtime | 4,925 records, 3,000 accepted; execution p50 11.995 ms and p95 32.832 ms |

## Downstream Text2Cypher Transfer

Use the exported benchmark test split and graph configs for execution-based
evaluation. The paper held-out split had 296 examples.

Zero-shot prediction/evaluation template. Use a stable `MODEL_SLUG` for each
checkpoint so summaries can be joined later:

```bash
MODEL_NAME=Qwen/Qwen3.5-9B
MODEL_SLUG=qwen35_9b
ZERO_RUN_DIR=artifacts/evaluations/${MODEL_SLUG}_zero_fewshot
mkdir -p "$ZERO_RUN_DIR"

python scripts/generate_text2cypher_predictions.py \
  --benchmark artifacts/benchmarks/pipe_cypher_full_qwen35_9b \
  --split test \
  --schema finbench=configs/schema_finbench.json \
  --schema snb=configs/schema_snb.json \
  --output "$ZERO_RUN_DIR/zero_shot_predictions.jsonl" \
  --base-url http://localhost:8000/v1 \
  --model "$MODEL_NAME" \
  --temperature 0.0 \
  --max-tokens 512 \
  --schema-max-items 70

python scripts/evaluate_benchmark_predictions.py \
  --benchmark artifacts/benchmarks/pipe_cypher_full_qwen35_9b \
  --split test \
  --predictions "$ZERO_RUN_DIR/zero_shot_predictions.jsonl" \
  --config finbench=configs/finbench_full.yaml \
  --config snb=configs/snb_full.yaml \
  --output "$ZERO_RUN_DIR/zero_shot_evaluation.jsonl" \
  --summary-output "$ZERO_RUN_DIR/zero_shot_summary.json"
```

Few-shot ordered same-category control:

```bash
CONTROL_DIR=artifacts/evaluations/control_${MODEL_SLUG}_ordered_logged
mkdir -p "$CONTROL_DIR"

python scripts/generate_text2cypher_predictions.py \
  --benchmark artifacts/benchmarks/pipe_cypher_full_qwen35_9b \
  --split test \
  --schema finbench=configs/schema_finbench.json \
  --schema snb=configs/schema_snb.json \
  --output "$CONTROL_DIR/few_shot_predictions.jsonl" \
  --base-url http://localhost:8000/v1 \
  --model "$MODEL_NAME" \
  --temperature 0.0 \
  --max-tokens 512 \
  --schema-max-items 70 \
  --few-shot artifacts/benchmarks/pipe_cypher_full_qwen35_9b/train.jsonl \
  --few-shot-k 5 \
  --few-shot-mode ordered_same_category \
  --few-shot-log "$CONTROL_DIR/selection_log.jsonl"

python scripts/evaluate_benchmark_predictions.py \
  --benchmark artifacts/benchmarks/pipe_cypher_full_qwen35_9b \
  --split test \
  --predictions "$CONTROL_DIR/few_shot_predictions.jsonl" \
  --config finbench=configs/finbench_full.yaml \
  --config snb=configs/snb_full.yaml \
  --output "$CONTROL_DIR/few_shot_evaluation.jsonl" \
  --summary-output "$CONTROL_DIR/few_shot_summary.json"
```

Few-shot no-signature control:

```bash
CONTROL_DIR=artifacts/evaluations/control_${MODEL_SLUG}_scored_no_signature
mkdir -p "$CONTROL_DIR"

python scripts/generate_text2cypher_predictions.py \
  --benchmark artifacts/benchmarks/pipe_cypher_full_qwen35_9b \
  --split test \
  --schema finbench=configs/schema_finbench.json \
  --schema snb=configs/schema_snb.json \
  --output "$CONTROL_DIR/few_shot_predictions.jsonl" \
  --base-url http://localhost:8000/v1 \
  --model "$MODEL_NAME" \
  --temperature 0.0 \
  --max-tokens 512 \
  --schema-max-items 70 \
  --few-shot artifacts/benchmarks/pipe_cypher_full_qwen35_9b/train.jsonl \
  --few-shot-k 5 \
  --few-shot-mode scored_no_signature \
  --few-shot-exclude-signature-match \
  --few-shot-max-question-sim 0.90 \
  --few-shot-log "$CONTROL_DIR/selection_log.jsonl"

python scripts/evaluate_benchmark_predictions.py \
  --benchmark artifacts/benchmarks/pipe_cypher_full_qwen35_9b \
  --split test \
  --predictions "$CONTROL_DIR/few_shot_predictions.jsonl" \
  --config finbench=configs/finbench_full.yaml \
  --config snb=configs/snb_full.yaml \
  --output "$CONTROL_DIR/few_shot_evaluation.jsonl" \
  --summary-output "$CONTROL_DIR/few_shot_summary.json"
```

Few-shot random controls use the same template with
`--few-shot-mode random_same_category` and seeds `13`, `17`, and `23`.
Each output directory must be named
`artifacts/evaluations/control_${MODEL_SLUG}_random_seed13`,
`..._random_seed17`, and `..._random_seed23` so the summarizer recognizes the
three-seed control.

Audit overlap and compare modes:

```bash
NO_SIG_DIR=artifacts/evaluations/control_${MODEL_SLUG}_scored_no_signature

python scripts/audit_downstream_fewshot_leakage.py \
  --benchmark-dir artifacts/benchmarks/pipe_cypher_full_qwen35_9b \
  --split test \
  --predictions "$NO_SIG_DIR/few_shot_predictions.jsonl" \
  --selection-log "$NO_SIG_DIR/selection_log.jsonl" \
  --few-shot-max-question-sim 0.90 \
  --few-shot-exclude-signature-match \
  --output-json "$NO_SIG_DIR/leakage_no_signature.json" \
  --output-md "$NO_SIG_DIR/leakage_no_signature.md"

python scripts/summarize_downstream_fewshot_controls.py \
  --zero-run-dir "$ZERO_RUN_DIR" \
  --control-run-dir artifacts/evaluations/control_${MODEL_SLUG}_ordered_logged \
  --control-run-dir artifacts/evaluations/control_${MODEL_SLUG}_scored_no_signature \
  --control-run-dir artifacts/evaluations/control_${MODEL_SLUG}_random_seed13 \
  --control-run-dir artifacts/evaluations/control_${MODEL_SLUG}_random_seed17 \
  --control-run-dir artifacts/evaluations/control_${MODEL_SLUG}_random_seed23 \
  --output-json artifacts/reports/fewshot_controls_${MODEL_SLUG}.json \
  --output-md artifacts/reports/fewshot_controls_${MODEL_SLUG}.md \
  --output-tex artifacts/reports/fewshot_controls_${MODEL_SLUG}.tex
```

The paper evaluated these 11 locally served checkpoints:

| Displayed model | Served checkpoint or adapter |
| --- | --- |
| aigentx/Llama-3.1-8B Cypher LoRA | `aigentx/llama-3.1-8b-instruct-cypher` |
| aigentx/Llama-3.1-8B Cypher mixed LoRA | `aigentx/llama-3.1-8b-instruct-cypher-mixed-samples` |
| Azzedde/llama3.1-8b-text2cypher | `Azzedde/llama3.1-8b-text2cypher` |
| Gemma-2-9B-IT | `google/gemma-2-9b-it` |
| neo4j/Gemma-2-9B Text2Cypher LoRA | `neo4j/text2cypher-gemma-2-9b-it-finetuned-2024v1` |
| neo4j/Gemma-3-4B Text2Cypher | `neo4j/text-to-cypher-Gemma-3-4B-Instruct-2025.04.0` |
| projectwilsen/Llama-3.1-8B Text2Cypher LoRA | `projectwilsen/llama3.1-8b-text2cypher-neo4j-live` |
| Qwen2.5-Coder-7B-Instruct | `Qwen/Qwen2.5-Coder-7B-Instruct` |
| Qwen3.5-9B | `Qwen/Qwen3.5-9B` |
| Saiprasanth15/Llama-3.1-8B Text2Cypher LoRA | `Saiprasanth15/llama3.1-8b-text2cypher-neo4j-live` |
| tomasonjo/text2cypher-demo-16bit | `tomasonjo/text2cypher-demo-16bit` |

Expected downstream aggregate:

| Mode | Mean execution accuracy | Best execution accuracy | Signature overlap |
| --- | ---: | ---: | ---: |
| Zero-shot | 0.036 | 0.203 | 0.000 |
| Scored no-signature few-shot | 0.200 | 0.828 | 0.000 |
| Ordered same-category example bank | 0.269 | 0.993 | 0.866 |
| Random same-category example bank | 0.267 | 0.986 | 0.854 |

The no-signature result is the strict generalization condition. Ordered and
random same-category runs measure an operational example-bank setting: an
enterprise can use generated, schema-aligned question-query pairs as retrieval
examples for agent/tool-call prompts, while recognizing that high signature
overlap is an upper-bound condition rather than a claim of broad structural
generalization.

For the local Qwen3.5-9B baseline, the zero-shot run produced:

| Metric | Value | 95% bootstrap CI |
| --- | ---: | --- |
| Parse valid | 0.963 | [0.939, 0.983] |
| Schema valid | 0.916 | [0.885, 0.946] |
| Execution success | 0.611 | [0.554, 0.666] |
| Execution accuracy | 0.189 | [0.145, 0.233] |
| Answer F1 | 0.189 | [0.145, 0.233] |

Low zero-shot execution accuracy is expected to be interpreted as benchmark
difficulty and transfer stress, not poor pipeline quality. PIPE-Cypher's job is
to produce executable, balanced, private benchmark artifacts that expose these
failures.

## Reproducibility Checklist

Before treating a run as paper-quality, verify:

1. The graph backend is live and matches the intended schema fingerprint.
2. `scripts/validate_config.py` passes with no unknown keys.
3. The model endpoint is local, the model ID is recorded, and reasoning traces
   are disabled or stripped.
4. Run directories contain `records.jsonl`, config snapshots, logs, and run
   metadata.
5. Full exports have train/dev/test splits, benchmark cards, checksums, and
   redacted review artifacts where needed.
6. Ablations are complete at target 50 or larger, and target-100 cells are
   preferred for final claims.
7. Downstream runs use the same benchmark split hash across all models and
   modes.
8. Few-shot runs log selected example IDs and pass leakage audits.
9. Judge calibration reports confidence intervals and clearly distinguishes
   human audit from generation gates.
10. Paper-facing tables and figures are rendered only from complete audited
    summaries, not partial or smoke runs.
