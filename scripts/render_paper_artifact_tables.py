#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.paper_tables import (
    render_benchmark_export_table,
    render_category_crosswalk_table,
    render_downstream_error_table,
    render_downstream_table,
    render_effort_automation_table,
    render_full_artifact_distribution_table,
    render_graph_statistics_table,
    render_icij_onboarding_table,
    render_prompt_refinement_table,
    render_validator_cascade_table,
)
from pipecypher.schema import load_schema


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render LaTeX paper tables from exported benchmark/evaluation artifacts."
    )
    parser.add_argument(
        "--benchmark-dir",
        default="artifacts/benchmarks/20260601_live_full_qwen9b",
    )
    parser.add_argument(
        "--evaluation-summary",
        default="artifacts/evaluations/20260601_full_qwen9b_test_summary.json",
    )
    parser.add_argument(
        "--downstream-errors",
        default="experiments/snapshots/20260601_live_full_qwen9b/downstream_error_report.json",
    )
    parser.add_argument(
        "--failure-taxonomy",
        default="experiments/snapshots/20260601_live_full_qwen9b/failure_taxonomy.json",
    )
    parser.add_argument(
        "--icij-onboarding",
        default="experiments/snapshots/20260602_icij_target100_schema_templates_v3/onboarding_summary.json",
    )
    parser.add_argument("--paper-dir", default="paper_emnlp2026_industry")
    args = parser.parse_args()

    benchmark_dir = Path(args.benchmark_dir)
    paper_dir = Path(args.paper_dir)
    stats = _read_json(benchmark_dir / "stats.json")
    manifest = _read_json(benchmark_dir / "manifest.json")
    evaluation = _read_json(args.evaluation_summary)
    downstream_errors = _read_json(args.downstream_errors)
    failure_taxonomy = _read_json(args.failure_taxonomy)
    icij_onboarding = _read_json(args.icij_onboarding)

    outputs = {
        "tables_benchmark_export.tex": render_benchmark_export_table(stats, manifest),
        "tables_full_artifact_distribution.tex": render_full_artifact_distribution_table(stats),
        "tables_downstream_evaluation.tex": render_downstream_table(evaluation),
        "tables_downstream_error_taxonomy.tex": render_downstream_error_table(
            downstream_errors
        ),
        "tables_graph_statistics.tex": render_graph_statistics_table(_graph_statistics_rows()),
        "tables_icij_onboarding.tex": render_icij_onboarding_table(icij_onboarding),
        "tables_category_crosswalk.tex": render_category_crosswalk_table(),
        "tables_validator_cascade.tex": render_validator_cascade_table(stats, failure_taxonomy),
        "tables_prompt_refinement.tex": render_prompt_refinement_table(),
        "tables_effort_automation.tex": render_effort_automation_table(),
    }
    paper_dir.mkdir(parents=True, exist_ok=True)
    for name, text in outputs.items():
        path = paper_dir / name
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path}")


def _read_json(path: str | Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _graph_statistics_rows() -> list[dict[str, object]]:
    rows = []
    for item in [
        ("FinBench", "configs/schema_finbench.json", 10006, 57622, "reported"),
        ("SNB", "configs/schema_snb.json", 34735, 70842, "reported"),
        (
            "ICIJ Offshore Leaks",
            "configs/schema_icij_offshoreleaks_live.json",
            2016523,
            3339267,
            "onboarding audit",
        ),
    ]:
        name, schema_path, nodes, relationships, status = item
        schema = load_schema(schema_path)
        rows.append(
            {
                "graph": name,
                "nodes": nodes,
                "relationships": relationships,
                "labels": len(schema.labels),
                "relationship_types": len(schema.relationship_types),
                "status": status,
            }
        )
    return rows


if __name__ == "__main__":
    main()
