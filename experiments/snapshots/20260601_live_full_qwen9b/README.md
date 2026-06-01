# Full Qwen3.5-9B Benchmark Snapshot

This directory is a lightweight, tracked snapshot of an ignored full benchmark export. The full JSONL files remain under `artifacts/` locally and on `ds-serv6`; they are not committed because generated artifacts can grow quickly.

- Source export: `artifacts/benchmarks/20260601_live_full_qwen9b`
- Total accepted examples: `3000`
- Canonical export SHA-256: `8bc79a53a06b291a81974d7859d1a02d013c1e7dfc401e447b2897259aeaa47c`
- Representative sample: `16` examples in `sample_examples.json`, selected by stable ID within each graph/category cell.
- Diversity diagnostics: `diversity_report.json`.
- Failure taxonomy: `failure_taxonomy.json`, derived from the ignored full-run raw candidate records on `ds-serv6`. It summarizes `4,777` candidates, `3,000` accepted examples, and `1,777` rejected candidates.

Use `manifest.json` to verify file sizes, split counts, aggregate statistics, and checksums for the full local export.
