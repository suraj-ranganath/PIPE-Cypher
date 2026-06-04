# Diversity Improvement Comparison

| Metric | Random balanced | Diversity governed | Delta |
|---|---:|---:|---:|
| pipe_diversity_index | 0.557 | 0.575 | +0.017 |
| query_signature_ratio | 0.062 | 0.135 | +0.073 |
| top_signature_share | 0.062 | 0.062 | +0.000 |
| template_family_entropy | 0.903 | 0.868 | -0.035 |
| operator_combo_entropy | 0.901 | 0.911 | +0.010 |
| structural_substructures | 97.000 | 134.000 | +37.000 |
| self_bleu_2 | 0.850 | 0.866 | +0.016 |
| ead_distinct_2 | 0.266 | 0.284 | +0.018 |
| schema_property_coverage | 0.407 | 0.426 | +0.019 |

- Split mode: `signature_disjoint`
- Leakage-free split blocks: `True`
