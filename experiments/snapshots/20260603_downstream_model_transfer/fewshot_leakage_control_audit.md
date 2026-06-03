# Few-Shot Leakage Control Audit

- Exact train/test question overlap: `0` (0.000)
- Train/test query-signature overlap: `295` (0.997)

| Mode | Rows | Selected demos | Signature match rate | High-sim rate | Mean sim | Max sim |
|---|---:|---:|---:|---:|---:|---:|
| ordered | 296 | 1480 | 0.888 | 0.393 | 0.846 | 0.941 |
| scored no-sig | 296 | 1480 | 0.000 | 0.000 | 0.593 | 0.843 |
| random seed 13 | 296 | 1480 | 0.870 | 0.406 | 0.840 | 0.941 |
| random seed 17 | 296 | 1480 | 0.872 | 0.399 | 0.836 | 0.941 |
| random seed 23 | 296 | 1480 | 0.882 | 0.410 | 0.844 | 0.941 |
