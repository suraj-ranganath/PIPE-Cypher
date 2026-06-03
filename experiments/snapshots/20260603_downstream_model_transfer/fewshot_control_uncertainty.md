# Few-Shot Control Uncertainty

Method: model-level paired bootstrap over downstream checkpoints with 10,000 resamples and 95% percentile intervals.

Zero-shot mean execution accuracy: 0.139

| Control | Mean acc. | Delta vs zero | Delta CI | Improved models |
|---|---:|---:|---:|---:|
| Ordered same-category | 0.380 | 0.241 | [0.014, 0.489] | 5/12 |
| Scored no-signature | 0.245 | 0.106 | [-0.041, 0.266] | 5/12 |
| Random same-category mean | 0.378 | 0.239 | [0.013, 0.477] | 5/12 |
