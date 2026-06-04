# Downstream Model Transfer Summary

Complete runs: 10 / 12

| Model | Family | Tuning | Mode | Seed | N | Zero exec. acc. | Few exec. acc. | Delta | Few exec. success | Few schema | Few F1 |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| aigentx_llama31_cypher | unspecified | unspecified | ordered_same_category | 13 | 296 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 |
| aigentx_llama31_cypher_mixed | unspecified | unspecified | ordered_same_category | 13 | 296 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 |
| Azzedde/llama3.1-8b-text2cypher | unspecified | unspecified | ordered_same_category | 13 | 296 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 |
| google/gemma-2-9b-it | unspecified | unspecified | ordered_same_category | 13 | 296 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 |
| neo4j/text-to-cypher-Gemma-3-4B-Instruct-2025.04.0 | unspecified | unspecified | ordered_same_category | 13 | 296 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 |
| projectwilsen_llama31_text2cypher_template | unspecified | unspecified | ordered_same_category | 13 | 296 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 |
| Qwen/Qwen2.5-Coder-7B-Instruct | unspecified | unspecified | ordered_same_category | 13 | 296 | 0.007 | 0.983 | 0.976 | 1.000 | 1.000 | 0.987 |
| Qwen/Qwen3.5-9B | unspecified | unspecified | ordered_same_category | 13 | 296 | 0.189 | 0.993 | 0.804 | 1.000 | 1.000 | 0.993 |
| saiprasanth_llama31_text2cypher_template | unspecified | unspecified | ordered_same_category | 13 | 296 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 |
| tomasonjo/text2cypher-demo-16bit | unspecified | unspecified | ordered_same_category | 13 | 296 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 |

## Incomplete Runs

- neo4j-gemma2-text2cypher-lora (`20260604_clean_downstream_neo4j_gemma2_text2cypher_lora_zero_fewshot`) missing: few_shot_summary.json
- ragraph-ai/stable-cypher-instruct-3b (`20260604_clean_downstream_stable_cypher_instruct3b_transformers_zero_fewshot`) missing: zero_shot_summary.json: no evaluated rows, few_shot_summary.json: no evaluated rows
