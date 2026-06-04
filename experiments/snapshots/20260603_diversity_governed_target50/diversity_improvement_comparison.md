# Diversity Improvement Comparison

| Metric | Random balanced | Diversity governed | Delta |
|---|---:|---:|---:|
| pipe_diversity_index | 0.520 | 0.524 | +0.004 |
| query_signature_ratio | 0.031 | 0.037 | +0.006 |
| top_signature_share | 0.062 | 0.062 | +0.000 |
| template_family_entropy | 0.917 | 0.889 | -0.028 |
| operator_combo_entropy | 0.944 | 0.944 | +0.000 |
| structural_substructures | 58.000 | 60.000 | +2.000 |
| self_bleu_2 | 0.845 | 0.846 | +0.001 |
| ead_distinct_2 | 0.252 | 0.265 | +0.012 |
| schema_property_coverage | 0.370 | 0.407 | +0.037 |

- Split mode: `signature_disjoint`
- Leakage-free split blocks: `True`
