# Few-Shot Leakage Control Audit

- Exact train/test question overlap: `0` (0.000)
- Train/test query-signature overlap: `289` (0.976)

| Mode | Rows | Selected demos | Signature match rate | High-sim rate | Mean sim | Max sim |
|---|---:|---:|---:|---:|---:|---:|
| Ordered | 296 | 1480 | 0.866 | 0.389 | 0.825 | 0.941 |
| No-signature | 296 | 1480 | 0.000 | 0.000 | 0.585 | 0.857 |
| Random | 296 | 1480 | 0.854 | 0.409 | 0.824 | 0.941 |
