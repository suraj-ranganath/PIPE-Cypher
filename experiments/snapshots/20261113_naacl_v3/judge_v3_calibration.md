# Judge v3 calibration (NAACL 2027 v3 rebuild)

Run on 2026-11-12 between 21:50Z and 22:20Z from the Mac. OpenRouter only; no gpt-6-luna calls were made.
Spend was $0.570 against a $0.60 cap. Ledger: `artifacts/naacl_v3/ledgers/calibration_spend.jsonl`.
Item-level files under `artifacts/naacl_v3/calibration/` are **PRIVATE**: they contain questions, Cypher literals, and result values.

## 1. Provider equivalence (GLM-5.3-Flash, Z.AI FP8 vs Novita FP8)

Setup:
- 150 v2 judged items: 100 that Z.AI passed and 50 it failed (seed 13).
- The exact stored v2 judge prompts were replayed twice on `novita/fp8` (temperature 0, reasoning effort low).
- Script: `scripts/provider_equivalence.py`.
- Summary: `artifacts/naacl_v3/calibration/provider_equivalence_summary.json`.

| Pair | Agreement | kappa |
| --- | ---: | ---: |
| Z.AI vs Novita, run 1 | 0.88 | 0.73 |
| Z.AI vs Novita, run 2 | 0.92 | 0.82 |
| Novita run 1 vs run 2 | 0.88 | 0.72 |

**Conclusion.** Cross-provider agreement is at the level of same-provider rerun agreement, so the provider switch cannot be told apart from judge run-to-run noise.

Other observations with the v2 prompt on Novita:
- Median latency 2.0 s.
- Cache hits 0.3%. The v2 prompt puts the per-item schema slice first, so its prefix is never shared between items.

## 2. Calibration set and reference

Built with `scripts/calibrate_judges.py select` (seed 2027).
- 150 v2 items: 75 FinBench, 75 SNB.
- Sampling oversampled the v2 judge decision patterns (GLM, gpt-6-luna, Qwen): TTT 30, TFT 35, TFF 20, TTF 20, FFT 20, FFF 10, FTT 11, FTF 4.
- Accepted and rejected candidates are both included.

**Reference: Claude adjudication.** These are LLM expert labels written item by item under the v3 convention sheet. They are not human labels.
- File: `claude_adjudication.jsonl`, one label and reason per item.
- Final labels: 69 correct, 33 wrong, 48 ambiguous. For agreement, wrong and ambiguous both count as "reject".
- Six labels were revised after iteration 1. They concerned self-exclusion: "other/another" with no `a <> b` in the query. The first pass had treated the gap as immaterial, which contradicted C10 as written. C10 was then made explicit and those labels aligned with it. Each revision is logged in the row.

This set is deliberately hard: it is oversampled for disagreement and carries v2-specific defects, so agreement on fresh v3 items is expected to be higher. **Report agreement on fresh v3 items and on the human labels, not these numbers.**

## 3. What changed in the judge

- **Convention sheet.** `pipecypher/conventions.py`, version v3.2, rules C1-C13. It was derived from the v2 gpt-6-luna flag reasons. The same text is meant for the question writer and the judge.
- **Checklist judge.** `ChecklistJudge` checks nine criteria, each answered yes/no/na with evidence. The model also writes a clause-by-clause `query_reading`. The verdict is computed by code:
  - pass only if all nine criteria are present;
  - none is answered no or invalid;
  - "unambiguous" is answered yes.
- **Out of scope for the judge:** ties, unordered-LIMIT truncation, emptiness, read-only, and syntax. Code checks all of these.
- **Prompt order for caching:** system, conventions, rubric, the full graph schema (identical per graph), then the item. GLM got 32-37% cache hits at 10-way concurrency.
- **Deterministic notes shown to the judge** (`pipecypher/judge.py`):
  - `unlisted_relationship_patterns`: a (start, type, end) triple the schema never lists, including inside EXISTS / NOT EXISTS.
  - `dropped_with_variables`: a variable not carried through a WITH and then re-bound to any node.
  - On the 2,080 v2 accepted items they flag 16 (0.8%), and all 16 are real errors. Examples: `(Person)-[:HAS_CREATOR]->(Message)` reversed inside NOT EXISTS; `(Forum)-[:CONTAINER_OF]->(Comment)`; and a template that drops `p` at a WITH and so returns every person's tags.
- **JudgePanel.** The gate accepts only if every member accepts. All members always run in parallel, and every member's verdict and checklist are recorded.

## 4. Results (150 items; reference = Claude adjudication)

| Judge / prompt | Pass rate | Agreement [95% CI] | kappa | False accepts | False rejects |
| --- | ---: | --- | ---: | ---: | ---: |
| GLM, v2 prompt (stored, Z.AI) | 0.70 | 0.53 | 0.10 | 53 | 17 |
| GLM, v2 prompt (Novita, same items) | 0.75 | 0.55 [0.47, 0.63] | 0.14 | 55 | 12 |
| gpt-6-luna, v2 prompt (stored) | 0.43 | 0.68 | 0.35 | 22 | 26 |
| Qwen3.5-9B, v2 prompt (stored) | 0.64 | 0.62 | 0.26 | 42 | 15 |
| GLM, v3 iteration 1 | 0.67 | 0.71 | 0.44 | 37 | 6 |
| GLM, v3 iteration 2 | 0.67 | 0.75 | 0.51 | 35 | 3 |
| GLM, v3 iteration 3 (reasoning low) | 0.65 | 0.79 | 0.58 | 30 | 2 |
| GLM, v3 iteration 3 (reasoning medium) | 0.67 | 0.77 | 0.55 | 33 | 2 |
| **GLM, v3 frozen (iteration 4)** | 0.59 | 0.83 [0.77, 0.88] | **0.67** | 22 | 3 |
| GLM, v3 frozen, rerun | 0.63 | 0.80 | 0.61 | 28 | 2 |
| Gemma-4-26B-A4B, v3 frozen | 0.70 | 0.73 | 0.48 | 38 | 2 |
| gpt-oss-20b, v3 frozen | 0.49 | 0.74 | 0.48 | 22 | 17 |
| Qwen3.5-9B, v3 iteration 1 | 0.65 | 0.65 | 0.31 | 41 | 12 |
| **Panel GLM + Gemma-4 (frozen)** | 0.53 | **0.87 [0.80, 0.91]** | **0.73** | 15 | 5 |
| Panel GLM rerun + Gemma-4 | 0.58 | 0.83 | 0.66 | 22 | 4 |
| Panel GLM + gpt-oss-20b (frozen) | 0.39 | 0.80 | 0.59 | 10 | 20 |

Pairwise agreement:

| Pair | Agreement | kappa |
| --- | ---: | ---: |
| GLM vs Gemma-4, frozen | 0.77 | 0.50 |
| GLM rerun vs Gemma-4 | 0.83 | 0.61 |
| GLM vs gpt-oss-20b | 0.71 | 0.41 |
| GLM frozen run-to-run | 0.90 | 0.79 |

For comparison, the v2 GLM prompt rerun on Novita gave kappa 0.72, on a different sample.

**Prompt ablation (same model, same provider, same items).** The v2 prompt reaches kappa 0.14 with the reference; v3 reaches 0.67.

## 5. Decision (frozen)

**Second panel judge: Gemma-4-26B-A4B on `primeintellect/bf16`, reasoning effort none.**

Why Gemma over gpt-oss-20b:
- best panel agreement with the reference (kappa 0.73 vs 0.59);
- far higher recall (0.93 vs 0.71), so the panel discards fewer correct items;
- higher inter-judge kappa;
- less than half of gpt-oss's cost ($0.00009 vs $0.00021 per call).

The cost is precision: 0.81 for the panel vs 0.83 with gpt-oss. gpt-6-luna (an outside auditor) and the humans measure the residual error rate.

**Frozen contract.**
- sha256 `a4b55edc63f086a2ae13f96a93ba2db24ec5ba55895f3226009542a4a89a362a`, covering the system text, prompt template, and convention sheet.
- Record: `artifacts/naacl_v3/calibration/frozen_judge_v3.json`.
- Guarded by `tests/test_judge_v3.py::test_judge_v3_contract_is_frozen`.

## 6. Residual false accepts of the panel (15 / 150)

The panel still accepts these deep semantic errors:
- correlated NOT EXISTS scope;
- a per-entity answer to a single-aggregate question;
- a cross product of two independent lists;
- a direction-neutral verb answered with one direction;
- a temporal window checked only against the first event;
- "owner type" mapped to accountType.

No prompt change fixed these within 4 iterations. They motivate the human audit and the gpt-6-luna audit, and they should be reported as limitations of LLM judging.

## 7. Cost per judged candidate (frozen prompt)

GLM: about 3,700 input tokens, 33% cached at concurrency 10, and about 550 output tokens.

| Judge | Cost per call |
| --- | ---: |
| GLM | $0.00038 |
| Gemma-4 | $0.00009 |
| Panel | about $0.00047 per candidate |

About 7,000 judged candidates therefore cost about $3.3. To cut this, run the judge only after the deterministic gates pass; see the integration notes.
