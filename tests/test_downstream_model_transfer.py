from __future__ import annotations

import json
from pathlib import Path

from pipecypher.downstream_model_transfer import (
    build_model_transfer_report,
    render_model_transfer_latex,
    render_model_transfer_markdown,
)


def test_model_transfer_report_keeps_incomplete_runs_out_of_latex(tmp_path: Path):
    complete = tmp_path / "20260603_downstream_model_a_zero_fewshot"
    incomplete = tmp_path / "20260603_downstream_model_b_zero_fewshot"
    complete.mkdir()
    incomplete.mkdir()
    _write_summary(complete / "zero_shot_summary.json", execution_accuracy=0.2, schema_valid=0.8)
    _write_summary(complete / "few_shot_summary.json", execution_accuracy=0.9, schema_valid=1.0)
    _write_summary(incomplete / "zero_shot_summary.json", execution_accuracy=0.3, schema_valid=0.7)

    report = build_model_transfer_report(
        [complete, incomplete],
        {
            complete.name: {
                "model": "Model A",
                "model_family": "instruction",
                "tuning": "base",
            },
            incomplete.name: {
                "model": "Model B",
                "model_family": "cypher",
                "tuning": "LoRA",
            },
        },
    )

    assert report["complete_count"] == 1
    assert report["incomplete_count"] == 1
    assert report["best_few_shot_exec_accuracy"]["model"] == "Model A"

    markdown = render_model_transfer_markdown(report)
    assert "Model A" in markdown
    assert "Model B" in markdown
    assert "missing: few_shot_summary.json" in markdown

    latex = render_model_transfer_latex(report)
    assert "Model A" in latex
    assert "Model B" not in latex
    assert "0.200" in latex
    assert "0.900" in latex
    assert "0.700" in latex


def test_model_transfer_report_infers_model_name_from_run_id(tmp_path: Path):
    run_dir = tmp_path / "20260602_downstream_qwen25_coder7b_zero_fewshot"
    run_dir.mkdir()
    _write_summary(run_dir / "zero_shot_summary.json", execution_accuracy=0.1, schema_valid=0.5)
    _write_summary(run_dir / "few_shot_summary.json", execution_accuracy=0.8, schema_valid=1.0)

    report = build_model_transfer_report([run_dir])

    assert report["complete_runs"][0]["model"] == "qwen25-coder7b"


def _write_summary(path: Path, *, execution_accuracy: float, schema_valid: float) -> None:
    summary = {
        "overall": {
            "n": 296,
            "execution_accuracy": execution_accuracy,
            "answer_f1": execution_accuracy,
            "execution_success": max(execution_accuracy, 0.5),
            "parse_valid": 1.0,
            "schema_valid": schema_valid,
            "read_only": 1.0,
        }
    }
    path.write_text(json.dumps(summary), encoding="utf-8")
