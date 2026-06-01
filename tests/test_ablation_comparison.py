from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipecypher.ablation_comparison import (
    compare_ablation_suites,
    format_ablation_suite_comparison_csv,
    format_ablation_suite_comparison_markdown,
)


def test_compare_ablation_suites_preserves_seed_metadata_and_cell_variation(tmp_path: Path):
    first = _write_summary(
        tmp_path / "suite_a.json",
        run_prefix="suite_a",
        run_seed="",
        accepted=400,
        accept_rate=0.8,
        execution_rate=0.9,
        judge_rate=0.85,
    )
    second = _write_summary(
        tmp_path / "suite_b.json",
        run_prefix="suite_b_seed17",
        run_seed="17",
        accepted=420,
        accept_rate=0.84,
        execution_rate=0.95,
        judge_rate=0.9,
    )

    report = compare_ablation_suites([first, second])

    assert report["suite_count"] == 2
    assert report["complete_suite_count"] == 2
    assert report["suites"][1]["run_seed"] == "17"
    assert len(report["cells"]) == 1
    cell = report["cells"][0]
    assert cell["graph"] == "finbench"
    assert cell["variant"] == "full_pipe_cypher"
    assert cell["accepted"]["mean"] == 410
    assert cell["accepted"]["min"] == 400
    assert cell["accepted"]["max"] == 420
    assert cell["accept_rate"]["mean"] == pytest.approx(0.82)
    assert cell["gate_rates"]["execution_success"]["mean"] == pytest.approx(0.925)
    assert cell["gate_rates"]["judge_pass"]["mean"] == pytest.approx(0.875)

    markdown = format_ablation_suite_comparison_markdown(report)
    csv_text = format_ablation_suite_comparison_csv(report)

    assert "suite_b_seed17" in markdown
    assert "| finbench | Full PIPE-Cypher | 2 | 410.0 | 400-420 | 0.820" in markdown
    assert "graph,variant,variant_label,suite_count" in csv_text
    assert "full_pipe_cypher" in csv_text


def _write_summary(
    path: Path,
    *,
    run_prefix: str,
    run_seed: str,
    accepted: int,
    accept_rate: float,
    execution_rate: float,
    judge_rate: float,
) -> Path:
    summary = {
        "target_per_category": 50,
        "category_count": 8,
        "all_runs_finished": True,
        "research_status": "paper-ready candidate",
        "metadata": {
            "run_prefix": run_prefix,
            "run_seed": run_seed,
            "generation_model": "Qwen/Qwen3.5-9B",
            "judge_model": "Qwen/Qwen3.5-9B",
            "code_revision": "abc123",
        },
        "runs": [
            {
                "graph": "finbench",
                "variant": "full_pipe_cypher",
                "variant_label": "Full PIPE-Cypher",
                "records": 500,
                "accepted": accepted,
                "accept_rate": accept_rate,
                "categories_at_target": 8,
                "gate_rates": {
                    "read_only": 1.0,
                    "syntax_valid": 1.0,
                    "schema_valid": 0.99,
                    "execution_success": execution_rate,
                    "judge_pass": judge_rate,
                },
            }
        ],
    }
    path.write_text(json.dumps(summary), encoding="utf-8")
    return path
