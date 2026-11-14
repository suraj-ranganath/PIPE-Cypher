from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipecypher.downstream_model_transfer import (
    build_fewshot_control_uncertainty_report,
    build_fewshot_control_report,
    build_model_transfer_report,
    render_fewshot_control_uncertainty_latex,
    render_fewshot_control_uncertainty_markdown,
    render_fewshot_control_latex,
    render_fewshot_control_markdown,
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
    (complete / "metadata.json").write_text(
        json.dumps({"few_shot_mode": "scored_no_signature", "few_shot_seed": 17}),
        encoding="utf-8",
    )
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
    assert "scored_no_signature" in markdown
    assert "Model B" in markdown
    assert "missing: few_shot_summary.json" in markdown

    latex = render_model_transfer_latex(report)
    assert "Model A" in latex
    assert "Model B" not in latex
    assert "0.200" in latex
    assert "0.900" in latex
    assert "scored no-sig" in latex
    assert "296" in latex


def test_model_transfer_report_infers_model_name_from_run_id(tmp_path: Path):
    run_dir = tmp_path / "20260602_downstream_qwen25_coder7b_zero_fewshot"
    run_dir.mkdir()
    _write_summary(run_dir / "zero_shot_summary.json", execution_accuracy=0.1, schema_valid=0.5)
    _write_summary(run_dir / "few_shot_summary.json", execution_accuracy=0.8, schema_valid=1.0)

    report = build_model_transfer_report([run_dir])

    assert report["complete_runs"][0]["model"] == "qwen25-coder7b"


def test_fewshot_control_report_pairs_zero_and_control_runs(tmp_path: Path):
    zero = tmp_path / "20260602_downstream_qwen35_9b_zero_fewshot"
    zero.mkdir()
    _write_summary(zero / "zero_shot_summary.json", execution_accuracy=0.2, schema_valid=0.8)
    control_dirs = []
    for suffix, value in [
        ("ordered_logged", 0.8),
        ("scored_no_signature", 0.7),
        ("random_seed13", 0.6),
        ("random_seed17", 0.9),
        ("random_seed23", 0.3),
    ]:
        path = tmp_path / f"20260603_control_qwen35_9b_{suffix}"
        path.mkdir()
        _write_summary(path / "few_shot_summary.json", execution_accuracy=value, schema_valid=1.0)
        control_dirs.append(path)

    report = build_fewshot_control_report(
        zero_shot_dirs=[zero],
        control_dirs=control_dirs,
        metadata={
            zero.name: {
                "model": "Qwen3.5-9B",
                "model_family": "Qwen",
                "tuning": "general",
            }
        },
    )

    assert report["complete_model_count"] == 1
    model = report["models"][0]
    assert model["model"] == "Qwen3.5-9B"
    assert model["controls"]["ordered"]["execution_accuracy"] == 0.8
    assert model["random"]["mean"]["execution_accuracy"] == 0.6
    assert model["best_control"]["mode"] == "ordered"
    assert report["aggregate"]["ordered_improved_models"] == 1

    markdown = render_fewshot_control_markdown(report)
    assert "Scored no-sig" in markdown
    assert "Qwen3.5-9B" in markdown
    latex = render_fewshot_control_latex(report)
    assert r"\label{tab:downstream_fewshot_controls}" in latex
    assert "Qwen3.5-9B" in latex


def test_fewshot_control_report_accepts_clean_run_tag_prefix(tmp_path: Path):
    zero = tmp_path / "20260604_clean_downstream_qwen35_9b_zero_fewshot"
    zero.mkdir()
    _write_summary(zero / "zero_shot_summary.json", execution_accuracy=0.2, schema_valid=0.8)

    controls = []
    for suffix, value in [
        ("ordered_logged", 0.4),
        ("scored_no_signature", 0.5),
        ("random_seed13", 0.3),
        ("random_seed17", 0.6),
        ("random_seed23", 0.6),
    ]:
        path = tmp_path / f"20260604_clean_control_qwen35_9b_{suffix}"
        path.mkdir()
        _write_summary(path / "few_shot_summary.json", execution_accuracy=value, schema_valid=1.0)
        controls.append(path)

    report = build_fewshot_control_report(zero_shot_dirs=[zero], control_dirs=controls)

    assert report["complete_model_count"] == 1
    model = report["models"][0]
    assert model["controls"]["scored_no_signature"]["execution_accuracy"] == 0.5
    assert model["random"]["mean"]["execution_accuracy"] == pytest.approx(0.5)


def test_fewshot_control_report_uses_zero_run_fewshot_as_ordered_control(tmp_path: Path):
    zero = tmp_path / "20260604_clean_downstream_qwen35_9b_zero_fewshot"
    zero.mkdir()
    _write_summary(zero / "zero_shot_summary.json", execution_accuracy=0.2, schema_valid=0.8)
    _write_summary(zero / "few_shot_summary.json", execution_accuracy=0.9, schema_valid=1.0)

    controls = []
    for suffix, value in [
        ("scored_no_signature", 0.5),
        ("random_seed13", 0.3),
        ("random_seed17", 0.6),
        ("random_seed23", 0.6),
    ]:
        path = tmp_path / f"20260604_clean_control_qwen35_9b_{suffix}"
        path.mkdir()
        _write_summary(path / "few_shot_summary.json", execution_accuracy=value, schema_valid=1.0)
        controls.append(path)

    report = build_fewshot_control_report(zero_shot_dirs=[zero], control_dirs=controls)

    assert report["complete_model_count"] == 1
    model = report["models"][0]
    assert model["controls"]["ordered"]["run_id"] == zero.name
    assert model["controls"]["ordered"]["execution_accuracy"] == 0.9


def test_zero_row_summaries_are_incomplete(tmp_path: Path):
    run_dir = tmp_path / "20260604_clean_downstream_stable_zero_fewshot"
    run_dir.mkdir()
    _write_summary(run_dir / "zero_shot_summary.json", execution_accuracy=0.0, schema_valid=0.0, n=0)
    _write_summary(run_dir / "few_shot_summary.json", execution_accuracy=0.0, schema_valid=0.0, n=0)

    report = build_model_transfer_report([run_dir])

    assert report["complete_count"] == 0
    assert "no evaluated rows" in " ".join(report["incomplete_runs"][0]["missing"])


def test_fewshot_control_report_uses_control_metadata_when_zero_metadata_missing(tmp_path: Path):
    zero = tmp_path / "20260602_downstream_neo4j_gemma2_text2cypher_lora_zero_fewshot"
    zero.mkdir()
    _write_summary(zero / "zero_shot_summary.json", execution_accuracy=0.2, schema_valid=0.8)
    control_dirs = []
    for suffix, value in [
        ("ordered_logged", 0.9),
        ("scored_no_signature", 0.7),
        ("random_seed13", 0.6),
        ("random_seed17", 0.6),
        ("random_seed23", 0.6),
    ]:
        path = tmp_path / f"20260603_control_neo4j_gemma2_text2cypher_lora_{suffix}"
        path.mkdir()
        _write_summary(path / "few_shot_summary.json", execution_accuracy=value, schema_valid=1.0)
        if suffix == "ordered_logged":
            (path / "metadata.json").write_text(
                json.dumps({"model": "neo4j/Gemma-2-9B Text2Cypher LoRA"}),
                encoding="utf-8",
            )
        control_dirs.append(path)

    report = build_fewshot_control_report(
        zero_shot_dirs=[zero],
        control_dirs=control_dirs,
    )

    model = report["models"][0]
    assert model["model"] == "neo4j/Gemma-2-9B Text2Cypher LoRA"
    assert model["model_family"] == "Gemma"
    assert model["tuning"] == "Text2Cypher LoRA"


def test_fewshot_control_uncertainty_reports_model_level_deltas(tmp_path: Path):
    zero_a = tmp_path / "20260602_downstream_model_a_zero_fewshot"
    zero_b = tmp_path / "20260602_downstream_model_b_zero_fewshot"
    zero_a.mkdir()
    zero_b.mkdir()
    _write_summary(zero_a / "zero_shot_summary.json", execution_accuracy=0.2, schema_valid=0.8)
    _write_summary(zero_b / "zero_shot_summary.json", execution_accuracy=0.4, schema_valid=0.9)

    control_dirs = []
    for slug, values in {
        "model_a": {
            "ordered_logged": 0.8,
            "scored_no_signature": 0.6,
            "random_seed13": 0.7,
            "random_seed17": 0.9,
            "random_seed23": 0.8,
        },
        "model_b": {
            "ordered_logged": 0.3,
            "scored_no_signature": 0.2,
            "random_seed13": 0.3,
            "random_seed17": 0.3,
            "random_seed23": 0.3,
        },
    }.items():
        for suffix, value in values.items():
            path = tmp_path / f"20260603_control_{slug}_{suffix}"
            path.mkdir()
            _write_summary(path / "few_shot_summary.json", execution_accuracy=value, schema_valid=1.0)
            control_dirs.append(path)

    report = build_fewshot_control_report(
        zero_shot_dirs=[zero_a, zero_b],
        control_dirs=control_dirs,
        metadata={
            zero_a.name: {"model": "model_a", "tuning": "base"},
            zero_b.name: {"model": "model_b", "tuning": "base"},
        },
    )
    uncertainty = build_fewshot_control_uncertainty_report(
        report,
        iterations=100,
        seed=7,
    )

    assert uncertainty["method"] == "model_level_paired_bootstrap"
    assert uncertainty["zero_shot_mean_accuracy"] == pytest.approx(0.3)
    ordered = uncertainty["rows"][0]
    assert ordered["mean_accuracy"] == pytest.approx(0.55)
    assert ordered["mean_delta"] == pytest.approx(0.25)
    assert ordered["improved_models"] == 1

    markdown = render_fewshot_control_uncertainty_markdown(uncertainty)
    assert "model-level paired bootstrap" in markdown
    latex = render_fewshot_control_uncertainty_latex(uncertainty)
    assert r"\label{tab:downstream_fewshot_control_uncertainty}" in latex
    assert "Models improved" in latex


def _write_summary(
    path: Path,
    *,
    execution_accuracy: float,
    schema_valid: float,
    n: int = 296,
) -> None:
    summary = {
        "overall": {
            "n": n,
            "execution_accuracy": execution_accuracy,
            "answer_f1": execution_accuracy,
            "execution_success": max(execution_accuracy, 0.5),
            "parse_valid": 1.0,
            "schema_valid": schema_valid,
            "read_only": 1.0,
        }
    }
    path.write_text(json.dumps(summary), encoding="utf-8")
