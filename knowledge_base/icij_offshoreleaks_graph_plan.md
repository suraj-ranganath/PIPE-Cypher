# ICIJ Offshore Leaks Third-Graph Onboarding Plan

## Rationale

ICIJ Offshore Leaks is the strongest public third-graph candidate found for an
enterprise-style PIPE-Cypher onboarding study. It is not a synthetic benchmark:
it is a public investigative finance and compliance graph with officers,
offshore entities, intermediaries, addresses, source datasets, relationship
dates, and entity-resolution style links. That makes it a useful proxy for
private KYC, AML, financial-crime, ownership, and risk-investigation graphs.

Use this graph as an additional onboarding/generalization artifact, not as a
replacement for the primary FinBench/SNB research-quality results. Do not report
ICIJ results in the paper until a completed live run has been loaded, generated,
audited, and collected with the same standards as the LDBC runs.

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
  --output configs/schema_icij_offshoreleaks.json

python scripts/run_pipeline.py \
  --config configs/icij_offshoreleaks_smoke.yaml \
  --run-name live_icij_qwen9b_onboarding
```

## Paper Use

The defensible paper story is:

1. FinBench and SNB remain the completed research-quality evaluation workloads.
2. ICIJ Offshore Leaks demonstrates the onboarding path on a real public
   finance/compliance property graph with millions of graph records.
3. Any ICIJ generation numbers should appear only after a live run is complete,
   audited, and summarized under the same paper-readiness criteria as the LDBC
   suites.

This lets the paper strengthen its industry motivation without pretending that a
public graph is a private enterprise deployment.
