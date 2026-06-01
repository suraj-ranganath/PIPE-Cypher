# Smoke Run Evidence

Date: June 1, 2026.

Commands run:

```bash
pytest -q
python scripts/inspect_schema.py --config configs/local_smoke.yaml --reference-only --output artifacts/smoke/schema_finbench_reference.json
python scripts/inspect_schema.py --config configs/snb_smoke.yaml --reference-only --output artifacts/smoke/schema_snb_reference.json
python scripts/generate_finbench_import_cypher.py --output artifacts/import/finbench_load.cypher
python scripts/run_pipeline.py --config configs/local_smoke.yaml --offline-smoke --run-name offline_smoke_finbench_context
python scripts/summarize_run.py artifacts/runs/20260601_041350_offline_smoke_finbench_context/records.jsonl
python scripts/run_pipeline.py --config configs/snb_smoke.yaml --offline-smoke --run-name offline_smoke_snb_reference
python scripts/summarize_run.py artifacts/runs/20260601_041920_offline_smoke_snb_reference/records.jsonl
python -m compileall -q pipecypher scripts tests
python scripts/check_gpu_host.py
scripts/sync_to_ds_serv6.sh
MODEL=Qwen/Qwen3.5-9B CUDA_VISIBLE_DEVICES=2 MAX_MODEL_LEN=2048 GPU_MEMORY_UTILIZATION=0.90 CONDA_ENV=pipe-rdf-arr EXTRA_VLLM_ARGS='--no-enable-flashinfer-autotune --enforce-eager --max-num-seqs 1 --max-num-batched-tokens 2048' scripts/launch_ds_serv6_vllm.sh
ssh suraj@ds-serv6.ucsd.edu 'cd /home/suraj/PIPE-Cypher && source ~/miniforge3/etc/profile.d/conda.sh && conda activate pipe-rdf-arr && python scripts/check_llm_endpoint.py --base-url http://localhost:8000/v1 --model Qwen/Qwen3.5-9B'
ssh suraj@ds-serv6.ucsd.edu 'cd /home/suraj/PIPE-Cypher && SCALE_FACTOR=0.1 RUN_ROOT=/home/suraj/pipecypher-runs/finbench_sf0.1 DATA_ROOT=/home/suraj/pipecypher-runs/finbench_sf0.1/data scripts/run_finbench_datagen.sh'
ssh suraj@ds-serv6.ucsd.edu 'cd /home/suraj/PIPE-Cypher && scripts/start_neo4j_community.sh'
ssh suraj@ds-serv6.ucsd.edu 'cd /home/suraj/PIPE-Cypher && SNAPSHOT_DIR=/home/suraj/pipecypher-runs/finbench_sf0.1/data/snapshot RUN_ROOT=/home/suraj/pipecypher-neo4j scripts/load_finbench_neo4j.sh'
ssh suraj@ds-serv6.ucsd.edu 'cd /home/suraj/PIPE-Cypher && PIPE_CYPHER_NEO4J_DATABASE=neo4j /home/suraj/pipecypher-tools/runtime-venv/bin/python scripts/inspect_schema.py --config configs/finbench_live_smoke.yaml --output configs/schema_finbench.json'
ssh suraj@ds-serv6.ucsd.edu 'cd /home/suraj/PIPE-Cypher && /home/suraj/pipecypher-tools/runtime-venv/bin/python scripts/run_pipeline.py --config configs/finbench_live_smoke.yaml --run-name live_finbench_qwen9b_defaultslots'
ssh suraj@ds-serv6.ucsd.edu 'cd /home/suraj/PIPE-Cypher && /home/suraj/pipecypher-tools/runtime-venv/bin/python scripts/summarize_run.py artifacts/runs/20260601_122841_live_finbench_qwen9b_defaultslots/records.jsonl'
ssh suraj@ds-serv6.ucsd.edu 'cd /home/suraj/PIPE-Cypher && /home/suraj/pipecypher-tools/runtime-venv/bin/python scripts/run_pipeline.py --config configs/finbench_live_categories_smoke.yaml --run-name live_finbench_qwen9b_8cat_seeded'
ssh suraj@ds-serv6.ucsd.edu 'cd /home/suraj/PIPE-Cypher && /home/suraj/pipecypher-tools/runtime-venv/bin/python scripts/summarize_run.py artifacts/runs/20260601_124531_live_finbench_qwen9b_8cat_seeded/records.jsonl'
ssh suraj@ds-serv6.ucsd.edu 'cd /home/suraj/PIPE-Cypher && RUN_ROOT=/home/suraj/pipecypher-neo4j-snb SESSION=pipecypher_neo4j_snb BOLT_PORT=7688 HTTP_PORT=7475 AUTH_ENABLED=false scripts/start_neo4j_community.sh'
ssh suraj@ds-serv6.ucsd.edu 'cd /home/suraj/PIPE-Cypher && RUN_ROOT=/home/suraj/pipecypher-neo4j-snb BOLT_URI=bolt://localhost:7688 scripts/load_snb_neo4j.sh'
ssh suraj@ds-serv6.ucsd.edu 'cd /home/suraj/PIPE-Cypher && /home/suraj/pipecypher-tools/runtime-venv/bin/python scripts/inspect_schema.py --config configs/snb_live_smoke.yaml --output configs/schema_snb.json'
ssh suraj@ds-serv6.ucsd.edu 'cd /home/suraj/PIPE-Cypher && /home/suraj/pipecypher-tools/runtime-venv/bin/python scripts/run_pipeline.py --config configs/snb_live_smoke.yaml --run-name live_snb_qwen9b_ids_template'
ssh suraj@ds-serv6.ucsd.edu 'cd /home/suraj/PIPE-Cypher && /home/suraj/pipecypher-tools/runtime-venv/bin/python scripts/summarize_run.py artifacts/runs/20260601_124201_live_snb_qwen9b_ids_template/records.jsonl'
python scripts/sample_judge_audit.py --records artifacts/runs/20260601_124037_live_snb_qwen9b_judgeslice/records.jsonl --output artifacts/audits/20260601_live_snb_qwen9b_judgeslice_audit.csv --n 7
ssh suraj@ds-serv6.ucsd.edu 'cd /home/suraj/PIPE-Cypher && /home/suraj/pipecypher-tools/runtime-venv/bin/python scripts/run_pipeline.py --config configs/finbench_live_llm_only_probe.yaml --run-name live_finbench_llm_only_probe'
ssh suraj@ds-serv6.ucsd.edu 'cd /home/suraj/PIPE-Cypher && /home/suraj/pipecypher-tools/runtime-venv/bin/python scripts/run_pipeline.py --config configs/finbench_live_mixed_mini.yaml --run-name live_finbench_mixed_mini'
ssh suraj@ds-serv6.ucsd.edu 'cd /home/suraj/PIPE-Cypher && /home/suraj/pipecypher-tools/runtime-venv/bin/python scripts/run_pipeline.py --config configs/snb_live_mixed_mini.yaml --run-name live_snb_mixed_mini_diverse'
```

Observed results:

```text
42 passed in 0.14s

FinBench offline smoke:
PIPE-Cypher run complete: 4/4 accepted
records=4
accepted=4
accept_rate=1.000
by_category={"complex_retrieval": 1, "ranking_topk": 1, "simple_aggregation": 1, "simple_retrieval": 1}
accepted_by_category={"complex_retrieval": 1, "ranking_topk": 1, "simple_aggregation": 1, "simple_retrieval": 1}
difficulty={"easy": 3, "medium": 1}
primary_strategy={"aggregation": 1, "join_heavy": 1, "order_rank": 1, "single_hop": 1}
gates={"execution_success": 4, "judge_pass": 4, "read_only": 4, "schema_valid": 4, "syntax_valid": 4}
issues={}

SNB offline smoke:
PIPE-Cypher run complete: 4/4 accepted
records=4
accepted=4
accept_rate=1.000
by_category={"complex_retrieval": 1, "ranking_topk": 1, "simple_aggregation": 1, "simple_retrieval": 1}
accepted_by_category={"complex_retrieval": 1, "ranking_topk": 1, "simple_aggregation": 1, "simple_retrieval": 1}
difficulty={"easy": 3, "medium": 1}
primary_strategy={"aggregation": 1, "join_heavy": 1, "order_rank": 1, "single_hop": 1}
gates={"execution_success": 4, "judge_pass": 4, "read_only": 4, "schema_valid": 4, "syntax_valid": 4}
issues={}

Live FinBench SF0.1 + Neo4j + Qwen3.5-9B smoke:
PIPE-Cypher run complete: 4/4 accepted
records=4
accepted=4
accept_rate=1.000
by_category={"complex_retrieval": 1, "ranking_topk": 1, "simple_aggregation": 1, "simple_retrieval": 1}
accepted_by_category={"complex_retrieval": 1, "ranking_topk": 1, "simple_aggregation": 1, "simple_retrieval": 1}
difficulty={"easy": 3, "medium": 1}
primary_strategy={"aggregation": 1, "join_heavy": 1, "order_rank": 1, "single_hop": 1}
gates={"execution_success": 4, "judge_pass": 4, "read_only": 4, "schema_valid": 4, "syntax_valid": 4}
issues={}

Live FinBench SF0.1 all-category seeded smoke:
PIPE-Cypher run complete: 8/8 accepted
records=8
accepted=8
accept_rate=1.000
by_category={"boolean_existence": 1, "complex_aggregation": 1, "complex_retrieval": 1, "negation_difference": 1, "path_temporal": 1, "ranking_topk": 1, "simple_aggregation": 1, "simple_retrieval": 1}
accepted_by_category={"boolean_existence": 1, "complex_aggregation": 1, "complex_retrieval": 1, "negation_difference": 1, "path_temporal": 1, "ranking_topk": 1, "simple_aggregation": 1, "simple_retrieval": 1}
difficulty={"easy": 4, "medium": 4}
primary_strategy={"aggregation": 3, "join_heavy": 1, "negation": 1, "order_rank": 1, "path": 1, "single_hop": 1}
gates={"execution_success": 8, "judge_pass": 8, "read_only": 8, "schema_valid": 8, "syntax_valid": 8}
issues={}

Live SNB test-data + Neo4j + Qwen3.5-9B smoke:
PIPE-Cypher run complete: 4/4 accepted
records=4
accepted=4
accept_rate=1.000
by_category={"complex_retrieval": 1, "ranking_topk": 1, "simple_aggregation": 1, "simple_retrieval": 1}
accepted_by_category={"complex_retrieval": 1, "ranking_topk": 1, "simple_aggregation": 1, "simple_retrieval": 1}
difficulty={"easy": 3, "medium": 1}
primary_strategy={"aggregation": 1, "join_heavy": 1, "order_rank": 1, "single_hop": 1}
gates={"execution_success": 4, "judge_pass": 4, "read_only": 4, "schema_valid": 4, "syntax_valid": 4}
issues={}

Live mini-ablation:
FinBench LLM-only probe:
records=16
accepted=0
accept_rate=0.000
gates={"execution_success": 16, "read_only": 16, "schema_valid": 16, "syntax_valid": 16}

FinBench mixed mini:
records=37
accepted=15
accept_rate=0.405
accepted_by_category={"boolean_existence": 2, "complex_aggregation": 2, "complex_retrieval": 2, "negation_difference": 2, "path_temporal": 1, "ranking_topk": 2, "simple_aggregation": 2, "simple_retrieval": 2}
gates={"execution_success": 37, "judge_pass": 15, "read_only": 37, "schema_valid": 37, "syntax_valid": 37}

FinBench mixed mini after scalar-binding and seed-coverage fixes:
records=29
accepted=16
accept_rate=0.552
accepted_by_category={"boolean_existence": 2, "complex_aggregation": 2, "complex_retrieval": 2, "negation_difference": 2, "path_temporal": 2, "ranking_topk": 2, "simple_aggregation": 2, "simple_retrieval": 2}
gates={"execution_success": 29, "judge_pass": 16, "read_only": 29, "schema_valid": 29, "syntax_valid": 29}

SNB mixed mini:
records=8
accepted=8
accept_rate=1.000
accepted_by_category={"complex_retrieval": 2, "ranking_topk": 2, "simple_aggregation": 2, "simple_retrieval": 2}
gates={"execution_success": 8, "judge_pass": 8, "read_only": 8, "schema_valid": 8, "syntax_valid": 8}
```

Additional verification:

- `scripts/generate_finbench_import_cypher.py` wrote `artifacts/import/finbench_load.cypher`.
- The generated import uses `MERGE` for unique nodes and `CREATE` for relationships so repeated transaction events between the same accounts are preserved.
- `scripts/check_llm_endpoint.py` passed on `ds-serv6` against the live vLLM endpoint and returned `chat_text="ok"` for `Qwen/Qwen3.5-9B`.
- The working 9B vLLM smoke used one A5000 with `MAX_MODEL_LEN=2048`, `--enforce-eager`, `--max-num-seqs 1`, and FlashInfer sampler/autotune disabled.
- LDBC FinBench SF0.1 generated and loaded into the user-space Neo4j Community smoke database with 10,006 nodes and 57,622 relationships.
- Live schema introspection saved `configs/schema_finbench.json` from Neo4j.
- The live run `artifacts/runs/20260601_122841_live_finbench_qwen9b_defaultslots` contains four accepted, non-empty, LLM-judged FinBench examples. The examples use graph-backed slot values, for example `Bertrand`, rather than placeholder literals.
- The live run `artifacts/runs/20260601_124531_live_finbench_qwen9b_8cat_seeded` contains eight accepted FinBench examples covering all planned categories with an easy/medium split of 4/4.
- The official SNB Cypher test-data loaded into a separate user-space Neo4j Community instance on Bolt port 7688 with 34,735 nodes and 70,842 relationships.
- Live SNB schema introspection saved `configs/schema_snb.json` from Neo4j.
- The live run `artifacts/runs/20260601_124201_live_snb_qwen9b_ids_template` contains four accepted, non-empty, LLM-judged SNB examples using graph-backed person and tag values.
- The SNB judge path initially hit the Qwen smoke endpoint's 2k-token context limit when prompted with the full live schema. `LLMJudge` now sends a Cypher-specific schema slice, which restored local-Qwen judge JSON outputs.
- `artifacts/audits/20260601_live_snb_qwen9b_judgeslice_audit.csv` contains four unique accepted/rejected examples sampled for post-hoc human judge calibration. Human labels are intentionally blank until the audit is performed.
- Live mini-ablation artifacts:
  - `artifacts/runs/20260601_133302_live_finbench_llm_only_probe_generic_scan_tag`: 0/16 accepted, with 16/16 `generic_node_scan` validation warnings.
  - `artifacts/runs/20260601_132232_live_finbench_mixed_mini_full_coverage`: 16/29 accepted.
  - `artifacts/runs/20260601_130456_live_snb_mixed_mini_diverse`: 8/8 accepted.
  - `artifacts/runs/20260601_135706_live_snb_qwen9b_8cat_seeded_fixed`: 8/8 accepted across all planned SNB categories.
  - `artifacts/runs/20260601_140632_20260601_midscale_finbench`: 40/46 accepted, five accepted examples in every planned category.
  - `artifacts/runs/20260601_140855_20260601_midscale_snb`: 40/47 accepted, five accepted examples in every planned category.
- `artifacts/benchmarks/20260601_live_all_category_mini` exports 24 accepted records as benchmark JSONL files with stable IDs, train/dev/test splits of 15/1/8, stats, exactly three accepted examples in every planned category across FinBench+SNB, and manifest hash `32ee49f53a22930dacafdcfcfe159d447ab65a1fac398c56cf2f5af7996d5b46`.
- `artifacts/benchmarks/20260601_live_midscale` exports 80 accepted records as benchmark JSONL files with stable IDs, train/dev/test splits of 48/16/16, stats, exactly ten accepted examples in every planned category across FinBench+SNB, and manifest hash `543d99ad3cffde902bedc107811c4b3105285f4921804353f479028742909408`.
- Downstream evaluation smoke artifacts:
  - `artifacts/predictions/20260601_qwen9b_midscale_test_predictions.jsonl`: 16 local Qwen3.5-9B mid-scale test-split predictions.
  - `artifacts/evaluations/20260601_qwen9b_midscale_test_summary.json`: 0.250 execution accuracy, 0.250 answer F1, and 0.688 execution success.
- The FinBench LLM-only probe exposed a dominant local-Qwen failure mode: ambitious generated templates often repaired/fell back to generic `MATCH (n) RETURN DISTINCT n LIMIT 1`, which the LLM judge rejected.
- `python -m ruff check .` could not run in the current environment because `ruff` is not installed.

This evidence proves CLI wiring, schema prompts, deterministic validation, mock execution, deterministic judge, JSONL logging, import-script generation, FinBench and SNB reference profiles, summary metrics, live local Qwen/vLLM serving, FinBench and SNB live Neo4j loading, live schema introspection, execution validation, and LLM-judge review on small live smokes. It does not yet prove full LLM generation quality, judge calibration, or full-scale benchmark generation.
