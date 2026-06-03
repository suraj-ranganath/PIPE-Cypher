# Downstream Model Transfer Summary

Complete runs: 12 / 12

| Model | Family | Tuning | Mode | Seed | N | Zero exec. acc. | Few exec. acc. | Delta | Few exec. success | Few schema | Few F1 |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| aigentx/Llama-3.1-8B Cypher LoRA | Llama 3.1 | Cypher LoRA | ordered_same_category |  | 296 | 0.074 | 0.730 | 0.655 | 0.777 | 0.912 | 0.769 |
| Azzedde/llama3.1-8b-text2cypher | Llama 3.1 | Text2Cypher fine-tuned | ordered_same_category |  | 296 | 0.155 | 0.976 | 0.821 | 0.997 | 0.997 | 0.979 |
| Gemma-2-9B-IT | Gemma | general instruction | ordered_same_category |  | 296 | 0.152 | 0.993 | 0.841 | 1.000 | 1.000 | 0.993 |
| neo4j/Gemma-2-9B Text2Cypher LoRA | Gemma 2 | Text2Cypher LoRA | ordered_same_category |  | 296 | 0.199 | 0.993 | 0.794 | 0.997 | 0.997 | 0.996 |
| neo4j/Gemma-3-4B Text2Cypher | Gemma 3 | Text2Cypher fine-tuned | ordered_same_category |  | 296 | 0.000 | 0.912 | 0.912 | 0.912 | 0.997 | 0.912 |
| Qwen2.5-Coder-7B-Instruct | Qwen-Coder | code instruction | ordered_same_category |  | 296 | 0.291 | 0.993 | 0.703 | 1.000 | 1.000 | 0.996 |
| Qwen3.5-9B | Qwen | general instruction | ordered_same_category |  | 296 | 0.189 | 0.997 | 0.807 | 1.000 | 1.000 | 0.997 |
| ragraph-ai/stable-cypher-instruct-3b | StableLM | Cypher instruction | ordered_same_category |  | 296 | 0.155 | 0.838 | 0.682 | 0.912 | 0.976 | 0.838 |
| tomasonjo/text2cypher-demo-16bit | Llama 3.1 | Text2Cypher fine-tuned | ordered_same_category |  | 296 | 0.166 | 0.976 | 0.811 | 1.000 | 1.000 | 0.979 |
| aigentx/Llama-3.1-8B Cypher mixed LoRA | Llama 3.1 | Cypher mixed LoRA | ordered_same_category |  | 296 | 0.111 | 0.983 | 0.872 | 0.990 | 0.990 | 0.983 |
| projectwilsen/Llama-3.1-8B Text2Cypher LoRA | Llama 3.1 | Text2Cypher LoRA | ordered_same_category |  | 296 | 0.169 | 0.142 | -0.027 | 0.162 | 0.990 | 0.142 |
| Saiprasanth15/Llama-3.1-8B Text2Cypher LoRA | Llama 3.1 | Text2Cypher LoRA | ordered_same_category |  | 296 | 0.000 | 0.730 | 0.730 | 0.740 | 0.993 | 0.730 |
