# PIPE-Cypher Reproducibility Notes

This bundle contains the code and paper artifacts needed to inspect
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
- `paper_arxiv/`: arXiv source, figures, tables, and PDF build outputs.
- `knowledge_base/`: sanitized citation, literature, deployment, and
  review-response notes.

Raw generation records and benchmark JSONL exports may contain public graph
values or organization-specific values in a private deployment. Share those
only after running the redaction audit and checking the generated manifest.

Before submission, run `python scripts/audit_paper_evidence_provenance.py`
from the repository root. It checks that manuscript-facing sources, the clean
benchmark export, the Qwen3.5-9B-only evidence manifest, and the downstream
control manifest agree and do not reference stale or diagnostic evidence.
