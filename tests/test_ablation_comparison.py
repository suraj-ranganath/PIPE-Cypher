from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipecypher.ablation_comparison import (
    compare_ablation_suites,
    format_ablation_suite_comparison_csv,
    format_ablation_suite_comparison_markdown,
    format_ablation_suite_comparison_tex,
)


def test_compare_ablation_suites_preserves_seed_metadata_and_cell_variation(tmp_path: Path):
    first = _write_summary(
        tmp_path / "suite_a" / "ablation_suite_summary.json",
        run_prefix="suite_a",
        run_seed="",
        accepted=400,
        accept_rate=0.8,
        execution_rate=0.9,
        judge_rate=0.85,
    )
    second = _write_summary(
        tmp_path / "suite_b" / "ablation_suite_summary.json",
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
    assert report["evidence_ready_suite_count"] == 2
    assert report["suites"][1]["run_seed"] == "17"
    assert report["suites"][1]["target_records"] == 800
    assert report["suites"][1]["evidence_ready"] is True
    assert len(report["cells"]) == 1
    cell = report["cells"][0]
    assert cell["graph"] == "finbench"
    assert cell["variant"] == "full_pipe_cypher"
    assert cell["accepted"]["mean"] == 410
    assert cell["accepted"]["min"] == 400
    assert cell["accepted"]["max"] == 420
    assert cell["target_coverage"]["mean"] == pytest.approx((400 / 400 + 420 / 800) / 2)
    assert cell["category_target_share"]["mean"] == 1.0
    assert cell["accept_rate"]["mean"] == pytest.approx(0.82)
    assert cell["gate_rates"]["execution_success"]["mean"] == pytest.approx(0.925)
    assert cell["gate_rates"]["judge_pass"]["mean"] == pytest.approx(0.875)

    markdown = format_ablation_suite_comparison_markdown(report)
    csv_text = format_ablation_suite_comparison_csv(report)
    tex = format_ablation_suite_comparison_tex(report)

    assert "suite_b_seed17" in markdown
    assert "| suite_b_seed17 | 100 | 800 | 17 | yes | yes |" in markdown
    assert "| finbench | Full PIPE-Cypher | 2 | 0.762 | 0.525-1.000 | 0.820" in markdown
    assert "graph,variant,variant_label,suite_count,compared_suite_count" in csv_text
    assert "target_coverage_mean" in csv_text
    assert "full_pipe_cypher" in csv_text
    assert r"\label{tab:ablation_suite_comparison}" in tex
    assert r"\begin{table}[H]" in tex
    assert r"Full PIPE-Cypher & FinBench & 2/2" in tex


def test_compare_ablation_suites_reports_missing_cells_and_missing_evidence(tmp_path: Path):
    first = _write_summary(
        tmp_path / "suite_a" / "ablation_suite_summary.json",
        run_prefix="suite_a",
        run_seed="",
        accepted=400,
        accept_rate=0.8,
        execution_rate=0.9,
        judge_rate=0.85,
    )
    second = _write_summary(
        tmp_path / "suite_b" / "ablation_suite_summary.json",
        run_prefix="suite_b",
        run_seed="",
        accepted=0,
        accept_rate=0.0,
        execution_rate=0.0,
        judge_rate=0.0,
        include_run=False,
        write_evidence=False,
    )

    report = compare_ablation_suites([first, second])

    assert report["evidence_ready_suite_count"] == 1
    assert report["suites"][1]["evidence_ready"] is False
    cell = report["cells"][0]
    assert cell["suite_count"] == 1
    assert cell["compared_suite_count"] == 2
    assert cell["missing_suite_count"] == 1
    assert cell["missing_suite_prefixes"] == ["suite_b"]


def test_tex_comparison_omits_unconstrained_stress_baseline_rows(tmp_path: Path):
    first = _write_summary(
        tmp_path / "suite_a" / "ablation_suite_summary.json",
        run_prefix="suite_a",
        run_seed="",
        accepted=400,
        accept_rate=0.8,
        execution_rate=0.9,
        judge_rate=0.85,
    )
    summary = json.loads(first.read_text(encoding="utf-8"))
    summary["expected_variants"].append("unconstrained_local_llm")
    summary["runs"].append(
        {
            "graph": "finbench",
            "variant": "unconstrained_local_llm",
            "variant_label": "Unconstrained LLM",
            "records": 422,
            "accepted": 200,
            "accept_rate": 0.474,
            "categories_at_target": 2,
            "gate_rates": {
                "read_only": 1.0,
                "syntax_valid": 0.9,
                "schema_valid": 0.8,
                "execution_success": 0.7,
                "judge_pass": 0.6,
            },
        }
    )
    first.write_text(json.dumps(summary), encoding="utf-8")

    report = compare_ablation_suites([first])
    markdown = format_ablation_suite_comparison_markdown(report)
    tex = format_ablation_suite_comparison_tex(report)

    assert "Unconstrained LLM" in markdown
    assert "Unconstrained LLM" not in tex
    assert "attempt-logged stress baseline" in tex


def _write_summary(
    path: Path,
    *,
    run_prefix: str,
    run_seed: str,
    accepted: int,
    accept_rate: float,
    execution_rate: float,
    judge_rate: float,
    include_run: bool = True,
    write_evidence: bool = True,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "target_per_category": 100 if run_seed else 50,
        "category_count": 8,
        "expected_graphs": ["finbench"],
        "expected_variants": ["full_pipe_cypher"],
        "all_runs_finished": include_run,
        "research_status": "paper-ready candidate",
        "metadata": {
            "run_prefix": run_prefix,
            "run_seed": run_seed,
            "generation_model": "Qwen/Qwen3.5-9B",
            "judge_model": "Qwen/Qwen3.5-9B",
            "code_revision": "abc123",
        },
        "runs": []
        if not include_run
        else [
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
    if write_evidence:
        (path.parent / "ablation_suite_audit.json").write_text(
            json.dumps({"paper_ready": True}), encoding="utf-8"
        )
        (path.parent / "collection_manifest.json").write_text(
            json.dumps({"run_prefix": run_prefix}), encoding="utf-8"
        )
    return path
