# Downstream Few-Shot Control Summary

Complete models: 12 / 12

| Model | Tuning | Zero | Ordered | Scored no-sig | Random mean | Random std | Best control |
|---|---|---:|---:|---:|---:|---:|---|
| aigentx/Llama-3.1-8B Cypher LoRA | Cypher LoRA | 0.074 | 0.733 | 0.321 | 0.735 | 0.011 | random mean (0.735) |
| aigentx/Llama-3.1-8B Cypher mixed LoRA | Cypher mixed LoRA | 0.111 | 0.000 | 0.000 | 0.000 | 0.000 | no gain |
| Azzedde/llama3.1-8b-text2cypher | Text2Cypher fine-tuned | 0.155 | 0.000 | 0.000 | 0.000 | 0.000 | no gain |
| Gemma-2-9B-IT | general instruction | 0.152 | 0.000 | 0.000 | 0.000 | 0.000 | no gain |
| neo4j/Gemma-2-9B Text2Cypher LoRA | Text2Cypher LoRA | 0.199 | 0.993 | 0.686 | 0.982 | 0.002 | ordered (0.993) |
| neo4j/Gemma-3-4B Text2Cypher | Text2Cypher fine-tuned | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | no gain |
| projectwilsen/Llama-3.1-8B Text2Cypher LoRA | Text2Cypher LoRA | 0.169 | 0.000 | 0.000 | 0.000 | 0.000 | no gain |
| Qwen2.5-Coder-7B-Instruct | code instruction | 0.291 | 0.993 | 0.676 | 0.980 | 0.000 | ordered (0.993) |
| Qwen3.5-9B | general instruction | 0.189 | 0.997 | 0.821 | 0.990 | 0.003 | ordered (0.997) |
| Saiprasanth15/Llama-3.1-8B Text2Cypher LoRA | Text2Cypher LoRA | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | no gain |
| ragraph-ai/stable-cypher-instruct-3b | Cypher instruction | 0.155 | 0.838 | 0.432 | 0.843 | 0.008 | random mean (0.843) |
| tomasonjo/text2cypher-demo-16bit | Text2Cypher fine-tuned | 0.166 | 0.000 | 0.000 | 0.000 | 0.000 | no gain |

## Aggregate

| Metric | Value |
|---|---:|
| Mean zero-shot exec. acc. | 0.139 |
| Mean ordered exec. acc. | 0.380 |
| Mean scored no-signature exec. acc. | 0.245 |
| Mean random exec. acc. | 0.378 |
| Models improved by ordered | 5 / 12 |
| Models improved by scored no-signature | 5 / 12 |
