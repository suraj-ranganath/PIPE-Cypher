# NAACL 2027 Industry Runbook

> **Status 2026-11-12:** The experiments were executed on `jamming` (CPU only) with hosted open-weight models (GLM-5.3-Flash FP8 generator/judge; downstream models at released precision) because GPU access ended. Results, decisions, and deviations are in `experiments/snapshots/20261112_naacl_v2/status.md`; the review-concern mapping is in `knowledge_base/naacl2027_reviewer_concern_map.md`. Parts of this document that refer to ds-serv6, local vLLM, or Qwen3.5-9B as generator are historical.


Deadline: **13 Nov 2026, 23:59 AoE** (OpenReview, 6 pages + Limitations).
The paper draft is `paper_naacl2027_industry/main.tex`; every red `\TBD{}` maps to an
output below. Context and rationale are in `knowledge_base/eacl_revision_plan.md`.
The detailed protocols are in:

- `knowledge_base/independent_validation_protocol.md` (judges, human validation)
- `knowledge_base/downstream_prompt_formats.md` (models, prompt formats, suite runner)
- `knowledge_base/external_anchor_protocol.md` (Text2Cypher-2024 anchor, ranking agreement)
- `knowledge_base/refresh_experiment_protocol.md` (schema migration / data drift)

## 0. Before anything (15 min)

1. Restore server access. From this laptop, `ssh suraj@ds-serv6.ucsd.edu` failed with
   `Permission denied (publickey)`. Try `ssh-add ~/.ssh/compute_key`.
2. Sync the code. Nothing is committed yet: review `git status`, then commit on `develop`
   and pull on the server, or use `scripts/sync_to_ds_serv6.sh`.
3. On the server, run `python -m pytest -q`; all tests must pass. Log `git rev-parse HEAD`.
4. `nvidia-smi`: only use GPUs with no other user's processes (AGENTS.md).
5. `export OPENAI_API_KEY=...` in a private shell only, never in a file. Then check it:
   `python -c "from pipecypher.llm import served_model_ids as s; print('gpt-6-luna' in s('https://api.openai.com/v1', provider='openai'))"`.
   This must print `True`. If not, find the exact model id first.
6. Validate configs:
   `for c in configs/{finbench,snb}_v2*.yaml configs/t2c_*.yaml; do python scripts/validate_config.py $c; done`.

## 1. Critical path: benchmark v2 (start first; about 5-12 h)

Serve Qwen3.5-9B on **two** free GPUs as two endpoints, one per graph, using the
usual `scripts/serve_qwen_vllm.sh` flags. Then run:

```bash
PIPE_CYPHER_LLM_BASE_URL=http://localhost:8000/v1 python scripts/run_pipeline.py --config configs/finbench_v2.yaml --run-name naacl_v2_finbench
PIPE_CYPHER_LLM_BASE_URL=http://localhost:8010/v1 python scripts/run_pipeline.py --config configs/snb_v2.yaml --run-name naacl_v2_snb
```

- Watch `attempt_summary.by_category`: `unique_accepted_signatures`, `induced_templates`, and
  `signature_quota_rejections`.
- If a cell stalls below target after all induction rounds, do not loosen gates. Two
  options:
  - lower the target, keeping cells balanced;
  - raise `max_examples_per_signature` from 8 to 12.

  Either way, report it.
- **First, a 20-minute pilot** with `target_per_category: 10`. Check that induction produces
  templates and that paraphrases keep values. Pilot output is engineering evidence only.

Export both splits from the same records:

```bash
python scripts/export_benchmark.py --records artifacts/runs/*naacl_v2_finbench* artifacts/runs/*naacl_v2_snb* --output-dir artifacts/benchmarks/naacl_v2_random
python scripts/export_benchmark.py --records <same> --output-dir artifacts/benchmarks/naacl_v2_heldout --split-strategy signature_disjoint
```

`stats.json` shows `unique_query_signatures`, `signature_split_overlap` (test must share
**0** signatures with train in `naacl_v2_heldout`), and `signature_split_cells_train_only`.
That fills the v2 column of Table 3 (`tab:diversity`).

## 2. Parallel tracks that do NOT need v2 (start immediately)

| Track | What | GPUs | Protocol |
| --- | --- | --- | --- |
| P1 | KNOWS direction check on SNB: compare the size of `(p)-[:KNOWS*1..2]->(x)` with `(p)-[:KNOWS*1..2]-(x)` for 20 test persons | none | below |
| P2 | Load recommendations/northwind/fincen dumps; run the gold-as-prediction harness check (must score 1.0) | none | external_anchor §4 |
| P3 | E3.4 anchor: all downstream models on the 596 curated T2C-2024 test rows (+ `test_unseen_question` slice) | 1-4 | external_anchor §4 + suite runner |
| P4 | E3.5: generate PIPE benchmarks on the 3 example graphs (`configs/t2c_*.yaml`) | 1 | external_anchor §4 |
| P5 | Generator-swap slice: `configs/{finbench,snb}_v2_genswap_gpt6luna.yaml` (hosted generator; the local Qwen judge must be up at :8000) | 0 (shares Qwen) | E2.4 |
| P6 | Refresh harness: second Neo4j instance on 7697, M0 control | none | refresh §1-4 |

P1 query (read-only):

```cypher
MATCH (p:Person) WITH p LIMIT 20
CALL { WITH p MATCH (p)-[:KNOWS*1..2]->(x:Person) RETURN count(DISTINCT x) AS directed }
CALL { WITH p MATCH (p)-[:KNOWS*1..2]-(x:Person) WHERE x <> p RETURN count(DISTINCT x) AS undirected }
RETURN p.id, directed, undirected
```

If `undirected > directed`, cite it in §5.2 as a reference error that v1's governance forced
and v2 fixes.

## 3. After v2 export (tracks in parallel)

| Track | What | Output, which fills |
| --- | --- | --- |
| A1 | Re-judge every v2 item and candidate with gpt-6-luna (hosted) and one local non-Qwen judge (Llama-3.3-70B AWQ on 4 GPUs, or Gemma-3-27B) + Qwen re-run control | `analyze_judge_agreement.py` -> §5.2 "Cross-family judges" |
| A2 | Human packets: templates (every signature x 2) + 300 instances, 2+ annotators | `analyze_benchmark_validation.py` -> abstract error rate, §5.2 "Human validation" |
| A3 | Downstream suite on `naacl_v2_heldout`, test split: core tier first, then T2C models with native formats, then gpt6_luna | `run_downstream_suite.py` -> Table 4 |
| A4 | Downstream on the gen-swap slice (P5) for all models | `analyze_downstream_statistics.py self-preference` -> §5.2 "Generator swap" |
| A5 | E3.5 ranking agreement: same models on PIPE-generated (P4) and curated (P3) items per graph | `rank-agreement` -> §5.2 "Agreement" |
| A6 | Refresh M1-M4, D1-D2 on v2 FinBench; accuracy misestimate with a Qwen zero-shot predictions file | refresh `table` -> §5.4 |
| A7 | Timed v2 build accounting (wall-clock, LLM calls, GPU-hours per 1k) from the step-1 run records | §5.4 cost sentence |

Statistics: always use `scripts/analyze_downstream_statistics.py` (signature-clustered CIs,
McNemar plus cluster sign-flip, medians across models). Never quote row-level bootstrap
CIs: on v1 they were 4x too narrow.

## 4. Guards that must hold before a number enters the paper

- The evaluator exits 0. Exit 3 means more than 1% of requests failed, so the run is
  invalid.
- `scripts/build_downstream_control_manifest.py` reports `all_complete: true`. It now
  checks request-failure rates.
- Every LoRA model is served under an adapter name distinct from its base model. The
  manifest enforces this; the June queue did not.
- Hosted-model artifacts stay separate from the Qwen-only main export (provenance guard).
- `pytest tests/test_naacl_paper_guards.py` passes, so no invalidated June numbers appear.
- `grep -c 'TBD{' paper_naacl2027_industry/main.tex` returns 0 and the build has no
  undefined references.
- Fill the `perlitz2024agreement` author list in `references.bib`; it is marked TODO.

## 5. If time runs out (honest fallbacks, in order of preference)

1. **v2 incomplete:** report the cells that reached target, list the missing cells
   explicitly, and keep v1 only as the diversity baseline. Do not mix v1 items into v2
   tables.
2. **No local 70B judge:** report gpt-6-luna and Gemma-3-27B (single-GPU AWQ fallback in
   the validation protocol).
3. **Human validation partial:** report the template-level check, which covers every
   signature, and state the instance sample size actually completed. Never extrapolate.
4. **E3.5 incomplete:** report E3.4 alone as a sanity anchor and move ranking agreement to
   Limitations as not done. Remove the claim from the abstract and contributions.
5. **Refresh incomplete:** report M1/M2 (the cheapest, most informative) and drop the rest
   from the text.

For any experiment that doesn't finish, remove its claim from the abstract, intro, and
conclusion. Do not leave a hedged version.

## 6. Known issues not fixed (low priority or out of time)

- `CONTEXTUAL_RETURN_PROPERTIES` in `pipecypher/validator.py` is hard-coded to FinBench
  labels. It should be derived from the profile. After migration M2 it won't recognize
  `blocked`.
- FinBench seed templates hard-code `TRANSFER_TO`/`isBlocked`. For refresh regeneration
  on M1/M2 copies, expect lower seed yield; induction and schema-derived templates
  carry the load.
- `configs/chat_templates/plain_generation.jinja` (projectwilsen, Saiprasanth adapters)
  emits no beginning-of-sequence token.
- Schema introspection records no node-label counts, so node-only drift is caught only by
  the execution audit.
