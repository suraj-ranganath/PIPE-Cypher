from pathlib import Path

from pipecypher.downstream_error_analysis import (
    classify_downstream_error,
    downstream_error_report,
    load_evaluation_rows,
)
from pipecypher.paper_tables import render_downstream_error_table


def _row(**overrides):
    row = {
        "execution_accuracy": False,
        "prediction_error": None,
        "parse_valid": True,
        "read_only": True,
        "schema_valid": True,
        "execution_success": True,
        "answer_f1": 0.0,
        "predicted_issues": [],
        "graph_profile": "finbench",
        "category": "simple_retrieval",
        "difficulty": "easy",
    }
    row.update(overrides)
    return row


def test_classify_downstream_error_orders_failure_stages():
    assert classify_downstream_error(_row(execution_accuracy=True)) == "correct"
    assert classify_downstream_error(_row(prediction_error="timeout")) == "prediction_error"
    assert classify_downstream_error(_row(parse_valid=False)) == "parse_invalid"
    assert classify_downstream_error(_row(read_only=False)) == "unsafe_or_not_read_only"
    assert classify_downstream_error(_row(schema_valid=False)) == "schema_invalid"
    assert classify_downstream_error(_row(execution_success=False)) == "execution_failed"
    assert classify_downstream_error(_row(answer_f1=0.5)) == "partial_answer_mismatch"
    assert classify_downstream_error(_row()) == "answer_mismatch"


def test_downstream_error_report_counts_groups_and_issue_codes(tmp_path: Path):
    rows = [
        _row(execution_accuracy=True),
        _row(schema_valid=False, predicted_issues=[{"code": "unknown_property"}]),
        _row(execution_success=False, category="ranking_topk", difficulty="medium"),
        _row(answer_f1=0.25, graph_profile="snb", category="ranking_topk"),
    ]
    path = tmp_path / "eval.jsonl"
    path.write_text("\n".join("{}" for _ in rows), encoding="utf-8")

    report = downstream_error_report(rows, source_path=path)
    table = render_downstream_error_table(report)

    assert report["total"] == 4
    assert report["correct"] == 1
    assert report["incorrect"] == 3
    assert report["bucket_counts"]["correct"] == 1
    assert report["error_bucket_counts"]["schema_invalid"] == 1
    assert report["by_graph"]["snb"]["error_bucket_counts"]["partial_answer_mismatch"] == 1
    assert report["by_category"]["ranking_topk"]["incorrect"] == 2
    assert report["by_difficulty"]["medium"]["error_bucket_counts"]["execution_failed"] == 1
    assert report["top_predicted_issue_codes"] == {"unknown_property": 1}
    assert "Schema invalid & 1 & 0.333" in table
    assert "Partial answer mismatch & 1 & 0.333" in table


def test_load_evaluation_rows_reads_jsonl(tmp_path: Path):
    path = tmp_path / "eval.jsonl"
    path.write_text('{"id": "a"}\n{"id": "b"}\n', encoding="utf-8")

    assert load_evaluation_rows(path) == [{"id": "a"}, {"id": "b"}]
