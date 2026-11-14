from __future__ import annotations

import json
from pathlib import Path

from scripts.build_downstream_control_manifest import build_manifest


def test_downstream_control_manifest_filters_clean_run_prefixes(tmp_path: Path):
    evaluation_root = tmp_path / "evaluations"
    snapshot_dir = tmp_path / "snapshot"
    evaluation_root.mkdir()
    snapshot_dir.mkdir()

    old_zero = evaluation_root / "20260603_downstream_old_zero_fewshot"
    clean_zero = evaluation_root / "20260604_clean_downstream_model_a_zero_fewshot"
    old_control = evaluation_root / "20260603_control_model_a_scored_no_signature"
    clean_control = evaluation_root / "20260604_clean_control_model_a_scored_no_signature"
    for path in (old_zero, clean_zero, old_control, clean_control):
        path.mkdir()

    _write_jsonl(clean_zero / "zero_shot_predictions.jsonl", 2)
    _write_jsonl(clean_zero / "zero_shot_evaluation.jsonl", 2)
    (clean_zero / "zero_shot_summary.json").write_text("{}", encoding="utf-8")
    _write_jsonl(clean_control / "few_shot_predictions.jsonl", 2)
    _write_jsonl(clean_control / "few_shot_evaluation.jsonl", 2)
    _write_jsonl(clean_control / "few_shot_selection.jsonl", 2)
    (clean_control / "few_shot_summary.json").write_text("{}", encoding="utf-8")
    (clean_control / "metadata.json").write_text("{}", encoding="utf-8")

    manifest = build_manifest(
        evaluation_root=evaluation_root,
        snapshot_dir=snapshot_dir,
        zero_prefix="20260604_clean_downstream_",
        control_prefix="20260604_clean_control_",
        expected_zero_runs=1,
        expected_control_runs=1,
        rows_per_run=2,
        control_modes_per_model=1,
    )

    assert manifest["observed"]["all_complete"] is True
    assert [run["run_id"] for run in manifest["zero_runs"]] == [clean_zero.name]
    assert [run["run_id"] for run in manifest["control_runs"]] == [clean_control.name]
    assert manifest["filters"]["control_prefix"] == "20260604_clean_control_"


def test_downstream_control_manifest_excludes_known_failed_slug(tmp_path: Path):
    evaluation_root = tmp_path / "evaluations"
    snapshot_dir = tmp_path / "snapshot"
    evaluation_root.mkdir()
    snapshot_dir.mkdir()

    clean_zero = evaluation_root / "20260604_clean_downstream_model_a_zero_fewshot"
    failed_zero = evaluation_root / "20260604_clean_downstream_failed_model_zero_fewshot"
    clean_control = evaluation_root / "20260604_clean_control_model_a_scored_no_signature"
    failed_control = evaluation_root / "20260604_clean_control_failed_model_scored_no_signature"
    for path in (clean_zero, failed_zero, clean_control, failed_control):
        path.mkdir()

    _write_jsonl(clean_zero / "zero_shot_predictions.jsonl", 2)
    _write_jsonl(clean_zero / "zero_shot_evaluation.jsonl", 2)
    (clean_zero / "zero_shot_summary.json").write_text("{}", encoding="utf-8")
    _write_jsonl(clean_control / "few_shot_predictions.jsonl", 2)
    _write_jsonl(clean_control / "few_shot_evaluation.jsonl", 2)
    _write_jsonl(clean_control / "few_shot_selection.jsonl", 2)
    (clean_control / "few_shot_summary.json").write_text("{}", encoding="utf-8")
    (clean_control / "metadata.json").write_text("{}", encoding="utf-8")

    manifest = build_manifest(
        evaluation_root=evaluation_root,
        snapshot_dir=snapshot_dir,
        zero_prefix="20260604_clean_downstream_",
        control_prefix="20260604_clean_control_",
        expected_zero_runs=1,
        expected_control_runs=1,
        rows_per_run=2,
        control_modes_per_model=1,
        exclude_run_substrings=("failed_model",),
    )

    assert manifest["observed"]["all_complete"] is True
    assert [run["run_id"] for run in manifest["zero_runs"]] == [clean_zero.name]
    assert [run["run_id"] for run in manifest["control_runs"]] == [clean_control.name]
    assert manifest["filters"]["exclude_run_substrings"] == ["failed_model"]


def _write_jsonl(path: Path, rows: int) -> None:
    path.write_text(
        "".join(json.dumps({"row": row}) + "\n" for row in range(rows)),
        encoding="utf-8",
    )
