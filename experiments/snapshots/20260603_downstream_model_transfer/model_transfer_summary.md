# Downstream Model Transfer Summary

Complete runs: 10 / 10

| Model | Family | Tuning | Zero exec. acc. | Few-shot exec. acc. | Delta | Zero schema | Few schema |
|---|---|---:|---:|---:|---:|---:|---:|
| Qwen3.5-9B | Qwen | general instruction | 0.189 | 0.997 | 0.807 | 0.909 | 1.000 |
| Qwen2.5-Coder-7B-Instruct | Qwen-Coder | code instruction | 0.291 | 0.993 | 0.703 | 0.709 | 1.000 |
| Gemma-2-9B-IT | Gemma | general instruction | 0.152 | 0.993 | 0.841 | 0.716 | 1.000 |
| tomasonjo/text2cypher-demo-16bit | Llama 3.1 | Text2Cypher fine-tuned | 0.166 | 0.976 | 0.811 | 0.750 | 1.000 |
| neo4j/Gemma-3-4B Text2Cypher | Gemma 3 | Text2Cypher fine-tuned | 0.000 | 0.912 | 0.912 | 0.706 | 0.997 |
| Azzedde/llama3.1-8b-text2cypher | Llama 3.1 | Text2Cypher fine-tuned | 0.155 | 0.976 | 0.821 | 0.807 | 0.997 |
| neo4j/Gemma-2-9B Text2Cypher LoRA | Gemma 2 | Text2Cypher LoRA | 0.199 | 0.993 | 0.794 | 0.821 | 0.997 |
| aigentx/Llama-3.1-8B Cypher LoRA | Llama 3.1 | Cypher LoRA | 0.074 | 0.730 | 0.655 | 0.199 | 0.912 |
| aigentx/Llama-3.1-8B Cypher mixed LoRA | Llama 3.1 | Cypher mixed LoRA | 0.111 | 0.983 | 0.872 | 0.791 | 0.990 |
| ragraph-ai/stable-cypher-instruct-3b | StableLM | Cypher instruction | 0.155 | 0.838 | 0.682 | 0.780 | 0.976 |
