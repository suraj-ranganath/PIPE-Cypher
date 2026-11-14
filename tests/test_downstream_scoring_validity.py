"""Regression tests for downstream scoring validity.

These cover the failure modes found in the June 2026 downstream transfer runs:
mis-routed endpoints returning HTTP 404 for every request (scored as 0.000),
checkpoints that emit literal ``\\n`` escapes, governance rules gating model
predictions before execution, and strict row equality penalizing omitted
policy-injected context columns.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipecypher.downstream_model_transfer import (
    build_fewshot_control_report,
    build_model_transfer_report,
    prediction_failure_rate,
)
from pipecypher.evaluation import (
    evaluate_prediction,
    policy_context_columns,
    projected_answer_scores,
    summarize_evaluation_rows,
)
from pipecypher.llm import assert_model_served
from pipecypher.models import ExecutionResult, SchemaSummary
from pipecypher.text2cypher import clean_predicted_cypher, unescape_literal_whitespace

FINBENCH_SCHEMA = SchemaSummary.from_dict(
    json.loads(Path("configs/schema_finbench.json").read_text(encoding="utf-8"))
)


class FakeClient:
    """Returns canned rows keyed by a substring of the executed query."""

    def __init__(self, responses: dict[str, list[dict]]):
        self.responses = responses
        self.executed: list[str] = []

    def run(self, query: str, **_: object) -> ExecutionResult:
        self.executed.append(query)
        for needle, rows in self.responses.items():
            if needle in query:
                return ExecutionResult(success=True, rows=rows)
        return ExecutionResult(success=False, rows=[], error="no canned response")


# ---------------------------------------------------------------------------
# Projection-tolerant scoring
# ---------------------------------------------------------------------------


def test_policy_context_columns_only_forgives_policy_injected_columns():
    gold = (
        "MATCH (p:Person {personName: 'Blythe'})-[:OWN_ACCOUNT]->(src:Account)"
        "-[:TRANSFER_TO]->(dst:Account) RETURN DISTINCT dst.accountId AS AccountId, "
        "dst.accountType AS AccountType, dst.isBlocked AS IsBlocked LIMIT 300"
    )
    columns = ["AccountId", "AccountType", "IsBlocked"]
    assert policy_context_columns(gold, columns) == ["AccountType", "IsBlocked"]


def test_policy_context_columns_keeps_aggregate_answer_columns_required():
    gold = (
        "MATCH (forum:Forum)-[:HAS_MEMBER]->(person:Person) WITH forum, "
        "COUNT(DISTINCT person) AS memberCount RETURN DISTINCT forum.title AS ForumTitle, "
        "memberCount ORDER BY memberCount DESC LIMIT 1"
    )
    assert policy_context_columns(gold, ["ForumTitle", "memberCount"]) == []


def test_projected_scores_accept_missing_context_columns():
    gold = [
        {"AccountId": "a1", "AccountType": "card", "IsBlocked": False},
        {"AccountId": "a2", "AccountType": "debit", "IsBlocked": True},
    ]
    pred = [{"accountId": "a2"}, {"accountId": "a1"}]
    scores, detail = projected_answer_scores(pred, gold, required_gold_columns=["AccountId"])
    assert scores.exact
    assert detail["mapping"] == {"AccountId": "accountId"}


def test_projected_scores_still_reject_wrong_entities():
    gold = [{"AccountId": "a1", "AccountType": "card"}, {"AccountId": "a2", "AccountType": "x"}]
    pred = [{"accountId": "a1"}, {"accountId": "a9"}]
    scores, _ = projected_answer_scores(pred, gold, required_gold_columns=["AccountId"])
    assert not scores.exact
    assert scores.f1 == pytest.approx(0.5)


def test_projected_scores_tolerate_extra_predicted_columns_and_order():
    gold = [{"PersonId": 1}, {"PersonId": 2}]
    pred = [{"name": "x", "id": 2}, {"name": "y", "id": 1}]
    scores, _ = projected_answer_scores(pred, gold, required_gold_columns=["PersonId"])
    assert scores.exact


def test_projected_scores_expand_returned_entities():
    gold = [{"PersonId": 1}, {"PersonId": 2}]
    pred = [{"p": {"id": 1, "firstName": "A"}}, {"p": {"id": 2, "firstName": "B"}}]
    scores, detail = projected_answer_scores(pred, gold, required_gold_columns=["PersonId"])
    assert scores.exact
    assert detail["node_expansion"] is True


def test_projected_scores_require_all_non_context_columns():
    gold = [{"ForumTitle": "f1", "memberCount": 10}]
    pred = [{"title": "f1", "members": 9}]
    scores, _ = projected_answer_scores(
        pred, gold, required_gold_columns=["ForumTitle", "memberCount"]
    )
    assert not scores.exact


# ---------------------------------------------------------------------------
# Evaluator executes read-only predictions as written
# ---------------------------------------------------------------------------

GOLD = (
    "MATCH (p:Person {personName: 'Blythe'})-[:OWN_ACCOUNT]->(src:Account)"
    "-[:TRANSFER_TO]->(dst:Account) RETURN DISTINCT dst.accountId AS AccountId, "
    "dst.accountType AS AccountType, dst.isBlocked AS IsBlocked LIMIT 300"
)
GOLD_ROWS = [
    {"AccountId": "a1", "AccountType": "card", "IsBlocked": False},
    {"AccountId": "a2", "AccountType": "debit", "IsBlocked": True},
]


def test_evaluator_scores_missing_context_columns_as_projected_match():
    pred = (
        "MATCH (p:Person {personName: 'Blythe'})-[:OWN_ACCOUNT]->(o:Account)"
        "-[:TRANSFER_TO]->(t:Account) RETURN DISTINCT t.accountId AS accountId"
    )
    client = FakeClient({"dst.accountType": GOLD_ROWS, "t.accountId": [{"accountId": "a1"}, {"accountId": "a2"}]})
    row = evaluate_prediction(
        question="Which accounts received transfers from Blythe's accounts?",
        gold_cypher=GOLD,
        predicted_cypher=pred,
        schema=FINBENCH_SCHEMA,
        client=client,
        include_text_metrics=False,
    )
    assert row["execution_accuracy"] is False
    assert row["projected_execution_accuracy"] is True
    assert row["required_gold_columns"] == ["AccountId"]


def test_evaluator_executes_governance_violating_read_only_prediction():
    # Undirected patterns are a construction-time governance error, but valid Cypher.
    pred = (
        "MATCH (p:Person {personName: 'Blythe'})-[:OWN_ACCOUNT]-(o:Account)"
        "-[:TRANSFER_TO]->(t:Account) RETURN DISTINCT t.accountId AS AccountId, "
        "t.accountType AS AccountType, t.isBlocked AS IsBlocked"
    )
    client = FakeClient({"dst.accountType": GOLD_ROWS, "t.accountType": GOLD_ROWS})
    row = evaluate_prediction(
        question="q",
        gold_cypher=GOLD,
        predicted_cypher=pred,
        schema=FINBENCH_SCHEMA,
        client=client,
        include_text_metrics=False,
    )
    assert row["governance_valid"] is False
    assert "undirected_relationship" in row["governance_error_codes"]
    assert row["execution_accuracy"] is True
    assert row["governed_execution_accuracy"] is False

    legacy = evaluate_prediction(
        question="q",
        gold_cypher=GOLD,
        predicted_cypher=pred,
        schema=FINBENCH_SCHEMA,
        client=FakeClient({"dst.accountType": GOLD_ROWS, "t.accountType": GOLD_ROWS}),
        include_text_metrics=False,
        governed_execution_only=True,
    )
    assert legacy["execution_success"] is False
    assert legacy["execution_accuracy"] is False


def test_evaluator_never_executes_write_queries():
    client = FakeClient({"dst.accountType": GOLD_ROWS, "DELETE": []})
    row = evaluate_prediction(
        question="q",
        gold_cypher=GOLD,
        predicted_cypher="MATCH (a:Account) DETACH DELETE a",
        schema=FINBENCH_SCHEMA,
        client=client,
        include_text_metrics=False,
    )
    assert row["read_only"] is False
    assert row["execution_success"] is False
    assert not any("DELETE" in query for query in client.executed)


def test_failed_requests_are_flagged_not_scored_silently():
    row = evaluate_prediction(
        question="q",
        gold_cypher=GOLD,
        predicted_cypher="",
        schema=FINBENCH_SCHEMA,
        client=FakeClient({"dst.accountType": GOLD_ROWS}),
        include_text_metrics=False,
        prediction_error="404 Client Error: Not Found for url: http://localhost:8000/v1/chat/completions",
    )
    assert row["prediction_failed"] is True
    summary = summarize_evaluation_rows(
        [{**row, "graph_profile": "finbench", "category": "c", "difficulty": "easy"}]
    )
    assert summary["run_validity"]["prediction_failure_rate"] == 1.0


# ---------------------------------------------------------------------------
# Prediction cleaning and endpoint preflight
# ---------------------------------------------------------------------------


def test_unescape_literal_newlines_outside_quotes_only():
    raw = "MATCH (p:Person {name: 'a\\\\nb'})\\nRETURN COUNT(DISTINCT p)"
    assert unescape_literal_whitespace(raw) == "MATCH (p:Person {name: 'a\\\\nb'})\nRETURN COUNT(DISTINCT p)"


def test_clean_predicted_cypher_handles_escaped_newlines():
    raw = "MATCH (t:Tag {name: 'Elton_John'})<-[:HAS_TAG]-(p:Post)\\nRETURN COUNT(DISTINCT p)"
    assert clean_predicted_cypher(raw) == (
        "MATCH (t:Tag {name: 'Elton_John'})<-[:HAS_TAG]-(p:Post) RETURN COUNT(DISTINCT p)"
    )


def test_assert_model_served_rejects_unserved_model(monkeypatch):
    class Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "Qwen/Qwen3.5-9B"}]}

    monkeypatch.setattr("pipecypher.llm.requests.get", lambda *a, **k: Resp())
    assert assert_model_served("http://x/v1", "Qwen/Qwen3.5-9B") == ["Qwen/Qwen3.5-9B"]
    with pytest.raises(RuntimeError, match="not served"):
        assert_model_served("http://x/v1", "tomasonjo/text2cypher-demo-16bit")


# ---------------------------------------------------------------------------
# Transfer summaries refuse infrastructure-failure runs
# ---------------------------------------------------------------------------


def _write_run(path: Path, mode: str, *, failed: bool, accuracy: float = 0.0) -> None:
    path.mkdir(parents=True, exist_ok=True)
    summary = {
        "overall": {
            "n": 3,
            "execution_accuracy": accuracy,
            "answer_f1": accuracy,
            "execution_success": accuracy,
            "parse_valid": 1.0,
            "schema_valid": 1.0,
            "read_only": 1.0,
        }
    }
    (path / f"{mode}_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    rows = [
        {
            "id": f"x{i}",
            "predicted_cypher": "" if failed else "MATCH (n) RETURN n",
            "error": "404 Client Error: Not Found" if failed else None,
        }
        for i in range(3)
    ]
    (path / f"{mode}_predictions.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )


def test_prediction_failure_rate_reads_legacy_prediction_files(tmp_path: Path):
    run = tmp_path / "20260604_clean_downstream_model_a_zero_fewshot"
    _write_run(run, "zero_shot", failed=True)
    assert prediction_failure_rate(run / "zero_shot_summary.json") == 1.0


def test_transfer_report_marks_failed_request_runs_incomplete(tmp_path: Path):
    bad = tmp_path / "20260604_clean_downstream_model_a_zero_fewshot"
    good = tmp_path / "20260604_clean_downstream_model_b_zero_fewshot"
    _write_run(bad, "zero_shot", failed=True)
    _write_run(bad, "few_shot", failed=True)
    _write_run(good, "zero_shot", failed=False, accuracy=0.2)
    _write_run(good, "few_shot", failed=False, accuracy=0.9)
    report = build_model_transfer_report([bad, good])
    assert report["complete_count"] == 1
    assert any("prediction failure rate" in m for m in report["incomplete_runs"][0]["missing"])


def test_fewshot_control_report_excludes_failed_zero_shot(tmp_path: Path):
    zero = tmp_path / "20260604_clean_downstream_model_a_zero_fewshot"
    _write_run(zero, "zero_shot", failed=True)
    _write_run(zero, "few_shot", failed=True)
    report = build_fewshot_control_report(zero_shot_dirs=[zero], control_dirs=[])
    assert report["complete_model_count"] == 0
    assert any("prediction failure rate" in m for m in report["models"][0]["missing"])


# ---------------------------------------------------------------------------
# External-reference and feature fixes (Text2Cypher-2024 anchor prep)
# ---------------------------------------------------------------------------


def test_evaluator_executes_read_only_external_gold_that_fails_governance():
    gold = "MATCH (a:Account)-[:TRANSFER_TO]-(b:Account) RETURN DISTINCT b.accountId AS id"
    rows = [{"id": "a1"}]
    row = evaluate_prediction(
        question="q",
        gold_cypher=gold,
        predicted_cypher="MATCH (a:Account)-[:TRANSFER_TO]->(b:Account) RETURN DISTINCT b.accountId AS id",
        schema=FINBENCH_SCHEMA,
        client=FakeClient({"]-(b:Account)": rows, "]->(b:Account)": rows}),
        include_text_metrics=False,
    )
    assert row["gold_governance_valid"] is False
    assert row["gold_execution_success"] is True
    assert row["execution_accuracy"] is True


def test_count_star_is_not_a_path_pattern():
    from pipecypher.validator import structural_features

    assert not structural_features("MATCH (a:Account) RETURN count(*) AS n")["path_pattern"]
    assert structural_features("MATCH (a:Account)-[:TRANSFER_TO*1..2]->(b) RETURN b")["path_pattern"]


def test_unknown_profiles_get_no_finbench_seed_templates():
    from pipecypher.graph_profiles import default_templates

    assert default_templates("t2c_northwind") == []
    assert default_templates("enterprise_private") == []
    assert default_templates("finbench")
