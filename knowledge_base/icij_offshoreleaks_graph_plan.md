# ICIJ Offshore Leaks Third-Graph Onboarding Plan

## Rationale

ICIJ Offshore Leaks is the strongest public third-graph candidate found for an
enterprise-style PIPE-Cypher onboarding study. It is not a synthetic benchmark:
it is a public investigative finance and compliance graph with officers,
offshore entities, intermediaries, addresses, source datasets, relationship
dates, and entity-resolution style links. That makes it a useful proxy for
private KYC, AML, financial-crime, ownership, and risk-investigation graphs.

Use this graph as an additional onboarding/generalization artifact, not as a
replacement for the primary FinBench/SNB research-quality results. As of June 2,
2026, only the corrected target-100 run
`20260602_icij_target100_schema_templates_v3` has been loaded, generated,
audited, sanitized, and collected with the same standards as the LDBC runs. The
earlier incomplete catfix run is failure-analysis evidence only.

## Verified Public Artifacts

Sources checked on June 2, 2026:

- Database overview: `https://offshoreleaks.icij.org/pages/database`
- Data package repository: `https://github.com/ICIJ/offshoreleaks-data-packages`
- Latest CSV package:
  `https://offshoreleaks-data.icij.org/offshoreleaks/csv/full-oldb.LATEST.zip`
  - HTTP 200
  - `Content-Length: 73043531`
  - `Last-Modified: Mon, 31 Mar 2025 09:28:02 GMT`
- Neo4j dump:
  `https://offshoreleaks-data.icij.org/offshoreleaks/neo4j/icij-offshoreleaks-5.13.0.dump`
  - HTTP 200
  - `Content-Length: 364540369`
  - `Last-Modified: Mon, 31 Mar 2025 09:22:40 GMT`

The latest CSV package expands to roughly 626 MB and contains these files:

| File | Expanded bytes |
|---|---:|
| `nodes-entities.csv` | 198,926,104 |
| `nodes-officers.csv` | 91,021,122 |
| `nodes-addresses.csv` | 72,465,663 |
| `nodes-intermediaries.csv` | 3,944,578 |
| `nodes-others.csv` | 398,436 |
| `relationships.csv` | 259,198,321 |

## Schema Snapshot

CSV-derived node counts from the latest package:

| Label | Nodes |
|---|---:|
| `Entity` | 814,344 |
| `Officer` | 771,315 |
| `Address` | 402,246 |
| `Intermediary` | 25,629 |
| `Other` | 2,989 |

CSV-derived relationship counts:

| Relationship type | Relationships |
|---|---:|
| `officer_of` | 1,720,357 |
| `registered_address` | 832,721 |
| `intermediary_of` | 598,546 |
| `same_name_as` | 104,170 |
| `similar` | 46,761 |
| `same_company_as` | 15,523 |
| `connected_to` | 12,145 |
| `same_as` | 4,272 |
| `same_id_as` | 3,120 |
| `underlying` | 1,308 |
| `similar_company_as` | 203 |
| `probably_same_officer_as` | 132 |
| `same_address_as` | 5 |
| `same_intermediary_as` | 4 |

Dominant relationship directions include `(:Officer)-[:officer_of]->(:Entity)`,
`(:Intermediary)-[:intermediary_of]->(:Entity)`,
`(:Entity)-[:registered_address]->(:Address)`, and
`(:Officer)-[:registered_address]->(:Address)`.

## Commands

Fetch the CSV/dump and produce a local schema summary:

```bash
RUN_ROOT=/home/suraj/pipecypher-icij-offshoreleaks \
FETCH_DUMP=true \
scripts/fetch_icij_offshoreleaks.sh
```

Generate the built-in reference schema used for offline smoke checks:

```bash
python scripts/inspect_schema.py \
  --config configs/icij_offshoreleaks_smoke.yaml \
  --reference-only \
  --output configs/schema_icij_offshoreleaks.json
```

Load the public Neo4j dump into a separate local Neo4j instance:

```bash
RUN_ROOT=/home/suraj/pipecypher-neo4j-icij \
DOWNLOAD_DIR=/home/suraj/pipecypher-icij-offshoreleaks/downloads \
SESSION=pipecypher_neo4j_icij \
BOLT_PORT=7689 \
HTTP_PORT=7476 \
AUTH_ENABLED=false \
scripts/load_icij_neo4j_dump.sh
```

Start the graph after the dump load:

```bash
RUN_ROOT=/home/suraj/pipecypher-neo4j-icij \
SESSION=pipecypher_neo4j_icij \
BOLT_PORT=7689 \
HTTP_PORT=7476 \
AUTH_ENABLED=false \
HEAP_INITIAL=6G \
HEAP_MAX=12G \
PAGECACHE=8G \
scripts/start_neo4j_community.sh
```

Introspect the live schema and then run a small dry pass:

```bash
python scripts/inspect_schema.py \
  --config configs/icij_offshoreleaks_smoke.yaml \
  --output configs/schema_icij_offshoreleaks_live.json

python scripts/run_pipeline.py \
  --config configs/icij_offshoreleaks_smoke.yaml \
  --run-name live_icij_qwen9b_onboarding
```

After the smoke run accepts all categories, use the larger live configuration:

```bash
python scripts/run_pipeline.py \
  --config configs/icij_offshoreleaks_full.yaml \
  --run-name live_icij_qwen9b_target100
```

Initial live target-100 diagnostic run as of June 2, 2026:

```text
remote root: /home/suraj/PIPE-Cypher-4df5175-catfix
session: pipecypher_icij_target100_after_seed17_catfix
endpoint: http://localhost:8001/v1
run name: 20260602_icij_target100_qwen9b_catfix_live
code revision: 4df5175396352e7ad695f6ad1c8ce14c493d6955
```

Outcome:

- records: 1,400
- accepted: 681
- categories at target: 6/8
- accepted category counts: `simple_retrieval=100`,
  `complex_retrieval=100`, `simple_aggregation=100`,
  `complex_aggregation=100`, `boolean_existence=100`,
  `path_temporal=100`, `negation_difference=79`, `ranking_topk=2`
- dominant failure reasons: duplicate accepted questions and empty execution
  results.

Research-use note: this run confirms that the public ICIJ graph is loaded and
the generic onboarding path can generate accepted examples across most
categories, but it is not paper-ready. Do not promote ICIJ numbers into the
paper or appendix result tables until a top-up or corrected run reaches the
target categories and passes the same readiness audit used for FinBench/SNB.

Root cause: ICIJ exposed a general arbitrary-schema onboarding failure, not an
ICIJ-specific loader problem. The ranking/top-k seed set had only two reusable
no-slot templates, so the category exhausted after two accepted questions. The
negation/difference seed relied on a sparse anti-join with only 79 productive
jurisdiction bindings; after those were consumed, generic slot lookup sampled
values that did not satisfy the final query predicate and produced empty
results. The same sparse-template pattern later appeared for
complex-aggregation during schema-template diagnostics.

General fix: PIPE-Cypher now derives deterministic templates directly from the
observed property-graph schema for sparse categories. For any onboarded graph,
the pipeline can add relationship-count aggregation templates, anti-join
negation templates, and top-k relationship-count templates, with scoped variants
over safe low-cardinality properties. Reverse grounding for scoped templates is
outcome-aware, so sampled slot values must satisfy the final query predicate.
Schema-derived templates do not fall back to broad generic slot lookup when
their outcome-aware bindings are unavailable or exhausted; they log
`slot bindings unavailable` or `slot bindings exhausted` instead. Future raw
generation records also carry template metadata so sparse-category evidence is
auditable without relying on question-string inference.

Corrected live target-100 run as of June 2, 2026:

```text
remote root: /home/suraj/PIPE-Cypher-afa1791-schema-templates-v3
session: pipecypher_icij_target100_schema_templates_v3
endpoint: http://localhost:8001/v1
run name: 20260602_icij_target100_schema_templates_v3
run directory: artifacts/runs/20260602_192926_20260602_icij_target100_schema_templates_v3
code revision: afa1791
run seed: 31
```

Outcome:

- live graph size: 2,016,523 nodes, 3,339,267 relationships, 5 labels, and 14
  relationship types.
- records: 983
- accepted: 800
- accept rate: 0.814
- categories at target: 8/8, with 100 accepted examples in every planned
  category.
- gate rates: read-only 1.000, syntax-valid 1.000, schema-valid 1.000,
  execution-success 0.814, non-empty execution 0.814, and judge-pass 0.814.
- sparse-category evidence: because this run predates explicit template
  metadata logging, schema-derived accepts are inferred from deterministic
  schema-derived question style: complex-aggregation 97, negation/difference
  28, and ranking/top-k 98.
- remaining failures are now expected exhaustion signals rather than invalid
  questions: complex-aggregation has 61 unavailable and 14 exhausted bindings,
  negation/difference has 23 unavailable and 15 exhausted bindings, and
  ranking/top-k has 57 unavailable and 13 exhausted bindings.
- sanitized local snapshot:
  `experiments/snapshots/20260602_icij_target100_schema_templates_v3/`.

Collection command:

```bash
python scripts/collect_remote_onboarding_run.py \
  --remote-root /home/suraj/PIPE-Cypher-afa1791-schema-templates-v3 \
  --run-prefix 20260602_icij_target100_schema_templates_v3 \
  --run-dir-name 20260602_192926_20260602_icij_target100_schema_templates_v3 \
  --target-per-category 100 \
  --graph-profile icij_offshoreleaks \
  --snapshot-dir experiments/snapshots/20260602_icij_target100_schema_templates_v3 \
  --generation-model Qwen/Qwen3.5-9B \
  --judge-model Qwen/Qwen3.5-9B \
  --code-revision afa1791 \
  --run-seed 31 \
  --config configs/icij_offshoreleaks_full.yaml \
  --metadata graph_nodes=2016523 \
  --metadata graph_relationships=3339267 \
  --metadata graph_labels=5 \
  --metadata graph_relationship_types=14
```

The ICIJ graph contains low-cardinality free-text properties such as notes and
addresses. Keep `privacy.categorical_max_value_chars` and
`privacy.categorical_omitted_properties` enabled during live introspection so
these values do not enter schema prompts or paper-facing artifacts.

## Paper Use

The defensible paper story is:

1. FinBench and SNB remain the completed research-quality evaluation workloads.
2. ICIJ Offshore Leaks demonstrates the onboarding path on a real public
   finance/compliance property graph with millions of graph records, including
   sparse-category schema-derived templates that are not tailored to LDBC.
3. ICIJ numbers may be used only from the corrected target-100 snapshot above,
   because it is complete, audited, summarized, and sanitized. The initial
   catfix run remains failure-analysis evidence only.

This lets the paper strengthen its industry motivation without pretending that a
public graph is a private enterprise deployment.
