# Review Response Matrix

Date: June 4, 2026.

This matrix tracks the current response to the latest submission-readiness review.
It is intentionally evidence-oriented: claims are paper-ready only when they map
to code, tests, manifests, tables, figures, or explicitly bounded limitations.

| Review concern | Response | Evidence status |
| --- | --- | --- |
| Missing paper tables and absent `tbl-*.html` artifacts | The ACL PDF now embeds LaTeX tables directly, and `scripts/verify_submission_package.py` checks that all `\input{}` and figure references resolve. If an HTML/preprint package is produced later, it must either include generated `tbl-*.html` files or avoid references to them. | Implemented verifier; final package build still pending after clean export refresh. |
| Missing code directory in submitted package | `scripts/build_submission_bundle.py` builds an anonymous reproducibility bundle containing the Python package, scripts, configs, tests, paper source, figures, tables, and sanitized evidence notes with checksums. | Implemented bundle builder; final bundle must be regenerated after final paper build. |
| Novelty over Auto-Cypher, SyntheT2C, Mind the Query, CypherBench, and Text2Cypher-2024 is under-specified | The paper now states that execution filtering and template filling are shared prior mechanisms. PIPE-Cypher's delta is outcome-aware reverse grounding, deterministic Cypher governance, read-only deployment, local judge calibration, configurable privacy/value policy, refreshable exports, and evidence ledgers. | Main paper related work revised; Table `prior_mechanism_comparison` added. |
| LLM judge calibration is limited | The paper keeps the completed 80-row, single-audit-sheet calibration as the only reported human evidence. A larger audit packet may be generated, but it is not paper evidence until labels return. | Existing judge CI table remains; audit-packet schema now includes naturalness and ambiguity fields. |
| Few-shot example-bank gains are confounded by query-signature overlap | The main paper now treats `scored_no_signature` as the primary few-shot generalization result. Ordered/random same-category banks are described as operational upper-bound example-bank conditions. | Main paper RQ3 revised; leakage-control tables remain in appendix. |
| Arbitrary enterprise schema claim is overbroad | Claims are narrowed to "designed for enterprise onboarding; validated on three public proxy graphs." ICIJ remains third-graph evidence, not proprietary-tenant proof. | Main paper, Industry Use, and Limitations revised. |
| Ablations saturate target coverage and do not isolate optional components | RQ2 is reframed as reliability of the reverse-grounded governance core. Gate-rate, failure-taxonomy, and first-blocking-gate audits are the component evidence. | Gate-impact audit implemented and added to appendix. |
| Privacy/redaction was described but not evaluated | Added exact-match redaction audit over entity bindings, quoted Cypher literals, reverse-grounding literals, and string-valued result samples. Numeric entity values in Cypher are redacted when numeric redaction is enabled. | Redaction audit code, canary tests, and appendix table implemented; final audit should be rerendered on clean export. |
| Clean generation model provenance | Current full-export evidence must be refreshed so paper-facing generation/judge artifacts are Qwen3.5-9B-only. Mixed historical top-up records are internal operations history and must not drive final paper tables. | Remote clean recovery queued; final export/rerender pending. |
