# Ablation Suite Paper-Readiness Audit

- Status: `paper_ready`
- Paper-ready: true
- Target per category: 100
- Minimum paper target: 50
- Run cells: 2/2
- Expected empty baseline runs: 0

| Check | Pass | Detail |
| --- | --- | --- |
| all_expected_runs_finished | yes | all expected graph/variant cells finished |
| target_is_large_enough | yes | target_per_category=100; required>=50 |
| no_missing_runs | yes | 0 missing run(s) |
| no_incomplete_runs | yes | 0 incomplete run(s) |
| expected_cell_count | yes | runs=2 expected=2 |
| known_graphs_and_variants | yes | all runs have inferred graph and variant labels |
| required_metadata_present | yes | all required metadata present |
| run_summaries_present | yes | summary.txt present for all run directories |
| non_empty_runs_reach_category_targets | yes | all non-unconstrained runs reach every category target |
| core_gate_rates_available | yes | all non-empty runs expose read/syntax/schema/execution/judge rates |
