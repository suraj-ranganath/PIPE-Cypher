# Downstream Evaluation Uncertainty

Method: nonparametric bootstrap with 2,000 resamples and 95% percentile intervals.

| Metric | N | Point | CI lower | CI upper | SE |
| --- | ---: | ---: | ---: | ---: | ---: |
| parse_valid | 296 | 0.963 | 0.939 | 0.983 | 0.011 |
| schema_valid | 296 | 0.916 | 0.885 | 0.946 | 0.016 |
| execution_success | 296 | 0.611 | 0.554 | 0.666 | 0.029 |
| execution_accuracy | 296 | 0.189 | 0.145 | 0.233 | 0.022 |
| answer_f1 | 296 | 0.189 | 0.145 | 0.233 | 0.023 |

## Grouped Intervals

### graph_profile

| Group | Metric | N | Point | CI lower | CI upper |
| --- | --- | ---: | ---: | ---: | ---: |
| finbench | parse_valid | 200 | 1.000 | 1.000 | 1.000 |
| finbench | schema_valid | 200 | 1.000 | 1.000 | 1.000 |
| finbench | execution_success | 200 | 0.660 | 0.595 | 0.730 |
| finbench | execution_accuracy | 200 | 0.160 | 0.110 | 0.215 |
| finbench | answer_f1 | 200 | 0.160 | 0.115 | 0.210 |
| snb | parse_valid | 96 | 0.885 | 0.823 | 0.948 |
| snb | schema_valid | 96 | 0.740 | 0.646 | 0.823 |
| snb | execution_success | 96 | 0.510 | 0.406 | 0.615 |
| snb | execution_accuracy | 96 | 0.250 | 0.167 | 0.333 |
| snb | answer_f1 | 96 | 0.250 | 0.167 | 0.344 |

### category

| Group | Metric | N | Point | CI lower | CI upper |
| --- | --- | ---: | ---: | ---: | ---: |
| boolean_existence | parse_valid | 37 | 0.703 | 0.541 | 0.838 |
| boolean_existence | schema_valid | 37 | 1.000 | 1.000 | 1.000 |
| boolean_existence | execution_success | 37 | 0.189 | 0.081 | 0.324 |
| boolean_existence | execution_accuracy | 37 | 0.189 | 0.081 | 0.324 |
| boolean_existence | answer_f1 | 37 | 0.189 | 0.081 | 0.324 |
| complex_aggregation | parse_valid | 37 | 1.000 | 1.000 | 1.000 |
| complex_aggregation | schema_valid | 37 | 0.676 | 0.541 | 0.811 |
| complex_aggregation | execution_success | 37 | 0.000 | 0.000 | 0.000 |
| complex_aggregation | execution_accuracy | 37 | 0.000 | 0.000 | 0.000 |
| complex_aggregation | answer_f1 | 37 | 0.000 | 0.000 | 0.000 |
| complex_retrieval | parse_valid | 37 | 1.000 | 1.000 | 1.000 |
| complex_retrieval | schema_valid | 37 | 0.676 | 0.514 | 0.811 |
| complex_retrieval | execution_success | 37 | 0.676 | 0.514 | 0.811 |
| complex_retrieval | execution_accuracy | 37 | 0.000 | 0.000 | 0.000 |
| complex_retrieval | answer_f1 | 37 | 0.000 | 0.000 | 0.000 |
| negation_difference | parse_valid | 37 | 1.000 | 1.000 | 1.000 |
| negation_difference | schema_valid | 37 | 1.000 | 1.000 | 1.000 |
| negation_difference | execution_success | 37 | 0.973 | 0.919 | 1.000 |
| negation_difference | execution_accuracy | 37 | 0.000 | 0.000 | 0.000 |
| negation_difference | answer_f1 | 37 | 0.000 | 0.000 | 0.000 |
| path_temporal | parse_valid | 37 | 1.000 | 1.000 | 1.000 |
| path_temporal | schema_valid | 37 | 1.000 | 1.000 | 1.000 |
| path_temporal | execution_success | 37 | 0.757 | 0.622 | 0.892 |
| path_temporal | execution_accuracy | 37 | 0.000 | 0.000 | 0.000 |
| path_temporal | answer_f1 | 37 | 0.000 | 0.000 | 0.000 |
| ranking_topk | parse_valid | 37 | 1.000 | 1.000 | 1.000 |
| ranking_topk | schema_valid | 37 | 0.973 | 0.919 | 1.000 |
| ranking_topk | execution_success | 37 | 0.297 | 0.162 | 0.459 |
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
| easy | parse_valid | 151 | 1.000 | 1.000 | 1.000 |
| easy | schema_valid | 151 | 0.921 | 0.874 | 0.960 |
| easy | execution_success | 151 | 0.815 | 0.748 | 0.874 |
| easy | execution_accuracy | 151 | 0.371 | 0.298 | 0.450 |
| easy | answer_f1 | 151 | 0.371 | 0.291 | 0.450 |
| medium | parse_valid | 145 | 0.924 | 0.883 | 0.966 |
| medium | schema_valid | 145 | 0.910 | 0.862 | 0.952 |
| medium | execution_success | 145 | 0.400 | 0.317 | 0.476 |
| medium | execution_accuracy | 145 | 0.000 | 0.000 | 0.000 |
| medium | answer_f1 | 145 | 0.000 | 0.000 | 0.000 |
