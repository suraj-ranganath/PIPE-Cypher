# Full Qwen3.5-9B Benchmark Snapshot

This directory is a lightweight, tracked snapshot of an ignored full benchmark export. The full JSONL files remain under `artifacts/` locally and on `ds-serv6`; they are not committed because generated artifacts can grow quickly.

- Source export: `artifacts/benchmarks/20260601_live_full_qwen9b`
- Total accepted examples: `3000`
- Canonical export SHA-256: `8bc79a53a06b291a81974d7859d1a02d013c1e7dfc401e447b2897259aeaa47c`
- Representative sample: `16` examples in `sample_examples.json`, selected by stable ID within each graph/category cell.
- Diversity diagnostics: `diversity_report.json`.
- Failure taxonomy: `failure_taxonomy.json`, derived from the ignored full-run raw candidate records on `ds-serv6`. It summarizes `4,777` candidates, `3,000` accepted examples, and `1,777` rejected candidates.
- Downstream uncertainty: `downstream_uncertainty.json` and `downstream_uncertainty.md`, derived from the 296-row full-test evaluation JSONL with 2,000 fixed-seed bootstrap resamples. The appendix figure is `paper_emnlp2026_industry/figures/downstream_uncertainty.pdf`.
- Judge audit packet snapshot: `judge_audit_packet_v2.json`. The ignored source CSV is `artifacts/audits/20260601_full_qwen9b_judge_audit_v2.csv` with SHA-256 `59d1be5a1a946fd2141cf5d5d1b735a82eb9ef18db7018f6cbcb049953b3eeea`, 80 rows, a 40/40 judge accept/reject split, 48 FinBench rows, 32 SNB rows, and 0 completed human labels.
- Judge annotation sheet manifest: `judge_annotation_sheets_manifest.json`. The ignored local sheets are under `artifacts/audits/20260601_full_qwen9b_judge_audit_v2_annotation/` and include two independent annotator CSVs plus an adjudication template; the manifest tracks their hashes without committing raw value-bearing sheets.
- Judge annotation agreement pre-label snapshot: `judge_annotation_agreement_unlabeled.json`, confirming the two independent sheets currently share all 80 row IDs, have no duplicate IDs, and have 0 comparable labeled rows before human annotation.

Use `manifest.json` to verify file sizes, split counts, aggregate statistics, and checksums for the full local export.
