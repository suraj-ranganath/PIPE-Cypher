# Diversity-Governed Selection

- Method: `greedy_mmr_cypher_diversity`
- Input examples: 3000
- Selected examples: 800
- Target per group: 50
- Group keys: `graph_profile, category`

| Group | Input | Target | Selected | Signatures | Families | Substructures | Underfilled |
|---|---:|---:|---:|---:|---:|---:|---|
| finbench::boolean_existence | 250 | 50 | 50 | 2 | 2 | 11 | no |
| finbench::complex_aggregation | 250 | 50 | 50 | 1 | 1 | 10 | no |
| finbench::complex_retrieval | 250 | 50 | 50 | 1 | 1 | 11 | no |
| finbench::negation_difference | 250 | 50 | 50 | 25 | 10 | 45 | no |
| finbench::path_temporal | 250 | 50 | 50 | 2 | 2 | 13 | no |
| finbench::ranking_topk | 250 | 50 | 50 | 3 | 3 | 17 | no |
| finbench::simple_aggregation | 250 | 50 | 50 | 1 | 1 | 8 | no |
| finbench::simple_retrieval | 250 | 50 | 50 | 1 | 1 | 10 | no |
| snb::boolean_existence | 125 | 50 | 50 | 1 | 1 | 10 | no |
| snb::complex_aggregation | 125 | 50 | 50 | 1 | 1 | 10 | no |
| snb::complex_retrieval | 125 | 50 | 50 | 1 | 1 | 16 | no |
| snb::negation_difference | 125 | 50 | 50 | 25 | 6 | 55 | no |
| snb::path_temporal | 125 | 50 | 50 | 1 | 1 | 11 | no |
| snb::ranking_topk | 125 | 50 | 50 | 41 | 5 | 62 | no |
| snb::simple_aggregation | 125 | 50 | 50 | 1 | 1 | 12 | no |
| snb::simple_retrieval | 125 | 50 | 50 | 1 | 1 | 8 | no |
