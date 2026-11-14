from pipecypher.failure_taxonomy import (
    classify_failure,
    failure_taxonomy_report,
    judge_reason_bucket,
)
from pipecypher.paper_tables import render_failure_taxonomy_table


def _row(
    *,
    accepted=False,
    validation=None,
    execution=None,
    judge=None,
    category="simple_retrieval",
    empty_result_diagnostic=None,
):
    row = {
        "accepted": accepted,
        "graph_profile": "finbench",
        "category": category,
        "validation": validation
        or {
            "read_only": True,
            "syntax_valid": True,
            "schema_valid": True,
            "issues": [],
        },
        "execution": execution or {"success": True, "rows": [{"x": 1}]},
        "judge": judge or {"passed": True, "failure_reason": ""},
    }
    if empty_result_diagnostic:
        row["empty_result_diagnostic"] = empty_result_diagnostic
    return row


def test_classify_failure_orders_post_judge_controls_before_other_gates():
    row = _row(
        judge={
            "passed": False,
            "failure_reason": "duplicate accepted question",
        }
    )

    assert classify_failure(row) == "diversity_control"
    assert judge_reason_bucket(row) == "diversity_control"


def test_classify_failure_covers_validation_execution_and_judge_rejects():
    schema_invalid = _row(
        validation={
            "read_only": True,
            "syntax_valid": True,
            "schema_valid": False,
            "issues": [{"code": "unknown_label"}],
        },
        execution={"success": False, "rows": []},
        judge={"passed": False, "failure_reason": "schema label mismatch"},
    )
    execution_error = _row(
        execution={"success": False, "rows": [], "error": "timeout"},
        judge={"passed": False, "failure_reason": "execution failed"},
    )
    judge_reject = _row(
        validation={
            "read_only": True,
            "syntax_valid": True,
            "schema_valid": True,
            "issues": [{"code": "generic_node_scan"}],
        },
        judge={"passed": False, "failure_reason": "does not answer the question"},
    )

    assert classify_failure(schema_invalid) == "schema_invalid"
    assert classify_failure(execution_error) == "execution_error"
    assert classify_failure(judge_reject) == "judge_reject"
    assert judge_reason_bucket(judge_reject) == "generic_node_scan"


def test_failure_taxonomy_report_and_table_are_paper_ready():
    rows = [
        _row(accepted=True),
        _row(judge={"passed": False, "failure_reason": "does not answer the question"}),
        _row(
            validation={
                "read_only": True,
                "syntax_valid": True,
                "schema_valid": False,
                "issues": [{"code": "unknown_relationship_type"}],
            },
            execution={"success": False, "rows": []},
            judge={"passed": False, "failure_reason": "schema relationship mismatch"},
            category="complex_retrieval",
        ),
        _row(
            execution={"success": True, "rows": []},
            judge={"passed": False, "failure_reason": "execution returned no rows"},
            empty_result_diagnostic={"classification": "literal_miss"},
        ),
    ]

    report = failure_taxonomy_report(rows, source_paths=["records.jsonl"])
    table = render_failure_taxonomy_table(report)

    assert report["total"] == 4
    assert report["accepted"] == 1
    assert report["rejection_bucket_counts"] == {
        "empty_result": 1,
        "schema_invalid": 1,
        "judge_reject": 1,
    }
    assert report["top_validation_issues"] == {"unknown_relationship_type": 1}
    assert report["empty_result_diagnostic_counts"] == {"literal_miss": 1}
    assert report["by_category"]["complex_retrieval"]["rejected"] == 1
    assert "Judge semantic reject & 1 & 0.333" in table
    assert "Schema invalid & 1 & 0.333" in table
