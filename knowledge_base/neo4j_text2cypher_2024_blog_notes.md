# Neo4j Text2Cypher 2024 Fine-Tuning Blog Notes

Source: https://neo4j.com/blog/developer/fine-tuned-text2cypher-2024-model/
Captured locally on 2026-06-02 for visual analysis only. Full-page and extracted chart images are stored under `artifacts/internal_visual_refs/neo4j_text2cypher_2024*` and should not be committed as paper figures.

## Visual/Content Takeaways

- The post presents Text2Cypher fine-tuning as a same-distribution improvement story: train on the Neo4j Text2Cypher 2024 training split and evaluate on the corresponding test split.
- Their visual result chart separates translation-style Google BLEU from execution-style ExactMatch. This is useful for PIPE-Cypher because it reinforces our decision to report execution accuracy/answer F1 as primary and text metrics as secondary diagnostics.
- The fine-tuning delta table shows improvements for several fine-tuned models, but the execution gains are modest for some baselines. That supports evaluating transfer on our own held-out enterprise-style graphs instead of assuming public Text2Cypher fine-tuning transfers.
- Their prompt table is much simpler than PIPE-Cypher's governance prompt contract: schema-only, no explanations, no extra relationship types/properties. PIPE-Cypher should frame its added value as turning these prompt instructions into deterministic gates, direction/property checks, value policy, and execution validation.
- The risks table is the most useful paper motivation. It explicitly flags paraphrased-test contamination, template/logic over-concentration, inference-time compute effects, and public-test leakage. PIPE-Cypher addresses these through private graph-specific benchmark generation, diversity diagnostics, local model operation, refreshable held-out splits, and audit metadata.

## How To Use In PIPE-Cypher

- Cite this line of work as evidence that public fine-tuned Text2Cypher models exist and can improve same-distribution scores.
- Use our multi-model downstream transfer experiment to test whether those gains transfer to FinBench/SNB enterprise-style workloads.
- In the paper narrative, avoid saying fine-tuned models are bad. The stronger claim is: public Text2Cypher fine-tuning is useful, but enterprise teams still need private, executable, distribution-specific benchmarks to measure transfer, support tenant-specific fine-tuning, and refresh evaluation as schemas and graph contents change.
- In appendix analysis, compare zero-shot vs retrieval few-shot and general/code/fine-tuned model families on the same held-out split. If the fine-tuned model improves syntax but not execution, frame this as public training improving Cypher form without fully solving graph-specific grounding.

## Runnable Model Split

- Blog-reported best models on same-distribution evaluation: `Finetuned'24-OpenAI/GPT-4o`, `Finetuned'24-OpenAI/GPT-4o-mini`, and `Finetuned'24-GoogleAIStudio/Gemini-1.5-Flash-001`. These are closed/vendor fine-tunes and should not be used for PIPE-Cypher reported experiments under the local/no-paid-API constraint.
- Public local candidates already used or attempted in PIPE-Cypher transfer experiments: `tomasonjo/text2cypher-demo-16bit`, `neo4j/text-to-cypher-Gemma-3-4B-Instruct-2025.04.0`, `ragraph-ai/stable-cypher-instruct-3b`, and, if the PEFT/base-model setup is available, `neo4j/text2cypher-gemma-2-9b-it-finetuned-2024v1`.
- The Neo4j 2024 Gemma2 model is a PEFT adapter; it is not a plain vLLM full checkpoint in the current server environment. Treat it as blocked unless `google/gemma-2-9b-it` access and a PEFT/LoRA serving path are verified.

## Current-Family Policy

The blog chart is a 2024 snapshot and should be treated as historical context. New PIPE-Cypher model-family benchmarks should use the latest local-weight checkpoint that is runnable under project constraints, not the exact chart entry, unless a historical baseline has already been launched. Candidate families to prefer for future local-only sweeps include Gemma 3 IT over Gemma 2, Qwen3-Coder over older code baselines, and current Llama instruct checkpoints when license access and 24 GB GPU memory permit.

## Fine-Tuned HF Model Inventory

Fine-tuned Text2Cypher/Cypher checkpoints located on Hugging Face:

- `tomasonjo/text2cypher-demo-16bit`: full Llama-family checkpoint, already evaluated locally.
- `neo4j/text-to-cypher-Gemma-3-4B-Instruct-2025.04.0`: full Gemma3 Text2Cypher checkpoint, already evaluated locally.
- `neo4j/text2cypher-gemma-2-9b-it-finetuned-2024v1`: PEFT LoRA adapter over `google/gemma-2-9b-it`; serve with vLLM `--enable-lora --max-lora-rank 64` and merged system messages.
- `projectwilsen/llama3.1-8b-text2cypher-neo4j-live`, `Saiprasanth15/llama3.1-8b-text2cypher-neo4j-live`, and `Bhargav6239/llama3.1-8b-text2cypher-neo4j-finetune`: LoRA adapters over `unsloth/meta-llama-3.1-8b-bnb-4bit`; the base lacks a chat template under vLLM, so use a template-aware runner before reporting.
- `aigentx/llama-3.1-8b-instruct-cypher`: LoRA adapter over `unsloth/meta-llama-3.1-8b-instruct-unsloth-bnb-4bit`; vLLM health check passes and the full held-out run was launched locally.
- `ragraph-ai/stable-cypher-instruct-3b`: fine-tuned StableLM checkpoint, but the HF config declares bitsandbytes 8-bit quantization on `StableLmForCausalLM`; vLLM rejects this quantization path, so use a direct Transformers/bitsandbytes or GGUF runner before reporting.
- `ed-neo4j/text-to-cypher-unsloth-Llama-3.3-70B-Instruct-bnb-4bit`: fine-tuned 70B 4-bit checkpoint around 39.5 GB; feasible only with careful multi-GPU planning and not a first-pass A5000 single-GPU run.

The exact public HF repo for the chart label `hf_finetuned_neo4j_text2cypher_23_codellama` was not located via HF search; do not report it as evaluated unless a concrete model ID is found.
