# Ablation Suite Paper-Readiness Audit

- Status: `not_paper_ready`
- Paper-ready: false
- Target per category: 100
- Minimum paper target: 50
- Run cells: 2/1
- Expected empty baseline runs: 0

| Check | Pass | Detail |
| --- | --- | --- |
| all_expected_runs_finished | no | missing or incomplete graph/variant cells remain |
| target_is_large_enough | yes | target_per_category=100; required>=50 |
| no_missing_runs | yes | 0 missing run(s) |
| no_incomplete_runs | no | 1 incomplete run(s) |
| expected_cell_count | no | runs=2 expected=1 |
| known_graphs_and_variants | yes | all runs have inferred graph and variant labels |
| required_metadata_present | yes | all required metadata present |
| run_summaries_present | no | runs without summary.txt: 1 |
| non_empty_runs_reach_category_targets | no | underfilled non-empty runs: 2 |
| core_gate_rates_available | yes | all non-empty runs expose read/syntax/schema/execution/judge rates |
