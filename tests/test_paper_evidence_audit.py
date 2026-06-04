from __future__ import annotations

import json
from pathlib import Path

from pipecypher.paper_evidence_audit import run_paper_evidence_audit


def test_paper_evidence_audit_passes_clean_fixture(tmp_path: Path):
    _write_clean_text_surfaces(tmp_path)
    benchmark = _write_benchmark(tmp_path, total=2, splits={"train": 1, "dev": 1, "test": 0})
    evidence = _write_evidence_manifest(tmp_path, model="Qwen/Qwen3.5-9B", records=3)
    downstream = _write_downstream_manifest(tmp_path, zero_runs=1, control_runs=2, rows=2)

    report = run_paper_evidence_audit(
        root=tmp_path,
        benchmark_dir=benchmark,
        evidence_manifest=evidence,
        downstream_manifest=downstream,
        required_paths=[],
        expected_total=2,
        expected_splits={"train": 1, "dev": 1, "test": 0},
        expected_by_graph={"finbench": 2},
        expected_category_count=None,
        expected_model_records=3,
        expected_downstream_zero_runs=1,
        expected_downstream_control_runs=2,
        expected_downstream_rows=2,
    )

    assert report["pass"] is True
    assert report["issues"] == []


def test_paper_evidence_audit_flags_stale_paper_claims(tmp_path: Path):
    _write_clean_text_surfaces(tmp_path)
    claim_map = tmp_path / "knowledge_base" / "claim_evidence_map.yaml"
    claim_map.write_text(
        "A 12-model result from artifacts/benchmarks/20260601_live_full_qwen9b "
        "reported mean 0.139.",
        encoding="utf-8",
    )
    benchmark = _write_benchmark(tmp_path, total=2, splits={"train": 1, "dev": 1, "test": 0})
    evidence = _write_evidence_manifest(tmp_path, model="Qwen/Qwen3.5-9B", records=3)
    downstream = _write_downstream_manifest(tmp_path, zero_runs=1, control_runs=2, rows=2)

    report = run_paper_evidence_audit(
        root=tmp_path,
        benchmark_dir=benchmark,
        evidence_manifest=evidence,
        downstream_manifest=downstream,
        required_paths=[],
        expected_total=2,
        expected_splits={"train": 1, "dev": 1, "test": 0},
        expected_by_graph={"finbench": 2},
        expected_category_count=None,
        expected_model_records=3,
        expected_downstream_zero_runs=1,
        expected_downstream_control_runs=2,
        expected_downstream_rows=2,
    )

    labels = {hit["label"] for hit in report["text_hits"]}
    assert report["pass"] is False
    assert "contaminated benchmark export" in labels
    assert "stale 12-model claim" in labels
    assert "stale downstream aggregate" in labels


def test_paper_evidence_audit_flags_disallowed_model_provenance(tmp_path: Path):
    _write_clean_text_surfaces(tmp_path)
    benchmark = _write_benchmark(tmp_path, total=2, splits={"train": 1, "dev": 1, "test": 0})
    evidence = _write_evidence_manifest(
        tmp_path,
        model="Qwen/Qwen3.5-35B-A3B",
        records=3,
        pass_value=False,
    )
    downstream = _write_downstream_manifest(tmp_path, zero_runs=1, control_runs=2, rows=2)

    report = run_paper_evidence_audit(
        root=tmp_path,
        benchmark_dir=benchmark,
        evidence_manifest=evidence,
        downstream_manifest=downstream,
        required_paths=[],
        expected_total=2,
        expected_splits={"train": 1, "dev": 1, "test": 0},
        expected_by_graph={"finbench": 2},
        expected_category_count=None,
        expected_model_records=3,
        expected_downstream_zero_runs=1,
        expected_downstream_control_runs=2,
        expected_downstream_rows=2,
    )

    codes = {issue["code"] for issue in report["issues"]}
    assert report["pass"] is False
    assert "model_provenance_failed" in codes
    assert "disallowed_generation_or_judge_model" in codes


def _write_clean_text_surfaces(root: Path) -> None:
    paper = root / "paper_emnlp2026_industry"
    kb = root / "knowledge_base"
    paper.mkdir()
    kb.mkdir()
    for name in ("main_acl.tex", "main.tex", "paper.md", "README.md", "reproducibility_README.md"):
        (paper / name).write_text("Clean PIPE-Cypher evidence.", encoding="utf-8")
    (paper / "tables_clean.tex").write_text("Clean table.", encoding="utf-8")
    (paper / "appendix_clean.tex").write_text("Clean appendix.", encoding="utf-8")
    (kb / "claim_evidence_map.yaml").write_text("claims: []\n", encoding="utf-8")
    (kb / "review_response_matrix.md").write_text("Clean matrix.", encoding="utf-8")


def _write_benchmark(root: Path, *, total: int, splits: dict[str, int]) -> Path:
    benchmark = root / "benchmark"
    benchmark.mkdir()
    manifest = {
        "total_examples": total,
        "split_counts": splits,
        "records_paths": ["artifacts/runs/clean"],
    }
    stats = {
        "total": total,
        "by_split": splits,
        "by_graph": {"finbench": total},
        "by_category": {"simple_retrieval": total},
        "gate_counts": {
            "accepted": total,
            "read_only": total,
            "syntax_valid": total,
            "schema_valid": total,
            "execution_success": total,
            "judge_pass": total,
        },
    }
    (benchmark / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (benchmark / "stats.json").write_text(json.dumps(stats), encoding="utf-8")
    _write_jsonl(benchmark / "all.jsonl", total)
    for split, count in splits.items():
        _write_jsonl(benchmark / f"{split}.jsonl", count)
    return benchmark


def _write_evidence_manifest(
    root: Path,
    *,
    model: str,
    records: int,
    pass_value: bool = True,
) -> Path:
    path = root / "evidence.json"
    manifest = {
        "paper_ready": pass_value,
        "missing_artifacts": [],
        "artifacts": ["benchmark"],
        "model_provenance": {
            "pass": pass_value,
            "records": records,
            "model_counts": {model: records},
            "disallowed_model_counts": {} if pass_value else {model: records},
        },
    }
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _write_downstream_manifest(
    root: Path,
    *,
    zero_runs: int,
    control_runs: int,
    rows: int,
) -> Path:
    path = root / "downstream.json"
    manifest = {
        "expected": {"zero_runs": zero_runs, "control_runs": control_runs, "rows_per_run": rows},
        "observed": {"zero_runs": zero_runs, "control_runs": control_runs, "all_complete": True},
        "issues": [],
        "zero_runs": [_run_entry("zero", rows)],
        "control_runs": [_run_entry(f"control-{idx}", rows) for idx in range(control_runs)],
    }
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _run_entry(run_id: str, rows: int) -> dict[str, object]:
    return {
        "run_id": run_id,
        "files": {
            "predictions.jsonl": {"line_count": rows},
            "evaluation.jsonl": {"line_count": rows},
        },
        "issues": [],
    }


def _write_jsonl(path: Path, rows: int) -> None:
    path.write_text(
        "".join(json.dumps({"idx": idx}) + "\n" for idx in range(rows)),
        encoding="utf-8",
    )
