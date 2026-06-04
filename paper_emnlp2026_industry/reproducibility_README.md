# PIPE-Cypher Reproducibility Bundle

This anonymous bundle contains the code and paper artifacts needed to inspect
PIPE-Cypher without private machine paths or remote-host operations notes.

Contents:

- `pipecypher/`: Python package for schema inspection, Cypher validation,
  generation records, judge calibration, diversity metrics, privacy redaction,
  and reporting utilities.
- `scripts/`: reproducibility and reporting scripts that do not contain
  private host-specific paths.
- `configs/`: public-proxy graph and enterprise-template configuration files.
- `tests/`: deterministic unit tests for validators, privacy, diversity,
  reporting, and package checks.
- `paper_emnlp2026_industry/`: ACL-style source, figures, tables, and PDF
  build outputs.
- `knowledge_base/`: sanitized citation, literature, deployment, and
  review-response notes.

Raw generation records and benchmark JSONL exports may contain public graph
values or organization-specific values in a private deployment. Share those
only after running the redaction audit and checking the generated manifest.
