from __future__ import annotations

import json

import pytest

from pipecypher.config import RunConfig
from pipecypher.conventions import CONVENTION_SHEET, convention_sheet, symmetric_relationship_note
from pipecypher.judge import (
    CHECKLIST_CRITERIA,
    ChecklistJudge,
    JudgePanel,
    LLMJudge,
    DeterministicJudge,
    build_judge,
    combine_panel_results,
    compute_checklist_verdict,
    parse_checklist,
    render_judge_v3_prompt,
    validate_panel_spec,
)
from pipecypher.models import (
    ExecutionResult,
    JudgeResult,
    NodeProperty,
    RelationshipPattern,
    SchemaSummary,
    ValidationIssue,
    ValidationResult,
)


def _schema(symmetric: list[str] | None = None) -> SchemaSummary:
    return SchemaSummary(
        node_properties=[NodeProperty("Person", "id", "INTEGER"), NodeProperty("Person", "firstName", "STRING")],
        relationship_properties=[],
        relationships=[RelationshipPattern("Person", "KNOWS", "Person")],
        categorical_properties={},
        graph_name="snb",
        symmetric_relationships=symmetric or [],
    )


def _validation(ok: bool = True) -> ValidationResult:
    return ValidationResult(
        read_only=True,
        syntax_valid=True,
        schema_valid=ok,
        normalized_cypher="MATCH (p:Person) RETURN p.id",
        issues=[ValidationIssue("warning", "missing_context_column", "context column added")],
        structural_features={"difficulty": "easy", "aggregation": False},
    )


def _all(answer: str = "yes") -> dict:
    return {name: {"evidence": "ok", "answer": answer} for name in CHECKLIST_CRITERIA}


class StubLLM:
    def __init__(self, payloads: list, model: str = "stub/model") -> None:
        self.payloads = list(payloads)
        self.model = model
        self.calls: list[dict] = []

    def chat_json(self, **kwargs):
        self.calls.append(kwargs)
        payload = self.payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return payload


def test_parse_checklist_accepts_variants():
    data = {
        "criteria": {
            "values": {"answer": "Yes", "evidence": "id 5"},
            "relationships": "no",
            "aggregation": {"verdict": "N/A"},
            "grouping": {"answer": True},
            "comparisons": {"answer": "maybe"},
        }
    }
    parsed = parse_checklist(data)
    assert parsed["values"] == {"answer": "yes", "evidence": "id 5"}
    assert parsed["relationships"]["answer"] == "no"
    assert parsed["aggregation"]["answer"] == "na"
    assert parsed["grouping"]["answer"] == "yes"
    assert parsed["comparisons"]["answer"] == "invalid"
    assert "ranking" not in parsed


def test_verdict_rule_is_computed_by_code():
    passed, failing, missing = compute_checklist_verdict(parse_checklist(_all("yes")))
    assert passed and not failing and not missing

    checklist = parse_checklist({**_all("yes"), "aggregation": {"answer": "na"}, "ranking": {"answer": "na"}})
    assert compute_checklist_verdict(checklist)[0] is True

    checklist = parse_checklist({**_all("yes"), "comparisons": {"answer": "no"}})
    assert compute_checklist_verdict(checklist) == (False, ["comparisons"], [])

    # "na" fails closed only for "unambiguous"
    checklist = parse_checklist({**_all("yes"), "unambiguous": {"answer": "na"}})
    assert compute_checklist_verdict(checklist) == (False, ["unambiguous"], [])

    partial = {k: v for k, v in _all("yes").items() if k != "columns"}
    passed, failing, missing = compute_checklist_verdict(parse_checklist(partial))
    assert not passed and missing == ["columns"]

    checklist = parse_checklist({**_all("yes"), "values": {"answer": "perhaps"}})
    assert compute_checklist_verdict(checklist)[1] == ["values"]


def test_prompt_order_puts_fixed_blocks_before_schema_and_item():
    schema = _schema(["KNOWS"])
    prompt = render_judge_v3_prompt(
        question="Which people know person 7?",
        cypher="MATCH (p:Person {id: 7})-[:KNOWS]-(f:Person) RETURN f.id",
        schema=schema,
        validation=_validation(),
        execution=ExecutionResult(success=True, rows=[{"f.id": 1}]),
    )
    conv = prompt.index("C1 Values.")
    rubric = prompt.index("Checklist.")
    schema_pos = prompt.index("Graph schema:")
    item = prompt.index("Which people know person 7?")
    assert conv < rubric < schema_pos < item
    assert "Symmetric relationship types in this graph" in prompt
    assert "1 row returned" in prompt
    assert "context column added" in prompt
    # The fixed prefix is identical for two different items on the same graph.
    other = render_judge_v3_prompt(
        question="How many people does person 8 know?",
        cypher="MATCH (p:Person {id: 8})-[:KNOWS]-(f) RETURN count(f)",
        schema=schema,
        validation=_validation(),
        execution=ExecutionResult(success=True, rows=[{"count(f)": 3}]),
    )
    prefix = prompt[: prompt.index("Item to review")]
    assert other.startswith(prefix)


def test_prompt_row_summary_marks_capped_execution():
    rows = [{"x": i} for i in range(25)]
    prompt = render_judge_v3_prompt(
        question="q", cypher="MATCH (n) RETURN n", schema=_schema(), validation=_validation(),
        execution=ExecutionResult(success=True, rows=rows),
    )
    assert "at least 25 rows" in prompt
    prompt = render_judge_v3_prompt(
        question="q", cypher="MATCH (n) RETURN n", schema=_schema(), validation=_validation(),
        execution=ExecutionResult(success=True, rows=rows[:5]), row_count=140,
    )
    assert "140 rows returned" in prompt


def test_convention_sheet_helpers():
    assert "C13 One reading." in CONVENTION_SHEET
    assert symmetric_relationship_note(_schema()) == ""
    assert "KNOWS" in convention_sheet(_schema(["KNOWS"]))


def test_checklist_judge_pass_and_fail():
    llm = StubLLM([{**_all("yes"), "difficulty": "medium", "clarified_question": ""}])
    judge = ChecklistJudge(llm, label="glm")
    result = judge.judge(
        question="q", cypher="MATCH (p:Person) RETURN p.id", schema=_schema(), validation=_validation(),
        execution=ExecutionResult(success=True, rows=[{"p.id": 1}]),
    )
    assert result.passed and result.failure_reason == ""
    assert result.raw["judge_mode"] == "checklist" and result.raw["failing"] == []
    assert result.difficulty == "medium"
    assert llm.calls[0]["response_format"] == {"type": "json_object"}

    llm = StubLLM([{**_all("yes"), "unambiguous": {"answer": "no", "evidence": "unfilled {k}"},
                    "clarified_question": "Which 5 tags ...?"}])
    result = ChecklistJudge(llm).judge(
        question="q", cypher="c", schema=_schema(), validation=_validation(),
        execution=ExecutionResult(success=True, rows=[{"a": 1}]),
    )
    assert not result.passed
    assert "unambiguous=no" in result.failure_reason
    assert result.ambiguity_score == 1.0
    assert result.raw["clarified_question"] == "Which 5 tags ...?"


def test_checklist_judge_retries_then_fails_closed():
    llm = StubLLM([ValueError("bad json"), {**_all("yes")}])
    result = ChecklistJudge(llm, parse_retries=1).judge(
        question="q", cypher="c", schema=_schema(), validation=_validation(),
        execution=ExecutionResult(success=True, rows=[{"a": 1}]),
    )
    assert result.passed and len(llm.calls) == 2

    llm = StubLLM([ValueError("bad json"), ValueError("still bad")])
    result = ChecklistJudge(llm, parse_retries=1).judge(
        question="q", cypher="c", schema=_schema(), validation=_validation(),
        execution=ExecutionResult(success=True, rows=[{"a": 1}]),
    )
    assert not result.passed and "fail-closed" in result.failure_reason


class FixedJudge:
    def __init__(self, passed: bool, reason: str = "") -> None:
        self.passed = passed
        self.reason = reason
        self.calls = 0

    def judge(self, **_):
        self.calls += 1
        result = JudgeResult(passed=self.passed, ambiguity_score=0.1, semantic_alignment_score=0.9,
                             schema_use_score=1.0, difficulty="easy", failure_reason=self.reason)
        result.raw = {"judge_mode": "fixed"}
        return result


@pytest.mark.parametrize("parallel", [True, False])
def test_panel_requires_unanimous_accept_and_runs_every_member(parallel):
    a, b = FixedJudge(True), FixedJudge(False, "wrong grouping")
    panel = JudgePanel([("glm", a), ("gemma", b)], parallel=parallel)
    result = panel.judge(question="q", cypher="c", schema=_schema(), validation=_validation(),
                         execution=ExecutionResult(success=True, rows=[{"a": 1}]))
    assert not result.passed and a.calls == 1 and b.calls == 1
    assert "[gemma] wrong grouping" in result.failure_reason
    assert result.raw["panel_unanimous"] is False
    assert [m["label"] for m in result.raw["panel"]] == ["glm", "gemma"]

    ok = JudgePanel([("glm", FixedJudge(True)), ("gemma", FixedJudge(True))], parallel=parallel).judge(
        question="q", cypher="c", schema=_schema(), validation=_validation(),
        execution=ExecutionResult(success=True, rows=[{"a": 1}]),
    )
    assert ok.passed and ok.raw["panel_unanimous"] is True


def test_panel_validation():
    with pytest.raises(ValueError):
        JudgePanel([("only", FixedJudge(True))])
    with pytest.raises(ValueError):
        JudgePanel([("x", FixedJudge(True)), ("x", FixedJudge(True))])
    assert validate_panel_spec([{"label": "g", "model": "m"}]) == []
    errors = validate_panel_spec([{"label": "g", "model": "m", "provder_routing": {}}, {"model": "m2"}])
    assert any("unknown keys" in e for e in errors) and any(".label is required" in e for e in errors)
    assert validate_panel_spec([{"label": "primary", "model": "m"}])


def test_combine_panel_results_scores():
    r1 = JudgeResult(True, 0.1, 0.9, 1.0, "easy")
    r2 = JudgeResult(True, 0.3, 0.7, 0.8, "hard")
    combined = combine_panel_results([("a", r1), ("b", r2)], {"a": "m1", "b": "m2"})
    assert combined.passed
    assert combined.ambiguity_score == 0.3 and combined.semantic_alignment_score == 0.7
    assert combined.raw["panel"][1]["model"] == "m2"


def test_build_judge_modes(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    cfg = RunConfig()
    cfg.models.provider = "openrouter"
    cfg.models.llm_base_url = "https://openrouter.ai/api/v1"
    cfg.models.judge_model = "z-ai/glm-5.3-flash"
    cfg.models.max_tokens = 2048
    cfg.judge.deterministic_fallback = False
    judge = build_judge(cfg)
    assert isinstance(judge, LLMJudge) and judge.max_tokens == 2048 and judge.fail_closed

    cfg.judge.mode = "checklist"
    judge = build_judge(cfg)
    assert isinstance(judge, ChecklistJudge) and judge.schema_mode == "full"

    cfg.judge.panel = [{"label": "gemma4", "model": "google/gemma-4-26b-a4b-it",
                        "provider_routing": {"order": ["primeintellect/bf16"], "allow_fallbacks": False},
                        "reasoning_effort": "none"}]
    panel = build_judge(cfg, label_for=lambda role: f"run:{role}")
    assert isinstance(panel, JudgePanel)
    assert panel.models == {"primary": "z-ai/glm-5.3-flash", "gemma4": "google/gemma-4-26b-a4b-it"}
    member = panel.members[1][1]
    assert member.llm.provider_routing["order"] == ["primeintellect/bf16"]
    assert member.llm.call_label == "run:judge_gemma4"

    cfg.judge.mode = "bogus"
    with pytest.raises(ValueError):
        build_judge(cfg)
    cfg.judge.mode = "checklist"
    cfg.judge.panel = [{"label": "x", "model": "m", "typo": 1}]
    with pytest.raises(ValueError):
        build_judge(cfg)


def test_v2_judge_behavior_unchanged_by_default():
    cfg = RunConfig()
    assert cfg.judge.mode == "v2" and cfg.judge.panel == [] and cfg.judge.schema_mode == "full"
    fallback = DeterministicJudge()
    llm = StubLLM([{"pass": True, "ambiguity_score": 0.1, "semantic_alignment_score": 0.9,
                    "schema_use_score": 1.0, "difficulty": "easy", "failure_reason": ""}])
    result = LLMJudge(llm, fallback).judge(
        question="q", cypher="MATCH (p:Person) RETURN p.id", schema=_schema(), validation=_validation(),
        execution=ExecutionResult(success=True, rows=[{"p.id": 1}]),
    )
    assert result.passed
    assert "Validation summary" in llm.calls[0]["user"]
    json.dumps(result.raw)


def _snb_like() -> SchemaSummary:
    return SchemaSummary(
        node_properties=[NodeProperty("Person", "id", "INTEGER"), NodeProperty("Comment", "id", "INTEGER")],
        relationship_properties=[],
        relationships=[
            RelationshipPattern("Comment", "HAS_CREATOR", "Person"),
            RelationshipPattern("Person", "IS_LOCATED_IN", "City"),
            RelationshipPattern("Person", "KNOWS", "Person"),
        ],
        categorical_properties={},
        graph_name="snb",
        symmetric_relationships=["KNOWS"],
    )


def test_unlisted_relationship_patterns_catches_subquery_and_wrong_end_label():
    from pipecypher.judge import unlisted_relationship_patterns

    schema = _snb_like()
    reversed_in_subquery = (
        "MATCH (p:Person) WHERE NOT EXISTS { MATCH (p)-[:HAS_CREATOR]->(:Comment) } RETURN p.id"
    )
    assert unlisted_relationship_patterns(reversed_in_subquery, schema) == ["(Person)-[:HAS_CREATOR]->(Comment)"]
    assert unlisted_relationship_patterns(
        "MATCH (m:Person)-[:IS_LOCATED_IN]->(:Country {name: 'India'}) RETURN m.id", schema
    ) == ["(Person)-[:IS_LOCATED_IN]->(Country)"]
    # Correct direction, symmetric types either way, and untyped ends are not flagged.
    assert unlisted_relationship_patterns("MATCH (c:Comment)-[:HAS_CREATOR]->(p:Person) RETURN c.id", schema) == []
    assert unlisted_relationship_patterns("MATCH (p:Person)<-[:HAS_CREATOR]-(c:Comment) RETURN c.id", schema) == []
    assert unlisted_relationship_patterns("MATCH (a:Person)-[:KNOWS*1..2]-(b:Person) RETURN b.id", schema) == []
    assert unlisted_relationship_patterns("MATCH (a:Person)<-[:KNOWS]-(b:Person) RETURN b.id", schema) == []
    assert unlisted_relationship_patterns("MATCH (p:Person)-[:HAS_CREATOR]->(x) RETURN x", schema) == []
    # String literals that look like patterns are ignored.
    assert unlisted_relationship_patterns(
        "MATCH (p:Person) WHERE p.note = '(a:Person)-[:HAS_CREATOR]->(b:Comment)' RETURN p", schema
    ) == []


def test_dropped_with_variables():
    from pipecypher.judge import dropped_with_variables

    bug = (
        "MATCH (p:Person {id: 50})-[:HAS_INTEREST]->(it:Tag) WITH collect(it.id) AS interestIds "
        "MATCH (p)<-[:HAS_CREATOR]-(m:Message)-[:HAS_TAG]->(t:Tag) RETURN t.name, t.id IN interestIds"
    )
    assert dropped_with_variables(bug) == ["variable `p` is not carried through WITH and is re-bound to any node later"]
    carried = "MATCH (p:Person)-[:X]->(t) WITH p, collect(t) AS ts MATCH (p)-[:Y]->(z) RETURN p, ts, z"
    assert dropped_with_variables(carried) == []
    # Use inside the WITH projection itself (including subqueries) is allowed.
    inside = (
        "MATCH (p:Person {id: 1}), (f:Forum) WITH f, CASE WHEN EXISTS { MATCH (f)-[:HAS_MEMBER]->(p) } "
        "THEN 'member' ELSE 'other' END AS role RETURN f.id, role"
    )
    assert dropped_with_variables(inside) == []
    assert dropped_with_variables("MATCH (a)-[:X]->(b) WITH * MATCH (b)-[:Y]->(c) RETURN c") == []
    assert dropped_with_variables("MATCH (a)-[:X]->(b) RETURN a UNION MATCH (a)-[:X]->(b) RETURN a") == []


def test_judge_prompt_includes_deterministic_notes():
    prompt = render_judge_v3_prompt(
        question="Which people have never written a comment?",
        cypher="MATCH (p:Person) WHERE NOT EXISTS { MATCH (p)-[:HAS_CREATOR]->(:Comment) } RETURN p.id",
        schema=_snb_like(),
        validation=_validation(),
        execution=ExecutionResult(success=True, rows=[{"p.id": 1}]),
    )
    assert "(Person)-[:HAS_CREATOR]->(Comment) is not listed in the schema" in prompt


FROZEN_JUDGE_V3_SHA256 = "a4b55edc63f086a2ae13f96a93ba2db24ec5ba55895f3226009542a4a89a362a"


def test_judge_v3_contract_is_frozen():
    """Calibrated on 2026-11-12 (artifacts/naacl_v3/calibration/frozen_judge_v3.json).

    Changing the judge prompt, system text, or convention sheet invalidates the
    calibration; re-run scripts/calibrate_judges.py and update this hash only then.
    """
    from pipecypher.judge import JUDGE_V3_PROMPT_SHA256

    assert JUDGE_V3_PROMPT_SHA256 == FROZEN_JUDGE_V3_SHA256
