# Independent Validation Protocol (E2.1 cross-family re-judging, E2.2 human validation)

Purpose: answer the main rejection point. The reviewers' concern is that one model,
Qwen/Qwen3.5-9B, both generated the reference Cypher and judged it, so the references
may be wrong for their questions. Two experiments address this:

- **E2.1** re-judges every benchmark item with independent judges from other model
  families, using the unchanged judge prompt contract, and reports agreement.
- **E2.2** has humans validate reference correctness at two levels: every query
  template, and a stratified 300-item sample. It reports a benchmark error rate with a
  confidence interval and inter-annotator agreement.

Approved manifest: `artifacts/benchmarks/20260604_live_full_qwen9b_reviewfix`
(3,000 accepted items; FinBench 8x250, SNB 8x125). All outputs below are
**PRIVATE/internal** unless stated as aggregate, because they contain questions,
Cypher literals, and result rows. Smoke and stub runs of this tooling are
engineering checks only and are not paper evidence.

## What the tooling guarantees

- `scripts/rejudge_with_independent_model.py` calls the existing `LLMJudge.judge`
  path, so the inputs match the original judge exactly:
  - system prompt `SYSTEM_JSON_ENGINEER` and the `JUDGE_PROMPT` template;
  - `schema_slice_for_cypher` schema slice and the first 5 execution rows;
  - validation summary (`ok`, issues, structural features);
  - `temperature=0.0`, `max_tokens=512`, `response_format=json_object`, and the
    categorical-value guard.

  Every row records the prompt SHA-256, the user-prompt SHA-256, the judge-contract
  SHA-256 (`421c7b…`, which matches the paper's prompt-contract appendix), the raw
  response text, latency, token usage, provider, call settings, and the error kind.
- Context reconstruction (`--context-source auto`, the default) has two levels.
  - **Source record.** It looks up each exported row's `source.records_path`, which
    exists for all 7 runs in the manifest, and restores the original `ValidationResult`
    and `ExecutionResult` byte-for-byte. A check on the full export found the export-only
    reconstruction (rows from `result_rows_sample`, warnings recomputed with the current
    validator) gives an identical prompt for 3,000/3,000 items.
  - **Re-execution.** `--neo4j-config graph=yaml` re-executes the reference read-only
    (`limit_rows=25`, as in the pipeline) and logs whether the stored sample is a subset
    of the fresh rows.
- Failed calls are logged as `request_error`, `parse_error`, or `judge_output_error`
  and are never replaced by the deterministic fallback.
  - The run aborts (exit 3) after 5 consecutive final failures. The client already
    retries transport errors, 429, and 5xx.
  - It exits 4 if more than 1% of targeted calls failed. Rerun with `--resume` to fill
    the gaps.
  - The preflight (`/models`) aborts with exit 2 before any call if the model is not
    served.
- Provenance found while building the tool:
  - **43 of the 3,000 accepted items were never LLM-judged.** Qwen returned output
    that could not be parsed, and the deterministic fallback passed them
    (`original_decision_source=deterministic_fallback_after_llm_error`). The re-judge
    covers them, and the analyzer reports them as a separate slice.
  - Only **67 rejected candidates** in the manifest runs have a preserved LLM judge
    decision with valid, executed, non-empty queries. They form the
    "original-fail" set needed for a meaningful kappa.
  - The other 1,858 rejections are skipped, and each skip is logged with its reason in
    `<output>.skipped.jsonl`:
    - 1,363 were duplicates whose judge output was overwritten after judging;
    - 486 returned empty results;
    - the rest failed validation or execution.
- Prompt-version caveat:
  - Git history shows three categorical-guard lines added to `JUDGE_PROMPT`
    (f079ff5) and categorical lists added to `configs/schema_finbench.json`
    (1246142, 15fbb49) on June 1–2.
  - The commit timestamps cannot be aligned with the June-1 run timestamps, so it is
    unverified whether the June-1 FinBench/SNB runs used exactly today's contract.
  - To check, run
    `grep -m3 -i "rev\|commit" /home/suraj/PIPE-Cypher/logs/20260601_full_qwen9b_full_generation.log`.
  - Either way, the **Qwen re-run control** below removes the confound: it gives
    Qwen's decision under the exact contract the independent judges see.

## Judge line-up

| Role | Model | Where | Notes |
| --- | --- | --- | --- |
| Frontier independent judge | `gpt-6-luna` (hosted OpenAI) | OpenAI API | **Public LDBC graphs only.** The script refuses any graph other than finbench/snb with `--provider openai`. Owner-approved exception to the local-weights rule in AGENTS.md; AGENTS.md should be updated to record it. |
| Local cross-family judge (pick at least one) | `meta-llama/Llama-3.3-70B-Instruct` as an AWQ INT4 checkpoint | ds-serv6, TP=4 | about 40 GB of weights, about 10 GB per GPU. |
| Local cross-family judge (alternative or second) | `google/gemma-3-27b-it` (bf16) | ds-serv6, TP=4 | 54 GB of bf16 weights. |
| Same-family control | `Qwen/Qwen3.5-9B` | ds-serv6, TP=1 | Measures Qwen self-consistency under today's contract (`judge_role=same_family_control`, excluded from "independent" flags). |

The paper can then report both a frontier and a local cross-family check.

Check that GPUs are free before serving: run `nvidia-smi` and
`python scripts/check_gpu_host.py`. Do not take GPUs that have another user's
resident processes. A two-GPU tensor-parallel attempt on this host once failed
(`knowledge_base/ds_serv6_model_serving.md`). If TP>1 fails, fall back to single-GPU
cross-family judges: `meta-llama/Llama-3.1-8B-Instruct` bf16 (16 GB), or an int4
`gemma-3-12b-it`. Report the judge actually used.

## E2.1 commands (run on ds-serv6 from /home/suraj/PIPE-Cypher, inside tmux)

```bash
cd /home/suraj/PIPE-Cypher && git rev-parse HEAD | tee logs/e21_code_revision.txt
B=artifacts/benchmarks/20260604_live_full_qwen9b_reviewfix
RECS="$(python -c "import json;print(' '.join(json.load(open('$B/manifest.json'))['records_paths']))")"
SCHEMAS="--schema finbench=configs/schema_finbench.json --schema snb=configs/schema_snb.json"
OUT=artifacts/independent_validation/e21; mkdir -p $OUT
```

### Serve the local judges

`EXTRA_VLLM_ARGS` replaces the script default, so `--no-enable-flashinfer-autotune` is
repeated in it. Replace `<AWQ-REPO>` with a verified AWQ INT4 export of
Llama-3.3-70B-Instruct; check the repo id and license acceptance on the Hub first.
```bash
# Llama-3.3-70B AWQ on GPUs 0-3, port 8101
CONDA_ENV=pipe-rdf-arr CUDA_VISIBLE_DEVICES=0,1,2,3 PORT=8101 \
SERVED_MODEL_NAME=meta-llama/Llama-3.3-70B-Instruct MAX_MODEL_LEN=8192 GPU_MEMORY_UTILIZATION=0.90 \
EXTRA_VLLM_ARGS="--no-enable-flashinfer-autotune --quantization awq_marlin --dtype float16 --max-num-seqs 32" \
bash scripts/serve_qwen_vllm.sh <AWQ-REPO> 2>&1 | tee logs/vllm_8101_llama33_awq.log

# Gemma-3-27B-it bf16 on GPUs 4-7, port 8102 (vLLM >= 0.8 for Gemma 3)
CONDA_ENV=pipe-rdf-arr CUDA_VISIBLE_DEVICES=4,5,6,7 PORT=8102 \
SERVED_MODEL_NAME=google/gemma-3-27b-it MAX_MODEL_LEN=8192 GPU_MEMORY_UTILIZATION=0.90 \
EXTRA_VLLM_ARGS="--no-enable-flashinfer-autotune --dtype bfloat16 --max-num-seqs 32" \
bash scripts/serve_qwen_vllm.sh google/gemma-3-27b-it 2>&1 | tee logs/vllm_8102_gemma3_27b.log
```

### Engineering check (not evidence)

Run 20 items per judge. Inspect `error_kind` and `raw_response_text`, and time the call.
```bash
python scripts/rejudge_with_independent_model.py --benchmark $B $SCHEMAS \
  --base-url http://localhost:8101/v1 --model meta-llama/Llama-3.3-70B-Instruct --judge-label llama33_70b_awq \
  --limit 20 --seed 7 --output $OUT/check_llama.jsonl
```
Gemma 3's chat template folds a system message into the first user turn. If the server
nevertheless returns `400 System role not supported`, the run aborts within 5 items.
Rerun it with `--system-message-mode merge`; the mode is recorded per row.

### Full runs

Each run covers 3,000 accepted items plus 67 judge-decided rejected candidates. Delete
the check files first, or use new output names.
```bash
python scripts/rejudge_with_independent_model.py --benchmark $B --records $RECS $SCHEMAS \
  --base-url http://localhost:8101/v1 --model meta-llama/Llama-3.3-70B-Instruct --judge-label llama33_70b_awq \
  --concurrency 16 --output $OUT/rejudge_llama33_70b_awq.jsonl 2>&1 | tee logs/e21_llama.log

python scripts/rejudge_with_independent_model.py --benchmark $B --records $RECS $SCHEMAS \
  --base-url http://localhost:8102/v1 --model google/gemma-3-27b-it --judge-label gemma3_27b \
  --concurrency 16 --output $OUT/rejudge_gemma3_27b.jsonl 2>&1 | tee logs/e21_gemma.log

# Hosted frontier judge. Public LDBC graphs only; the key comes from the environment
# and is never logged. The judge model needs the key in its environment; set it with
# an `export` in a private shell, never in a committed file.
#
# Reasoning models count hidden reasoning tokens against max_completion_tokens, so
# 512 can come back empty. Raise --max-tokens. --no-temperature is needed if the
# model rejects temperature=0. Both deviations are recorded in every row.
python scripts/rejudge_with_independent_model.py --benchmark $B --records $RECS $SCHEMAS \
  --provider openai --model gpt-6-luna --judge-label gpt6_luna \
  --no-temperature --reasoning-effort low --max-tokens 4096 \
  --concurrency 4 --output $OUT/rejudge_gpt6_luna.jsonl 2>&1 | tee logs/e21_gpt6_luna.log

# Same-family control: serve Qwen3.5-9B on one free GPU on port 8000 as for generation
python scripts/rejudge_with_independent_model.py --benchmark $B --records $RECS $SCHEMAS \
  --base-url http://localhost:8000/v1 --model Qwen/Qwen3.5-9B --judge-label qwen35_9b_rerun \
  --concurrency 8 --output $OUT/rejudge_qwen35_9b_rerun.jsonl 2>&1 | tee logs/e21_qwen_control.log
```
Each prompt is about 3.4K characters (about 1K tokens), so a judge pass is about 3M
prompt tokens. Time the 20-item check before promising a wall-clock figure. On a
failure exit (3 or 4), fix the endpoint and rerun the same command with `--resume`.

### Analyze agreement

```bash
python scripts/analyze_judge_agreement.py \
  --rejudge $OUT/rejudge_gpt6_luna.jsonl $OUT/rejudge_llama33_70b_awq.jsonl \
            $OUT/rejudge_gemma3_27b.jsonl $OUT/rejudge_qwen35_9b_rerun.jsonl \
  --output-json $OUT/judge_agreement.json --output-md $OUT/judge_agreement.md \
  --output-tex $OUT/judge_agreement.tex --output-slices-tex $OUT/judge_agreement_by_category.tex \
  --output-disagreements-csv $OUT/judge_disagreements_PRIVATE.csv --require-complete
```
The adjudication packet (`judge_disagreements_PRIVATE.csv`) contains every
non-unanimous item. Original-pass items flagged by the most independent judges come
first. Adjudicate at least every item flagged by 2 or more independent judges, filling
the `adjudicated_*` columns.

## E2.2 commands (human validation; run locally or on the server, no GPU)

```bash
B=artifacts/benchmarks/20260604_live_full_qwen9b_reviewfix; V=artifacts/independent_validation/e22
SCHEMAS="--schema finbench=configs/schema_finbench.json --schema snb=configs/schema_snb.json"
```

Template packet: 123 signatures and 143 rows. The top 20 signatures cover 96.6% of
items, so this is the highest-leverage check.
```bash
python scripts/build_benchmark_validation_packet.py --benchmark $B --mode templates \
  --realizations 2 --seed 17 --annotators 2 $SCHEMAS --output-dir $V/templates
```

Instance packet: 300 items, proportional over graph x category (25 per FinBench
stratum, 12 or 13 per SNB stratum). Use 3 annotators if possible.
```bash
python scripts/build_benchmark_validation_packet.py --benchmark $B --mode instances \
  --n 300 --seed 17 --annotators 3 $SCHEMAS --output-dir $V/instances
```

Send each annotator only their own `*_annotator_K.csv`, the `*_rubric.txt`, and the
`schema_*.txt` files. The sheets are blind to the original judge decision. Annotators
work independently and fill `question_unambiguous`, `reference_correct`,
`answer_columns_appropriate`, `error_type`, and `notes`.

Analyze the filled sheets:
```bash
python scripts/analyze_benchmark_validation.py \
  --sheets $V/instances/filled/annotator_1.csv $V/instances/filled/annotator_2.csv $V/instances/filled/annotator_3.csv \
  --key $V/instances/benchmark_validation_instances_key.csv \
  --output-json $V/instances_report.json --output-md $V/instances_report.md --output-tex $V/instances_report.tex \
  --output-disagreements-csv $V/instances_disagreements_PRIVATE.csv
```

Adjudicate the disagreements: fill the `adjudicated_*` columns in a copy of the
disagreement CSV. Then rerun with `--adjudication <filled copy> --require-complete`.
The command exits non-zero until every reference label is resolved. Repeat both steps
for `$V/templates` with `benchmark_validation_templates_key.csv`.

## How results map to paper claims

Pre-commit to these reporting rules before looking at the labels.

1. **Benchmark reference error rate.**
   - Headline: the instance packet's `headline.reference_error_rate`, as a consensus
     after adjudication, with a Wilson 95% CI. Example form: "x% of sampled references
     are incorrect (95% CI [a, b], n=300)".
   - Also report the stratified estimate and the per-graph, per-category rates from
     `slices`.
   - Before adjudication, report only the any/all-annotator bounds.
2. **Template-level coverage.** Report the template packet's
   `estimates.signatures.signatures_with_incorrect_realization` (k of 123 signatures)
   and the frequency-weighted item error. Because the top 20 signatures cover 96.6% of
   items, one incorrect high-frequency template is a material finding. Either fix it
   and re-export, or disclose it.
3. **Human agreement.** Report Cohen's kappa per annotator pair (and Fleiss' kappa for
   3 annotators) on `reference_correct`, plus raw agreement and Gwet's AC1. AC1 matters
   because error prevalence is low and kappa is then unstable.
4. **Cross-family judge agreement.**
   - For each independent judge, report the pass rate on the 3,000 accepted items and
     the flag rate (original pass, independent fail) with a Wilson CI.
   - Report agreement, kappa, and AC1 against the original judge on all 3,067 items.
     The 67 rejected items are what make kappa meaningful.
   - Report Fleiss' kappa across judges and the Qwen-rerun control.
   - Report the 43 fallback-accepted items as their own row (`by_original_decision_source`).
5. **Flagged-item adjudication.**
   - For items flagged by 2 or more independent judges, report how many humans confirm
     as incorrect.
   - Confirmed-incorrect items are either removed in a re-export or disclosed.
   - If the export changes, AGENTS.md requires rerunning or relabeling the downstream
     and few-shot tables on the new split. Never reuse old downstream metrics on a
     changed split.
6. Report every judge, including weak or disagreeing ones, and the error and skip
   counts from each `*.summary.json`. Do not drop a judge after seeing its numbers.

## Provenance checklist per run

Keep the following for each run:
- the `*.summary.json` files, with status, failed-call rate, code revision,
  benchmark/schema SHA-256, served models, provider, and call settings;
- the `*.skipped.jsonl` files;
- the packet manifests, with SHA-256 of the sheets, key, and rubric;
- the filled sheets as returned;
- the adjudication files.

Record these in `knowledge_base/claim_evidence_map.yaml` before any number reaches the
manuscript. Only aggregate JSON/Markdown/LaTeX outputs go into paper surfaces.
