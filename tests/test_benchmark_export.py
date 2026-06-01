from pathlib import Path

from pipecypher.benchmark_export import (
    assign_splits,
    benchmark_id,
    export_benchmark_package,
    materialize_benchmark_examples,
)
from pipecypher.io import read_jsonl, write_jsonl


def _record(question: str, category: str = "simple_retrieval", accepted: bool = True):
    return {
        "question": question,
        "cypher": f"MATCH (p:Person {{personName: '{question}'}}) RETURN DISTINCT p.personName AS name",
        "category": category,
        "graph_profile": "finbench",
        "accepted": accepted,
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
        "entity_values": [question],
        "reverse_cypher": "MATCH (p:Person) RETURN p.personName AS personName LIMIT 10",
        "model": "Qwen/Test",
    }


def test_benchmark_id_is_stable_across_source_run_metadata():
    first = _record("Alice")
    second = dict(first, _source_run="different")
    assert benchmark_id(first) == benchmark_id(second)


def test_materialize_filters_rejected_and_dedupes():
    accepted = _record("Alice")
    duplicate = dict(accepted)
    rejected = _record("Bob", accepted=False)
    examples = materialize_benchmark_examples([accepted, duplicate, rejected])
    assert len(examples) == 1
    assert examples[0]["question"] == "Alice"
    assert examples[0]["gates"]["accepted"] is True


def test_materialize_dedupes_same_question_with_different_cypher():
    accepted = _record("Alice")
    duplicate_question = dict(
        accepted,
        cypher="MATCH (p:Person {personName: 'Alice'}) RETURN DISTINCT p AS person",
    )

    examples = materialize_benchmark_examples([accepted, duplicate_question])

    assert len(examples) == 1
    assert examples[0]["question"] == "Alice"


def test_assign_splits_balances_by_graph_and_category():
    examples = materialize_benchmark_examples(
        [_record(f"q{i}", category="simple_retrieval") for i in range(5)]
    )
    splits = assign_splits(examples, seed="test")
    assert {split: len(rows) for split, rows in splits.items()} == {
        "train": 3,
        "dev": 1,
        "test": 1,
    }


def test_assign_splits_keeps_dev_nonempty_for_many_two_item_groups():
    records = []
    for category in ("simple_retrieval", "complex_retrieval", "ranking_topk"):
        records.extend(_record(f"{category}_{i}", category=category) for i in range(2))
    splits = assign_splits(materialize_benchmark_examples(records), seed="test")
    assert all(splits[split] for split in ("train", "dev", "test"))
    assert sum(len(rows) for rows in splits.values()) == 6


def test_export_benchmark_package_writes_manifest_stats_and_splits(tmp_path: Path):
    run_dir = tmp_path / "run_a"
    records_path = run_dir / "records.jsonl"
    write_jsonl(records_path, [_record("Alice"), _record("Bob"), _record("Carla")])

    result = export_benchmark_package(records_paths=[run_dir], output_dir=tmp_path / "export")
    out = tmp_path / "export"

    assert result["manifest"]["total_examples"] == 3
    assert (out / "manifest.json").exists()
    assert (out / "stats.json").exists()
    assert len(read_jsonl(out / "all.jsonl")) == 3
    assert sum(len(read_jsonl(out / f"{split}.jsonl")) for split in ("train", "dev", "test")) == 3
