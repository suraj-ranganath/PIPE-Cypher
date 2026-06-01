# Downstream Evaluation Uncertainty

Method: nonparametric bootstrap with 2,000 resamples and 95% percentile intervals.

| Metric | N | Point | CI lower | CI upper | SE |
| --- | ---: | ---: | ---: | ---: | ---: |
| parse_valid | 296 | 0.959 | 0.936 | 0.980 | 0.012 |
| schema_valid | 296 | 0.905 | 0.872 | 0.939 | 0.017 |
| execution_success | 296 | 0.622 | 0.564 | 0.676 | 0.028 |
| execution_accuracy | 296 | 0.189 | 0.145 | 0.233 | 0.022 |
| answer_f1 | 296 | 0.189 | 0.149 | 0.236 | 0.023 |

## Grouped Intervals

### graph_profile

| Group | Metric | N | Point | CI lower | CI upper |
| --- | --- | ---: | ---: | ---: | ---: |
| finbench | parse_valid | 200 | 1.000 | 1.000 | 1.000 |
| finbench | schema_valid | 200 | 0.990 | 0.975 | 1.000 |
| finbench | execution_success | 200 | 0.655 | 0.590 | 0.725 |
| finbench | execution_accuracy | 200 | 0.160 | 0.110 | 0.215 |
| finbench | answer_f1 | 200 | 0.160 | 0.110 | 0.210 |
| snb | parse_valid | 96 | 0.875 | 0.802 | 0.938 |
| snb | schema_valid | 96 | 0.729 | 0.635 | 0.812 |
| snb | execution_success | 96 | 0.552 | 0.458 | 0.646 |
| snb | execution_accuracy | 96 | 0.250 | 0.167 | 0.344 |
| snb | answer_f1 | 96 | 0.250 | 0.167 | 0.344 |

### category

| Group | Metric | N | Point | CI lower | CI upper |
| --- | --- | ---: | ---: | ---: | ---: |
| boolean_existence | parse_valid | 37 | 0.676 | 0.514 | 0.811 |
| boolean_existence | schema_valid | 37 | 1.000 | 1.000 | 1.000 |
| boolean_existence | execution_success | 37 | 0.189 | 0.081 | 0.324 |
| boolean_existence | execution_accuracy | 37 | 0.189 | 0.054 | 0.324 |
| boolean_existence | answer_f1 | 37 | 0.189 | 0.081 | 0.324 |
| complex_aggregation | parse_valid | 37 | 1.000 | 1.000 | 1.000 |
| complex_aggregation | schema_valid | 37 | 0.649 | 0.486 | 0.784 |
| complex_aggregation | execution_success | 37 | 0.000 | 0.000 | 0.000 |
| complex_aggregation | execution_accuracy | 37 | 0.000 | 0.000 | 0.000 |
| complex_aggregation | answer_f1 | 37 | 0.000 | 0.000 | 0.000 |
| complex_retrieval | parse_valid | 37 | 1.000 | 1.000 | 1.000 |
| complex_retrieval | schema_valid | 37 | 0.703 | 0.541 | 0.838 |
| complex_retrieval | execution_success | 37 | 0.703 | 0.541 | 0.838 |
| complex_retrieval | execution_accuracy | 37 | 0.000 | 0.000 | 0.000 |
| complex_retrieval | answer_f1 | 37 | 0.000 | 0.000 | 0.000 |
| negation_difference | parse_valid | 37 | 1.000 | 1.000 | 1.000 |
| negation_difference | schema_valid | 37 | 0.892 | 0.784 | 0.973 |
| negation_difference | execution_success | 37 | 0.892 | 0.784 | 0.973 |
| negation_difference | execution_accuracy | 37 | 0.000 | 0.000 | 0.000 |
| negation_difference | answer_f1 | 37 | 0.000 | 0.000 | 0.000 |
| path_temporal | parse_valid | 37 | 1.000 | 1.000 | 1.000 |
| path_temporal | schema_valid | 37 | 1.000 | 1.000 | 1.000 |
| path_temporal | execution_success | 37 | 0.865 | 0.757 | 0.973 |
| path_temporal | execution_accuracy | 37 | 0.000 | 0.000 | 0.000 |
| path_temporal | answer_f1 | 37 | 0.000 | 0.000 | 0.000 |
| ranking_topk | parse_valid | 37 | 1.000 | 1.000 | 1.000 |
| ranking_topk | schema_valid | 37 | 1.000 | 1.000 | 1.000 |
| ranking_topk | execution_success | 37 | 0.324 | 0.189 | 0.486 |
| ranking_topk | execution_accuracy | 37 | 0.000 | 0.000 | 0.000 |
| ranking_topk | answer_f1 | 37 | 0.000 | 0.000 | 0.000 |
| simple_aggregation | parse_valid | 37 | 1.000 | 1.000 | 1.000 |
| simple_aggregation | schema_valid | 37 | 1.000 | 1.000 | 1.000 |
| simple_aggregation | execution_success | 37 | 1.000 | 1.000 | 1.000 |
| simple_aggregation | execution_accuracy | 37 | 1.000 | 1.000 | 1.000 |
| simple_aggregation | answer_f1 | 37 | 1.000 | 1.000 | 1.000 |
| simple_retrieval | parse_valid | 37 | 1.000 | 1.000 | 1.000 |
| simple_retrieval | schema_valid | 37 | 1.000 | 1.000 | 1.000 |
| simple_retrieval | execution_success | 37 | 1.000 | 1.000 | 1.000 |
| simple_retrieval | execution_accuracy | 37 | 0.324 | 0.189 | 0.486 |
| simple_retrieval | answer_f1 | 37 | 0.324 | 0.189 | 0.486 |

### difficulty

| Group | Metric | N | Point | CI lower | CI upper |
| --- | --- | ---: | ---: | ---: | ---: |
| easy | parse_valid | 147 | 1.000 | 1.000 | 1.000 |
| easy | schema_valid | 147 | 0.925 | 0.878 | 0.966 |
| easy | execution_success | 147 | 0.850 | 0.796 | 0.905 |
| easy | execution_accuracy | 147 | 0.381 | 0.306 | 0.463 |
| easy | answer_f1 | 147 | 0.381 | 0.306 | 0.463 |
| medium | parse_valid | 149 | 0.919 | 0.872 | 0.960 |
| medium | schema_valid | 149 | 0.886 | 0.832 | 0.933 |
| medium | execution_success | 149 | 0.396 | 0.322 | 0.477 |
| medium | execution_accuracy | 149 | 0.000 | 0.000 | 0.000 |
| medium | answer_f1 | 149 | 0.000 | 0.000 | 0.000 |
