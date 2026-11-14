from pipecypher.models import ExecutionResult
from pipecypher.rewrite_audit import (
    classify_rewrite,
    compare_execution_results,
    summarize_rewrite_audit,
)


def test_classify_rewrite_detects_return_distinct_insertion():
    classes = classify_rewrite(
        "MATCH (p:Person) RETURN p.name AS name",
        "MATCH (p:Person) RETURN DISTINCT p.name AS name",
    )

    assert "return_distinct_inserted" in classes


def test_summarize_rewrite_audit_counts_accepted_changes_and_skips():
    summary = summarize_rewrite_audit(
        [
            {
                "accepted": True,
                "graph_profile": "finbench",
                "category": "simple_retrieval",
                "cypher": "MATCH (p:Person) RETURN p.name",
                "validation": {
                    "normalized_cypher": "MATCH (p:Person) RETURN DISTINCT p.name",
                    "structural_features": {"rewrite_skip_reasons": []},
                },
            },
            {
                "accepted": False,
                "graph_profile": "snb",
                "category": "ranking_topk",
                "cypher": "MATCH (n) RETURN n",
                "validation": {
                    "normalized_cypher": "MATCH (n) RETURN n",
                    "structural_features": {"rewrite_skip_reasons": ["CALL"]},
                },
            },
        ]
    )

    assert summary["records"] == 2
    assert summary["changed_records"] == 1
    assert summary["accepted_changed_records"] == 1
    assert summary["rewrite_type_counts"]["return_distinct_inserted"] == 1
    assert summary["rewrite_skip_reasons"]["CALL"] == 1


def test_compare_execution_results_tracks_duplicate_collapse():
    original = ExecutionResult(success=True, rows=[{"x": 1}, {"x": 1}])
    normalized = ExecutionResult(success=True, rows=[{"x": 1}])

    comparison = compare_execution_results(original, normalized)

    assert comparison["answer_set_equal"]
    assert not comparison["answer_multiset_equal"]
    assert comparison["duplicate_collapse"]
