# Downstream Few-Shot Control Summary

Complete models: 11 / 11

| Model | Tuning | Zero | Ordered | Scored no-sig | Random mean | Random std | Best control |
|---|---|---:|---:|---:|---:|---:|---|
| aigentx/Llama-3.1-8B Cypher LoRA | Cypher LoRA | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | no gain |
| aigentx/Llama-3.1-8B Cypher mixed LoRA | Cypher mixed LoRA | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | no gain |
| Azzedde/llama3.1-8b-text2cypher | Text2Cypher fine-tuned | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | no gain |
| Gemma-2-9B-IT | general instruction | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | no gain |
| neo4j/Gemma-2-9B Text2Cypher LoRA | Text2Cypher LoRA | 0.203 | 0.983 | 0.699 | 0.981 | 0.009 | ordered (0.983) |
| neo4j/Gemma-3-4B Text2Cypher | Text2Cypher fine-tuned | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | no gain |
| projectwilsen/Llama-3.1-8B Text2Cypher LoRA | Text2Cypher LoRA | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | no gain |
| Qwen2.5-Coder-7B-Instruct | code instruction | 0.007 | 0.983 | 0.669 | 0.972 | 0.002 | ordered (0.983) |
| Qwen3.5-9B | general instruction | 0.189 | 0.993 | 0.828 | 0.986 | 0.007 | ordered (0.993) |
| Saiprasanth15/Llama-3.1-8B Text2Cypher LoRA | Text2Cypher LoRA | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | no gain |
| tomasonjo/text2cypher-demo-16bit | Text2Cypher fine-tuned | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | no gain |

## Aggregate

| Metric | Value |
|---|---:|
| Mean zero-shot exec. acc. | 0.036 |
| Mean ordered exec. acc. | 0.269 |
| Mean scored no-signature exec. acc. | 0.200 |
| Mean random exec. acc. | 0.267 |
| Models improved by ordered | 3 / 11 |
| Models improved by scored no-signature | 3 / 11 |
