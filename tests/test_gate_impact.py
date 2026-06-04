from pipecypher.gate_impact import first_blocking_gate, summarize_gate_impact
from pipecypher.paper_tables import render_gate_impact_table


def _record(**overrides):
    row = {
        "graph_profile": "finbench",
        "category": "simple_retrieval",
        "question": "Q",
        "cypher": "MATCH (n) RETURN n",
        "accepted": False,
        "validation": {
            "read_only": True,
            "syntax_valid": True,
            "schema_valid": True,
            "issues": [],
        },
        "execution": {"success": True, "rows": [{"n": 1}]},
        "judge": {"passed": True, "failure_reason": ""},
    }
    row.update(overrides)
    return row


def test_first_blocking_gate_orders_validation_before_execution_and_judge():
    assert first_blocking_gate(_record(accepted=True)) == "accepted"
    assert (
        first_blocking_gate(
            _record(validation={"read_only": True, "syntax_valid": True, "schema_valid": False, "issues": [{"code": "wrong_direction"}]})
        )
        == "direction"
    )
    assert first_blocking_gate(_record(execution={"success": True, "rows": []})) == "empty_result"
    assert first_blocking_gate(_record(judge={"passed": False, "failure_reason": "duplicate accepted question"})) == "duplicate_or_diversity"


def test_first_blocking_gate_ignores_warning_issues_for_accepted_records():
    row = _record(
        accepted=True,
        validation={
            "read_only": True,
            "syntax_valid": True,
            "schema_valid": True,
            "issues": [{"level": "warning", "code": "rewrite_skipped"}],
        },
    )

    assert first_blocking_gate(row) == "accepted"


def test_gate_impact_summary_and_table():
    summary = summarize_gate_impact(
        [
            _record(accepted=True),
            _record(execution={"success": True, "rows": []}),
            _record(judge={"passed": False, "failure_reason": "semantic mismatch"}),
        ]
    )

    assert summary["records"] == 3
    assert summary["accepted"] == 1
    assert summary["blocked_by_gate"]["empty_result"] == 1
    assert summary["blocked_by_gate"]["judge"] == 1
    assert "tab:gate_impact" in render_gate_impact_table(summary)
