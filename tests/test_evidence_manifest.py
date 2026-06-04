import json
from pathlib import Path

from scripts.build_evidence_manifest import _flatten, build_evidence_manifest


def test_evidence_manifest_requires_clean_models_and_present_artifacts(tmp_path: Path):
    records = tmp_path / "records.jsonl"
    records.write_text(
        json.dumps({"model": "Qwen/Qwen3.5-9B"}) + "\n",
        encoding="utf-8",
    )
    table = tmp_path / "tables_result.tex"
    table.write_text("safe", encoding="utf-8")

    manifest = build_evidence_manifest(
        name="unit",
        records=[records],
        artifacts=[table],
        approved_models={"Qwen/Qwen3.5-9B"},
        notes=[],
    )

    assert manifest["paper_ready"] is True
    assert manifest["model_provenance"]["records"] == 1
    assert manifest["artifact_files"][0]["path"].endswith("tables_result.tex")


def test_evidence_manifest_blocks_disallowed_models(tmp_path: Path):
    records = tmp_path / "records.jsonl"
    records.write_text(
        json.dumps({"model": "Qwen/Qwen3.5-35B-A3B"}) + "\n",
        encoding="utf-8",
    )

    manifest = build_evidence_manifest(
        name="unit",
        records=[records],
        artifacts=[],
        approved_models={"Qwen/Qwen3.5-9B"},
        notes=[],
    )

    assert manifest["paper_ready"] is False
    assert manifest["model_provenance"]["disallowed_model_counts"] == {
        "Qwen/Qwen3.5-35B-A3B": 1
    }


def test_evidence_manifest_flattens_repeated_records_arguments():
    assert _flatten([["a", "b"], ["c"]]) == ["a", "b", "c"]
