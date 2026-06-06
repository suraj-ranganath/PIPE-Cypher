# Benchmark Format

PIPE-Cypher exports accepted examples as JSONL files with deterministic
train/dev/test splits.

## Files

Each benchmark directory contains:

- `all.jsonl`: all accepted examples.
- `train.jsonl`, `dev.jsonl`, `test.jsonl`: split files.
- `stats.json`: graph, category, difficulty, schema, and gate summaries.
- `manifest.json`: source run paths, split seed, result-sample limit, and export
  checksum.

## Row Fields

Important row fields include:

- `id`: stable example identifier.
- `question`: generated NL question.
- `cypher`: accepted read-only Cypher query.
- `graph_profile`: graph profile used for generation.
- `category`: workload category such as `simple_retrieval`,
  `complex_aggregation`, `negation_difference`, or `ranking_topk`.
- `difficulty`: difficulty label assigned by the pipeline and judge.
- `features`: structural query features such as hop count, relationship count,
  aggregation, ordering, negation, path pattern, return arity, and estimated
  result size when available.
- `validation`: deterministic gate outcomes.
- `judge`: local LLM-judge decision and scores.
- `result_sample`: bounded execution sample used for review.
- `source`: run/model/provenance metadata.

Exact fields can evolve as the benchmark card evolves, so downstream consumers
should ignore unknown fields and require only `question`, `cypher`, `category`,
`graph_profile`, and the relevant split file.

## Evaluation

For Text2Cypher evaluation, run model predictions against the same graph snapshot
used for benchmark export. PIPE-Cypher reports:

- parse validity;
- schema validity;
- read-only safety;
- execution success;
- exact execution accuracy;
- answer-set F1;
- per-graph, per-category, per-difficulty, and per-strategy breakdowns.

Reference-overlap metrics such as ROUGE, BLEU, METEOR, BERTScore, FrugalScore,
cosine similarity, Jaro-Winkler, and exact string match are implemented for
debugging answer rendering and near-match behavior. They do not replace
execution accuracy or answer-set F1 for Text2Cypher correctness.
