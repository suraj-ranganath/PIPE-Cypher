# Few-Shot Control Uncertainty

Method: model-level paired bootstrap over downstream checkpoints with 10,000 resamples and 95% percentile intervals.

Zero-shot mean execution accuracy: 0.036

| Control | Mean acc. | Delta vs zero | Delta CI | Improved models |
|---|---:|---:|---:|---:|
| Ordered same-category | 0.269 | 0.233 | [0.000, 0.481] | 3/11 |
| Scored no-signature | 0.200 | 0.163 | [0.000, 0.335] | 3/11 |
| Random same-category mean | 0.267 | 0.231 | [0.000, 0.464] | 3/11 |
