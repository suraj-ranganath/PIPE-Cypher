# Downstream Prompt Formats (NAACL 2027 resubmission)

Checked on 2026-11-11 from public Hugging Face model cards (raw `README.md`), the
public HF API, public GitHub, and Neo4j's public blog/Colab. No paid APIs were used.
Code: `pipecypher/prompt_formats.py` (registry), `configs/downstream_models_naacl2027.yaml`
(model manifest), `scripts/run_downstream_suite.py` (runner).

## Why this exists

The June 2026 downstream study is void: 8 of 11 checkpoints got HTTP 404 on every
request (the requests used a model name the endpoint was not serving) and the
empty predictions were scored 0.000. Reviewers also raised two prompt issues:

| Reviewer concern | Condition that answers it |
| --- | --- |
| Text2Cypher fine-tunes were not prompted the way their cards document | `zero_native` (the `native_*` format, verbatim from the card or official companion) vs `zero_pipe_standard` |
| The generator saw governance rules (contextual return columns, direction discipline, exact literals) that downstream models never saw | `zero_pipe_governed` vs `zero_pipe_standard` (same model, same split) |
| Few-shot gains might come from near-duplicate retrieval | `fewshot_ordered`, `fewshot_scored_no_signature` (signature-matched examples excluded), `fewshot_random_seed{13,17,23}` |
| Mis-routed endpoints were scored as model failures | `/models` preflight on the exact request name (the LoRA alias for adapters), `--max-consecutive-errors` abort, and evaluator exit 3. Any of these stops that model's queue. |

`pipe_standard` is byte-identical to the historical `TEXT2CYPHER_SYSTEM` /
`TEXT2CYPHER_PROMPT`, and a frozen copy in `tests/test_prompt_formats.py` guards it.
`pipe_governed` appends conventions built at runtime from
`pipecypher.validator.CONTEXTUAL_RETURN_PROPERTIES`, `WRITE_TOKENS`, and
`RESERVED_VARIABLES`, and from the active schema (relationship-direction example,
symmetric relationship types the validator accepts undirected, categorical properties). Contextual rules are kept only when the label and trigger
property exist in the schema. Their required columns are narrowed to properties the
schema has. FinBench `Medium.riskLevel` is absent, so that column is dropped. SNB
gets no contextual rules.

Few-shot conditions always use `pipe_standard`, because no card documents a few-shot
format. If a `native_*` format receives few-shot examples, it raises an error.

## Model card findings

All native templates keep PIPE-Cypher's schema text (`SchemaSummary.to_prompt(70)`) in
the `{schema}` slot so that only the template changes. Neo4j cards build schemas with
`neo4j-graphrag`/LangChain `get_schema`, so the schema serialization is a remaining
difference. The paper should state it.

| Checkpoint (verified HF id) | Documented format | Registry name | Source |
| --- | --- | --- | --- |
| `neo4j/text2cypher-gemma-2-9b-it-finetuned-2024v1` (PEFT LoRA, r=64, base `google/gemma-2-9b-it`) | Yes, a single user turn (A) | `native_neo4j_gemma2_2024` | https://huggingface.co/neo4j/text2cypher-gemma-2-9b-it-finetuned-2024v1 |
| `neo4j/text-to-cypher-Gemma-3-4B-Instruct-2025.04.0` | **Not on the model card** (the card has YAML metadata only). Neo4j's official Colab, linked from Neo4j's announcement blog, documents a single user turn (B) | `native_neo4j_gemma3_2025` | Colab https://colab.research.google.com/drive/1HeESE-saKNN-ZfUv06axBrnSWuN0ijlc, linked from https://neo4j.com/blog/news/text2cypher-vertex-ai/ |
| `neo4j/text-to-cypher-Gemma-3-27B-Instruct-2025.04.0` | Same as 4B: not on the card, documented in the official Colab (B) | `native_neo4j_gemma3_2025` | same as above |
| `tomasonjo/text2cypher-demo-16bit` (full Llama-3-8B-Instruct) | Yes, system + user (C) | `native_tomasonjo_llama3` | https://huggingface.co/tomasonjo/text2cypher-demo-16bit (same as the training notebook https://github.com/neo4j-labs/text2cypher/blob/main/finetuning/unsloth-llama3/llama3_text2cypher_chat.ipynb) |
| `Azzedde/llama3.1-8b-text2cypher` (full Llama-3.1-8B) | Yes, a raw Alpaca-style prompt with no chat template (D) | `native_azzedde_alpaca` (sent to `/v1/completions`) | https://huggingface.co/Azzedde/llama3.1-8b-text2cypher |
| `ragraph-ai/stable-cypher-instruct-3b` (StableLM 3B) | Yes, ChatML with a fixed system message and **only the bare question, no schema** (E) | `native_stable_cypher` | https://huggingface.co/ragraph-ai/stable-cypher-instruct-3b |
| `aigentx/llama-3.1-8b-instruct-cypher` (LoRA r=16, base `unsloth/Meta-Llama-3.1-8B-Instruct-unsloth-bnb-4bit`) | **None documented** (Unsloth boilerplate card only) | none, uses `pipe_standard` | https://huggingface.co/aigentx/llama-3.1-8b-instruct-cypher |
| `aigentx/llama-3.1-8b-instruct-cypher-mixed-samples` (LoRA r=16, same base) | **None documented** (auto-generated empty card) | none | https://huggingface.co/aigentx/llama-3.1-8b-instruct-cypher-mixed-samples |
| `projectwilsen/llama3.1-8b-text2cypher-neo4j-live` (rsLoRA r=16, base `unsloth/Meta-Llama-3.1-8B-bnb-4bit`) | **None documented** (Unsloth boilerplate card only) | none | https://huggingface.co/projectwilsen/llama3.1-8b-text2cypher-neo4j-live |
| `Saiprasanth15/llama3.1-8b-text2cypher-neo4j-live` (rsLoRA r=16, same base) | **None documented** (card is identical boilerplate) | none | https://huggingface.co/Saiprasanth15/llama3.1-8b-text2cypher-neo4j-live |

For the four checkpoints with no documented format, the paper must say "no documented
prompt format; evaluated with the standard PIPE-Cypher prompt". Possibly related but
**not used**: the same author (Geraldus Wilsen) published an Alpaca template for a
*Llama-3* text2cypher notebook (`neo4j-labs/text2cypher/finetuning/unsloth-llama3/llama3_text2cypher_simple.ipynb`).
It is not linked from either Llama-3.1 card, so it is not treated as documented.

### Verbatim templates

(A) Neo4j Gemma-2 2024 card, "Example Cypher generation". This is the `content` of the only `user` message:

```python
instruction = (
    "Generate Cypher statement to query a graph database. "
    "Use only the provided relationship types and properties in the schema. \n"
    "Schema: {schema} \n Question: {question}  \n Cypher output: "
)
```

(B) Neo4j official Colab for the Gemma-3 2025 models. It says: "You will need to prompt the
model in a similar way the model was finetuned". The template is sent as `messages=[{"role": "user", ...}]`:

```python
USER_PROMPT_TEMPLATE="""Generate a Cypher query for the Question below.
Use the information about the nodes, relationships, and properties from the Schema section below to generate the best possible Cypher query.
Return only the Cypher query as your final output, without any additional text or explanation.
####Schema:
{schema}
####Question:
{question}"""
```

The Colab also post-processes output with `.replace("\\n", "\n")`. Our
`unescape_literal_whitespace` does the same outside quoted literals.

(C) tomasonjo card, "Example usage":

```python
{"role": "system", "content": "Given an input question, convert it to a Cypher query. No pre-amble."},
{"role": "user", "content": f"""Based on the Neo4j graph schema below, write a Cypher query that would answer the user's question:
{schema}

Question: {question}
Cypher query:"""}
```

(D) Azzedde card, "How to Get Started with the Model". The text goes to `tokenizer(input_text)` with no chat template, so we send it as a raw `/v1/completions` prompt. vLLM adds BOS, as the tokenizer does.

```python
cypher_prompt = """Below is a database Neo4j schema and a question related to that database. Write a Cypher query to answer the question.

### Schema:
{schema}

### Question:
{question}

### Cypher:
"""
```

We stop generation at `"\n###"`. The card does not specify this. It only truncates any
following Alpaca section, so it cannot change a Cypher statement.

(E) ragraph-ai card, "Usage" (GGUF example; the tokenizer chat template uses the same default system message):

```python
full_prompt = f"<|im_start|>system\nCreate a Cypher statement to answer the following question:<|im_end|>\n<|im_start|>user\n{question}<|im_end|>\n<|im_start|>assistant\n"
```

## Serving notes that affect validity

- **LoRA routing.** Requests use the LoRA alias (`served_model_name == lora.alias`). The base model is served under a different `base_served_model_name`, and the manifest loader rejects equal names. Preflight checks that the alias appears in `/models`. This is the June 404 failure mode.
- **Gemma-2 LoRA.** The Gemma-2 chat template rejects the system role, so the `pipe_*` formats use `system_message_mode: merge`. The native format has no system turn. The adapter was trained on a 4-bit NF4 base and is served on the bf16 base.
- **projectwilsen / Saiprasanth.** The non-instruct base has no chat template, so these are served with `configs/chat_templates/plain_generation.jinja`. That template emits no BOS token, and vLLM chat requests do not add one. Treat their numbers as format-sensitive. A BOS-emitting template would need a new file under `configs/chat_templates/`, outside this change.
- **stable-cypher.** The safetensors repo declares bitsandbytes 8-bit, which vLLM rejected in June. The manifest serves the author's merged `stable-cypher-instruct-3b.f16.gguf` with `--tokenizer ragraph-ai/stable-cypher-instruct-3b`. vLLM GGUF loading for `stablelm` is **unverified** on ds-serv6.
- **Qwen3-Coder-30B-A3B.** This uses the official `Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8` on TP=2. FP8 MoE as weight-only Marlin on Ampere A5000 is **unverified**. The fallback is the official bf16 checkpoint on TP=4, then the community AWQ (`cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`).
- **Gemma-4-12B-it** (current Gemma successor) needs a vLLM build with Gemma 4 support. This is **unverified**.
- **License-gated** (HF `gated=manual`): `google/gemma-3-12b-it`, `google/gemma-3-27b-it`, `google/gemma-2-9b-it` (the Neo4j LoRA base), `meta-llama/Llama-3.1-8B-Instruct`, and `meta-llama/Llama-3.3-70B-Instruct` (the AWQ mirror is ungated, but the license still applies).
- **Generator overlap.** `Qwen/Qwen3.5-9B` generated and judged the benchmark (`is_generator: true`). Report it as a self-model row, not as independent transfer evidence.
- **Hosted reference** (`gpt6_luna`, served name `gpt-6-luna`, AGENTS.md owner decision of 2026-11-11). It runs on public graphs only (`finbench`, `snb`, `icij_offshoreleaks`, and the public Neo4j example graphs `t2c_fincen`, `t2c_northwind`, `t2c_recommendations`) as a reference ceiling. It is never launched and is never part of the private-deployment story. The key comes from `OPENAI_API_KEY` or `PIPE_CYPHER_LLM_API_KEY` and never appears in commands, logs, or metadata. Both the prediction script and the suite refuse non-public `graph_profile`s before contacting the endpoint. `send_temperature: false` is set until it is confirmed that the model accepts `temperature=0`.

## Run directories

| Condition | Directory under `artifacts/evaluations/` | Parsed by |
| --- | --- | --- |
| `zero_pipe_standard` | `<prefix>_downstream_<slug>` | `_control_slug_from_zero_run` gives `<slug>` |
| `zero_pipe_governed`, `zero_native` | `<prefix>_promptfmt_<slug>_<condition>` | ignored by the few-shot control parsers |
| `fewshot_ordered` | `<prefix>_control_<slug>_ordered_logged` | `_parse_control_run_id` gives `(<slug>, ordered)` |
| `fewshot_scored_no_signature` | `<prefix>_control_<slug>_scored_no_signature` | gives `(<slug>, scored_no_signature)` |
| `fewshot_random_seed{13,17,23}` | `<prefix>_control_<slug>_random_seed{N}` | gives `(<slug>, random_seedN)` |

Each directory holds `{zero,few}_shot_{predictions,evaluation}.jsonl`, `*_summary.json`,
`predict.log`, `evaluate.log`, and `metadata.json`. The metadata records the model,
hf_id/sha, served name, LoRA alias, provider, base_url, prompt format and source URL,
few-shot mode and seed, benchmark manifest sha256, split sha256, few-shot pool sha256,
model-manifest sha256, git revision and dirty flag, commands, exit codes, status, and
timestamps. Every prediction row also carries `prompt_format`, `prompt_transport`,
`system_message_mode`, `provider`, and `prompt_sha256`. The hash covers the canonical
JSON of the messages actually sent (after system merging), or the raw completion prompt.

## Commands

Run from the repo root on ds-serv6. The benchmark must be the approved manifest
(currently `artifacts/benchmarks/20260604_live_full_qwen9b_reviewfix`, test split
sha256 `46ee19ef069ece7dd287a7eb2f06781ecd6711f6a2f5afb437d37a3494407f61`).

```bash
# 1. Inspect everything that would run (no files written, no endpoints contacted)
python scripts/run_downstream_suite.py \
  --benchmark artifacts/benchmarks/20260604_live_full_qwen9b_reviewfix --split test \
  --tier core --prefix 20261111_naacl2027 --dry-run --launch --gpu-ids 2

# 2a. Against an endpoint you already started (one model per endpoint)
python scripts/run_downstream_suite.py \
  --benchmark artifacts/benchmarks/20260604_live_full_qwen9b_reviewfix --split test \
  --models qwen25_coder7b --endpoint qwen25_coder7b=http://localhost:8001/v1 \
  --prefix 20261111_naacl2027

# 2b. Let the suite start/stop vLLM per model on explicitly free GPUs
python scripts/run_downstream_suite.py \
  --benchmark artifacts/benchmarks/20260604_live_full_qwen9b_reviewfix --split test \
  --models tomasonjo_text2cypher8b,azzedde_llama31_text2cypher,neo4j_gemma3_4b_text2cypher \
  --launch --gpu-ids 2 --port 8001 --conda-env pipe-rdf-arr \
  --continue-on-model-failure --skip-existing --prefix 20261111_naacl2027

# 2c. Hosted reference row (public graphs only; key from the environment, never on the CLI)
python scripts/run_downstream_suite.py \
  --benchmark artifacts/benchmarks/20260604_live_full_qwen9b_reviewfix --split test \
  --models gpt6_luna --prefix 20261111_naacl2027

# 3. Few-shot control summary: the exact command is written to
#    artifacts/evaluations/20261111_naacl2027_suite_index.json (fewshot_control_summary_command)
```

Exit codes: 0 means every selected model completed. 4 means at least one model's queue
stopped. Details are in `logs/<prefix>_downstream_suite_failures.jsonl`, and the queue
stops on a preflight failure, a non-zero prediction exit, evaluator exit 3 (invalid
run), or another evaluator error. Without `--continue-on-model-failure`, the suite stops
at the first failed model. `--limit` runs are development diagnostics, not paper results.

Note: `scripts/generate_text2cypher_predictions.py` documents "exit 3" for the
consecutive-error abort, but `raise SystemExit("<message>")` exits with status 1. The
suite treats any non-zero prediction exit as a failure, so this does not affect the queue.
