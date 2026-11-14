#!/usr/bin/env bash
set -euo pipefail

python scripts/run_pipeline.py --config configs/generated/finbench/unconstrained_local_llm.yaml --run-name unconstrained_local_llm
python scripts/run_pipeline.py --config configs/generated/finbench/reverse_only.yaml --run-name reverse_only
python scripts/run_pipeline.py --config configs/generated/finbench/validators_repair.yaml --run-name validators_repair
python scripts/run_pipeline.py --config configs/generated/finbench/full_pipe_cypher.yaml --run-name full_pipe_cypher
python scripts/run_pipeline.py --config configs/generated/finbench/ablation_retrieval_topk_0.yaml --run-name ablation_retrieval_topk_0
python scripts/run_pipeline.py --config configs/generated/finbench/ablation_retrieval_topk_2.yaml --run-name ablation_retrieval_topk_2
python scripts/run_pipeline.py --config configs/generated/finbench/ablation_retrieval_topk_4.yaml --run-name ablation_retrieval_topk_4
python scripts/run_pipeline.py --config configs/generated/finbench/ablation_judge_false.yaml --run-name ablation_judge_false
python scripts/run_pipeline.py --config configs/generated/finbench/ablation_judge_true.yaml --run-name ablation_judge_true
python scripts/run_pipeline.py --config configs/generated/finbench/ablation_rewrite_false.yaml --run-name ablation_rewrite_false
python scripts/run_pipeline.py --config configs/generated/finbench/ablation_rewrite_true.yaml --run-name ablation_rewrite_true
python scripts/run_pipeline.py --config configs/generated/finbench/ablation_model_Qwen_Qwen3.5-9B.yaml --run-name ablation_model_Qwen_Qwen3.5-9B
python scripts/run_pipeline.py --config configs/generated/finbench/ablation_graph_mix_finbench_only.yaml --run-name ablation_graph_mix_finbench_only
python scripts/run_pipeline.py --config configs/generated/finbench/ablation_graph_mix_finbench_plus_snb.yaml --run-name ablation_graph_mix_finbench_plus_snb
