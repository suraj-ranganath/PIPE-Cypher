from pathlib import Path

from pipecypher.artifact_snapshot import build_artifact_snapshot, select_sample_examples
from pipecypher.benchmark_export import export_benchmark_package
from pipecypher.io import read_jsonl, write_jsonl


def _record(
    question: str,
    *,
    graph_profile: str,
    category: str,
) -> dict:
    cypher = (
        f"MATCH (p:Person {{personName: '{question}'}}) "
        "RETURN DISTINCT p.personName AS name"
    )
    return {
        "question": question,
        "cypher": cypher,
        "category": category,
        "graph_profile": graph_profile,
        "accepted": True,
        "validation": {
            "normalized_cypher": "MATCH (p:Person) RETURN DISTINCT p.personName AS name",
            "read_only": True,
            "syntax_valid": True,
            "schema_valid": True,
            "structural_features": {
                "difficulty": "easy",
                "labels": ["Person"],
                "relationship_types": [],
            },
        },
        "execution": {"success": True, "rows": [{"name": question}]},
        "judge": {
            "passed": True,
            "ambiguity_score": 0.0,
            "semantic_alignment_score": 1.0,
            "schema_use_score": 1.0,
            "difficulty": "easy",
        },
        "model": "Qwen/Test",
    }


def test_select_sample_examples_takes_stable_items_per_cell():
    examples = [
        {"id": "b", "graph_profile": "snb", "category": "simple_retrieval"},
        {"id": "a", "graph_profile": "snb", "category": "simple_retrieval"},
        {"id": "c", "graph_profile": "finbench", "category": "ranking_topk"},
    ]

    sample = select_sample_examples(examples, per_graph_category=1)

    assert [row["id"] for row in sample] == ["c", "a"]


def test_build_artifact_snapshot_writes_manifest_sample_and_readme(tmp_path: Path):
    run_dir = tmp_path / "run"
    records_path = run_dir / "records.jsonl"
    write_jsonl(
        records_path,
        [
            _record("Alice", graph_profile="finbench", category="simple_retrieval"),
            _record("Bob", graph_profile="finbench", category="simple_retrieval"),
            _record("Carla", graph_profile="snb", category="ranking_topk"),
        ],
    )
    export_benchmark_package(records_paths=[run_dir], output_dir=tmp_path / "export")

    snapshot = build_artifact_snapshot(
        export_dir=tmp_path / "export",
        output_dir=tmp_path / "snapshot",
        source_export_dir="artifacts/benchmarks/test",
    )

    assert snapshot["source_export_dir"] == "artifacts/benchmarks/test"
    assert snapshot["total_examples"] == 3
    assert snapshot["sample"]["count"] == 2
    assert "all.jsonl" in snapshot["file_checksums"]
    assert (tmp_path / "snapshot" / "manifest.json").exists()
    assert (tmp_path / "snapshot" / "README.md").exists()
    assert len(read_jsonl(tmp_path / "export" / "all.jsonl")) == 3
