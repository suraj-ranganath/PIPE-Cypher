"""v3 generation controls: parameterized template Cypher, outcome-aware binding,
literal consistency, gates before the judge, tier quotas, style realization,
and pause-on-cap spending."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from pipecypher.config import RunConfig, validate_config
from pipecypher.graph_profiles import finbench_reference_schema
from pipecypher.judge import DeterministicJudge
from pipecypher.literal_consistency import literal_consistency_problems
from pipecypher.llm import BudgetExceededError, ChatResponse, NullLLM, SpendLedger
from pipecypher.models import ExecutionResult, JudgeResult, TemplateCandidate
from pipecypher.pipeline import PipeCypherPipeline
from pipecypher.template_binding import (
    check_template_cypher,
    derive_binding_queries,
    is_degenerate,
    render_with_literals,
)


# ---------------------------------------------------------------- template_binding
def test_check_template_cypher_requires_every_slot_as_parameter():
    assert check_template_cypher("MATCH (p:Person) WHERE p.personId = $person RETURN p", ["person"]) is None
    assert "does not use" in check_template_cypher("MATCH (p:Person) RETURN p", ["person"])
    assert "unknown parameter" in check_template_cypher("MATCH (p) WHERE p.x = $a AND p.y = $b RETURN p", ["a"])
    # '$person' inside a string literal is not a parameter.
    assert "does not use" in check_template_cypher("MATCH (p:Person {personName: '$person'}) RETURN p", ["person"])


def test_derive_binding_keeps_other_predicates_and_projects_slots():
    cypher = (
        "MATCH (p:Person)-[:OWN_ACCOUNT]->(a:Account) WHERE p.personId = $person AND a.isBlocked = true "
        "RETURN DISTINCT a.accountId AS accountId ORDER BY accountId"
    )
    queries, problem = derive_binding_queries(cypher, ["person"], limit=50)
    assert problem is None
    assert queries[0].strategy == "derived_return"
    assert queries[0].cypher.endswith("WHERE true AND a.isBlocked = true RETURN DISTINCT p.personId AS person LIMIT 50")


def test_derive_binding_handles_inline_maps_and_aggregation_stages():
    cypher = (
        "MATCH (p:Person {personId: $person})-[:OWN_ACCOUNT]->(a:Account) "
        "WITH p, count(DISTINCT a) AS n WHERE n > 2 RETURN n"
    )
    queries, problem = derive_binding_queries(cypher, ["person"], limit=10)
    assert problem is None
    assert [q.strategy for q in queries] == ["derived_return", "derived_prefix"]
    assert "WHERE n > 2 RETURN DISTINCT p.personId AS person LIMIT 10" in queries[0].cypher
    assert "$person" not in queries[0].cypher and "{" not in queries[0].cypher


def test_derive_binding_ignores_starts_with_and_fails_closed_on_non_equality():
    cypher = (
        "MATCH (a:Account {accountId: $acct})-[:TRANSFER_TO]->(b:Account) "
        "WHERE b.nickname STARTS WITH 'A' RETURN DISTINCT b.accountId AS id"
    )
    queries, problem = derive_binding_queries(cypher, ["acct"], limit=5)
    assert problem is None and len(queries) == 1
    assert "STARTS WITH 'A' RETURN DISTINCT a.accountId AS acct LIMIT 5" in queries[0].cypher
    queries, problem = derive_binding_queries("MATCH (a:Account) WHERE a.accountId IN $ids RETURN a", ["ids"], limit=5)
    assert queries == [] and "simple equality" in problem


def test_is_degenerate_and_render_with_literals():
    assert is_degenerate(ExecutionResult(success=True, rows=[]))
    assert is_degenerate(ExecutionResult(success=True, rows=[{"n": 0}]))
    assert not is_degenerate(ExecutionResult(success=True, rows=[{"flag": False}]))
    assert not is_degenerate(ExecutionResult(success=True, rows=[{"n": 3}]))
    rendered = render_with_literals(
        "MATCH (a:Account {nickname: '$x'}) WHERE a.accountId = $acct AND a.nickname = $nick RETURN a",
        {"acct": 42, "nick": "O'Neil"},
    )
    assert rendered == "MATCH (a:Account {nickname: '$x'}) WHERE a.accountId = 42 AND a.nickname = 'O\\'Neil' RETURN a"


# ---------------------------------------------------------------- literal consistency
@pytest.mark.parametrize(
    "question,cypher,bound,expected",
    [
        ("Among tag records with id 'tag with id 1152', which link most?",
         "MATCH (s:Tag {id: 1152}) RETURN s.id ORDER BY s.id DESC LIMIT 1", [], "quoted value"),
        ("Which {k} accounts repaid the most?",
         "MATCH (a:Account) RETURN a.accountId ORDER BY a.accountId LIMIT 10", [], "unfilled placeholder"),
        ("Which posts have the most forums pointing to them?",
         "MATCH (f:Forum)-[:CONTAINER_OF]->(p:Post) WITH p, count(f) AS c RETURN p.id, c ORDER BY c DESC LIMIT 10", [], "LIMIT 10"),
        ("Has person 8796093022282 worked at company id company?",
         "MATCH (p:Person {id: 8796093022282})-[:WORK_AT]->(c:Company) RETURN count(c) > 0 AS x", ["company"], "bound value"),
        ("Which accounts have a total transfer amount above the threshold?",
         "MATCH (a:Account)-[t:TRANSFER_TO]->() WITH a, sum(t.amount) AS s WHERE s > 10000 RETURN a.accountId, s", [], "number 10000"),
    ],
)
def test_literal_gate_flags_v2_defect_patterns(question, cypher, bound, expected):
    problems = literal_consistency_problems(question, cypher, bound)
    assert any(expected in problem for problem in problems), problems


@pytest.mark.parametrize(
    "question,cypher,bound",
    [
        ("Which 5 accounts received the most transfers from account 42?",
         "MATCH (a:Account {accountId: 42})-[:TRANSFER_TO]->(b:Account) WITH b, count(*) AS c "
         "RETURN b.accountId, c ORDER BY c DESC LIMIT 5", [42]),
        ("Which accounts made more than 3 transfers after January 1, 2022?",
         "MATCH (a:Account)-[t:TRANSFER_TO]->() WHERE t.createTime > datetime('2022-01-01T00:00:00') "
         "WITH a, count(t) AS c WHERE c >= 4 RETURN a.accountId", []),
        ("Which accounts are reachable within two transfer hops from account 7?",
         "MATCH (a:Account {accountId: 7})-[:TRANSFER_TO*1..2]->(b:Account) RETURN DISTINCT b.accountId", [7]),
        ("List universities and companies for person 41 with their type.",
         "MATCH (p:Person {id: 41})-[:STUDY_AT]->(u:University) RETURN collect({name: u.name, type: 'University'}) AS x", [41]),
        ("Has loan 99 had a repayment greater than half of the loan amount?",
         "MATCH (a:Account)-[r:REPAY]->(l:Loan {loanId: '99'}) WHERE r.amount > l.loanAmount / 2 RETURN count(r) > 0 AS x", ["99"]),
        ("Which transfers from account 5 happened within 7 days of its creation?",
         "MATCH (a:Account {accountId: 5})-[t:TRANSFER_TO]->() WHERE t.createTime <= a.createTime + duration('P7D') RETURN t.amount", [5]),
        ("Which accounts with type 'credit card' are blocked?",
         "MATCH (a:Account) WHERE a.accountType = 'credit card' AND a.isBlocked = true RETURN a.accountId", []),
    ],
)
def test_literal_gate_accepts_consistent_items(question, cypher, bound):
    assert literal_consistency_problems(question, cypher, bound) == []


def test_literal_gate_ignores_pipeline_default_limit():
    question = "List the transfers of account 5 in chronological order."
    cypher = "MATCH (a:Account {accountId: 5})-[t:TRANSFER_TO]->() RETURN t.amount ORDER BY t.createTime LIMIT 300"
    assert literal_consistency_problems(question, cypher, [5])
    assert literal_consistency_problems(question, cypher, [5], ignore_limits=[300]) == []


# ---------------------------------------------------------------- pipeline integration
class _ParamClient:
    """Answers the parameterized template query only for bindings in ``good``."""

    def __init__(self, candidates, good, *, extra_rows=None):
        self.candidates = candidates
        self.good = set(good)
        self.extra_rows = extra_rows or [{"accountId": "A1"}]
        self.verified: list[object] = []

    def run(self, query, params=None, *, read_only=True, limit_rows=None):
        if params:
            value = next(iter(params.values()))
            self.verified.append(value)
            rows = self.extra_rows if value in self.good else []
            return ExecutionResult(success=True, rows=rows)
        if "AS person" in query:
            return ExecutionResult(success=True, rows=[{"person": c} for c in self.candidates])
        return ExecutionResult(success=True, rows=self.extra_rows)


def _v3_config() -> RunConfig:
    cfg = RunConfig()
    gen = cfg.generation
    gen.template_cypher = True
    gen.outcome_aware_binding = True
    gen.require_slot_bindings = True
    gen.literal_consistency_gate = True
    gen.convention_sheet = True
    gen.binding_verify_attempts = 5
    return cfg


_TEMPLATE_ITEM = {
    "template": "Which blocked accounts does person {person} own?",
    "slots": {"person": "Person.personId"},
    "cypher": "MATCH (p:Person)-[:OWN_ACCOUNT]->(a:Account) WHERE p.personId = $person AND a.isBlocked = true "
    "RETURN DISTINCT a.accountId AS accountId, a.accountType AS accountType, a.isBlocked AS isBlocked",
    "rationale": "1 hop + filter",
}


def test_template_from_item_requires_valid_parameterized_cypher():
    pipeline = PipeCypherPipeline(
        config=_v3_config(), schema=finbench_reference_schema(), client=_ParamClient([], []), llm=NullLLM(), judge=DeterministicJudge()
    )
    template = pipeline._template_from_item(dict(_TEMPLATE_ITEM), "simple_retrieval", {"template_origin": "llm"})
    assert template is not None and "$person" in template.metadata["parameterized_cypher"]
    missing = dict(_TEMPLATE_ITEM, cypher="MATCH (p:Person) RETURN p.personId")
    assert pipeline._template_from_item(missing, "simple_retrieval", {}) is None
    undeclared = dict(_TEMPLATE_ITEM, template="Which {k} accounts does person {person} own?")
    assert pipeline._template_from_item(undeclared, "simple_retrieval", {}) is None
    assert pipeline.template_rejections


def test_outcome_aware_binding_verifies_against_template_query():
    client = _ParamClient(candidates=["p1", "p2", "p3"], good={"p3"})
    pipeline = PipeCypherPipeline(
        config=_v3_config(), schema=finbench_reference_schema(), client=client, llm=NullLLM(), judge=DeterministicJudge()
    )
    template = pipeline._template_from_item(dict(_TEMPLATE_ITEM), "simple_retrieval", {"template_origin": "llm"})
    bindings, _ = pipeline.bind_slots(template)
    assert bindings == {"person": "p3"}
    assert client.verified == ["p1", "p2", "p3"]
    assert pipeline.last_binding_info["binding_source"] == "derived_return"
    assert pipeline.last_binding_info["verified"] is True


def test_outcome_aware_binding_never_uses_unverified_values():
    client = _ParamClient(candidates=["p1", "p2"], good=set())
    pipeline = PipeCypherPipeline(
        config=_v3_config(), schema=finbench_reference_schema(), client=client, llm=NullLLM(), judge=DeterministicJudge()
    )
    template = pipeline._template_from_item(dict(_TEMPLATE_ITEM), "simple_retrieval", {"template_origin": "llm"})
    bindings, _ = pipeline.bind_slots(template)
    assert bindings == {}
    record = pipeline.run_candidate(template)
    assert not record.accepted
    assert record.judge.failure_reason in {"slot bindings unavailable", "slot bindings exhausted"}


def test_llm_template_without_cypher_is_not_bound_under_v3():
    pipeline = PipeCypherPipeline(
        config=_v3_config(), schema=finbench_reference_schema(), client=_ParamClient(["p1"], {"p1"}), llm=NullLLM(), judge=DeterministicJudge()
    )
    template = TemplateCandidate(
        template="Which accounts does person {person} own?",
        category="simple_retrieval",
        slots={"person": "Person.personId"},
        metadata={"template_origin": "llm"},
    )
    assert pipeline.bind_slots(template) == ({}, None)


class _CountingJudge(DeterministicJudge):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def judge(self, **kwargs):
        self.calls += 1
        return JudgeResult(True, 0.0, 1.0, 1.0, "easy")


def test_v3_gates_run_before_the_judge():
    judge = _CountingJudge()
    client = _ParamClient([], set(), extra_rows=[{"accountId": "A1"}])
    pipeline = PipeCypherPipeline(
        config=_v3_config(), schema=finbench_reference_schema(), client=client, llm=NullLLM(), judge=judge
    )
    # Literal mismatch: the question never states 'credit card'.
    _, _, _, result, _ = pipeline._evaluate_cypher(
        question="Which accounts are blocked?",
        cypher="MATCH (a:Account) WHERE a.accountType = 'credit card' RETURN DISTINCT a.accountId AS accountId, "
        "a.accountType AS accountType, a.isBlocked AS isBlocked",
    )
    assert not result.passed and "literal mismatch" in result.failure_reason
    assert judge.calls == 0
    _, _, _, result, _ = pipeline._evaluate_cypher(
        question="Which accounts have type 'credit card'?",
        cypher="MATCH (a:Account) WHERE a.accountType = 'credit card' RETURN DISTINCT a.accountId AS accountId, "
        "a.accountType AS accountType, a.isBlocked AS isBlocked",
    )
    assert result.passed and judge.calls == 1


def test_fill_template_unquotes_identifiers_under_conventions():
    pipeline = PipeCypherPipeline(
        config=_v3_config(), schema=finbench_reference_schema(), client=_ParamClient([], set()), llm=NullLLM(), judge=DeterministicJudge()
    )
    template = TemplateCandidate(
        template="Which accounts does the person with id '{person}' own?",
        category="simple_retrieval",
        slots={"person": "Person.personId"},
    )
    question, _ = pipeline.fill_template(template, {"person": 1152})
    assert question == "Which accounts does the person with id 1152 own?"


def test_tier_quota_counts_and_spillover():
    cfg = _v3_config()
    cfg.generation.difficulty_model_path = str(Path(__file__).resolve().parents[1] / "configs" / "difficulty_v3.json")
    cfg.generation.tier_quotas = {"_default": {"easy": 0.4, "medium": 0.4, "hard": 0.2}}
    pipeline = PipeCypherPipeline(
        config=cfg, schema=finbench_reference_schema(), client=_ParamClient([], set()), llm=NullLLM(), judge=DeterministicJudge()
    )
    quota = pipeline._tier_quota("simple_retrieval", 10)
    assert quota == {"easy": 4, "medium": 4, "hard": 2}
    pipeline.tier_counts[("simple_retrieval", "easy")] = 4
    pipeline.tier_counts[("simple_retrieval", "medium")] = 4
    assert pipeline._needed_tiers("simple_retrieval", quota) == {"hard"}
    moves = pipeline._spill_tier_quota("simple_retrieval", quota)
    assert moves == {"hard": {"moved": 1, "to": "medium"}}
    assert sum(quota.values()) == 10


class _RealizeLLM:
    model = "fake"

    def __init__(self, paraphrases):
        self.paraphrases = paraphrases

    def chat_json(self, **kwargs):
        return {"paraphrases": self.paraphrases}

    def chat(self, **kwargs):
        return ChatResponse(text=json.dumps({"paraphrases": self.paraphrases}), raw={})


def test_realization_keeps_values_and_prefers_least_similar():
    cfg = _v3_config()
    cfg.generation.realization_styles = ["imperative"]
    cfg.generation.paraphrase_candidates = 3
    llm = _RealizeLLM([
        "List the blocked accounts owned by person 42.",
        "Show every blocked account that person 42 holds.",
        "List blocked accounts of a person.",  # drops the value -> rejected
    ])
    pipeline = PipeCypherPipeline(
        config=cfg, schema=finbench_reference_schema(), client=_ParamClient([], set()), llm=llm, judge=DeterministicJudge()
    )
    from pipecypher.text_metrics import tokenize

    pipeline.accepted_question_tokens["simple_retrieval"] = [tokenize("List the blocked accounts owned by person 7.")]
    question, status = pipeline.realize_question("Which blocked accounts does person 42 own?", ["42"], "simple_retrieval")
    assert question == "Show every blocked account that person 42 holds."
    assert status == "realized:imperative"


def test_v3_config_fields_validate():
    cfg = _v3_config()
    cfg.generation.realization_styles = ["terse_analyst", "keyword"]
    assert validate_config(cfg) == [] or all("schema_path" in e or "path" in e for e in validate_config(cfg))


# ---------------------------------------------------------------- spend ledger
def test_ledger_pauses_at_cap_and_resumes_when_cap_raised(tmp_path, monkeypatch):
    ledger_path = tmp_path / "spend.jsonl"
    ledger_path.write_text(json.dumps({"cost_usd": 1.0}) + "\n")
    monkeypatch.setenv("PIPE_CYPHER_PAUSE_ON_CAP", "1")
    monkeypatch.setenv("PIPE_CYPHER_PAUSE_POLL_SEC", "0.05")
    ledger = SpendLedger(str(ledger_path), max_cost_usd=0.5)
    done = threading.Event()

    def worker():
        ledger.check()
        done.set()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    time.sleep(0.3)
    assert not done.is_set()
    assert Path(f"{ledger_path}.paused").exists()
    Path(f"{ledger_path}.cap").write_text("2.0")
    thread.join(timeout=2)
    assert done.is_set()
    assert not Path(f"{ledger_path}.paused").exists()


def test_ledger_still_raises_without_pause(tmp_path, monkeypatch):
    ledger_path = tmp_path / "spend.jsonl"
    ledger_path.write_text(json.dumps({"cost_usd": 1.0}) + "\n")
    monkeypatch.delenv("PIPE_CYPHER_PAUSE_ON_CAP", raising=False)
    with pytest.raises(BudgetExceededError):
        SpendLedger(str(ledger_path), max_cost_usd=0.5).check()


# ---------------------------------------------------------------- end to end (scripted LLM)
class _ScriptedLLM:
    """Returns v3 templates, realizations, and Cypher based on the prompt text."""

    model = "scripted-glm"

    def chat_json(self, **kwargs):
        user = kwargs["user"]
        if "Generate 4 diverse question templates" in user or "question templates for the category" in user:
            return [
                {
                    "template": "Which accounts does the person with id {person} own?",
                    "slots": {"person": "Person.personId"},
                    "cypher": "MATCH (p:Person)-[:OWN_ACCOUNT]->(a:Account) WHERE p.personId = $person "
                    "RETURN DISTINCT a.accountId AS accountId, a.accountType AS accountType, a.isBlocked AS isBlocked",
                    "rationale": "one hop",
                },
                {"template": "Which {k} accounts are largest?", "slots": {}, "cypher": "MATCH (a:Account) RETURN a", "rationale": "bad"},
            ]
        if "Rewrite an analyst question" in user:
            question = user.rsplit("Question: ", 1)[1].strip()
            return {"paraphrases": [question.replace("Which accounts does", "List the accounts that"), question]}
        return []

    def chat(self, **kwargs):
        user = kwargs["user"]
        if "Generate a read-only Cypher statement" in user:
            question = user.rsplit("Question:", 1)[1]
            person = __import__("re").search(r"id (\d+)", question).group(1)
            return ChatResponse(
                text=f"MATCH (p:Person)-[:OWN_ACCOUNT]->(a:Account) WHERE p.personId = '{person}' "
                "RETURN DISTINCT a.accountId AS accountId, a.accountType AS accountType, a.isBlocked AS isBlocked",
                raw={},
            )
        return ChatResponse(text="", raw={})


class _GraphClient:
    owners = {"101": ["A1"], "102": [], "103": ["A3", "A4"]}

    def run(self, query, params=None, *, read_only=True, limit_rows=None):
        import re

        if params:
            accounts = self.owners.get(str(params.get("person")), [])
            return ExecutionResult(success=True, rows=[{"accountId": a, "accountType": "debit card", "isBlocked": False} for a in accounts])
        if "AS person" in query:
            return ExecutionResult(success=True, rows=[{"person": p} for p in self.owners])
        match = re.search(r"personId = '(\d+)'", query)
        if match:
            accounts = self.owners.get(match.group(1), [])
            return ExecutionResult(success=True, rows=[{"accountId": a, "accountType": "debit card", "isBlocked": False} for a in accounts])
        return ExecutionResult(success=True, rows=[])


def test_v3_end_to_end_with_scripted_llm(tmp_path):
    cfg = _v3_config()
    gen = cfg.generation
    gen.categories = ["simple_retrieval"]
    gen.target_per_category = 2
    gen.template_source = "llm"
    gen.template_candidates = 4
    gen.question_paraphrase = True
    gen.realization_styles = ["imperative"]
    gen.paraphrase_candidates = 2
    gen.max_entity_pct = 1.0
    gen.template_cypher_fallback = True
    gen.prompt_profile = "full_pipe_cypher_governed_v3"
    gen.difficulty_model_path = str(Path(__file__).resolve().parents[1] / "configs" / "difficulty_v3.json")
    # One hop plus three returned columns (two are policy context columns) scores "medium".
    gen.tier_quotas = {"_default": {"easy": 0.0, "medium": 1.0, "hard": 0.0}}
    pipeline = PipeCypherPipeline(
        config=cfg, schema=finbench_reference_schema(), client=_GraphClient(), llm=_ScriptedLLM(), judge=_CountingJudge()
    )
    result = pipeline.run(tmp_path / "records.jsonl")
    accepted = [r for r in result.records if r.accepted]
    assert len(accepted) == 2, [r.judge.failure_reason for r in result.records]
    assert {r.entity_values[0] for r in accepted} == {"101", "103"}  # 102 owns nothing: never bound
    meta = accepted[0].generation_metadata
    assert meta["binding"]["verified"] is True
    assert meta["question_realization"].startswith("realized:")
    assert meta["template_cypher_agreement"] is True
    assert meta["difficulty_tier"] == "medium"
    assert accepted[0].question.startswith("List the accounts that")
    assert result.attempt_summary["template_rejections"]
    templates_log = (tmp_path / "records.templates.jsonl").read_text().splitlines()
    assert any('"status": "rejected"' in line for line in templates_log)


def test_literal_gate_ignores_apostrophes():
    question = "I'd like to see the accounts that person 42 owns; don't include the owners' names."
    cypher = "MATCH (p:Person {personId: 42})-[:OWN_ACCOUNT]->(a:Account) RETURN DISTINCT a.accountId"
    assert literal_consistency_problems(question, cypher, [42]) == []
    assert literal_consistency_problems("Which accounts have type 'credit card'?", "MATCH (a:Account) RETURN a.accountId", []) != []


def test_slot_free_template_must_answer_itself():
    class _Empty:
        def run(self, query, params=None, *, read_only=True, limit_rows=None):
            return ExecutionResult(success=True, rows=[])

    pipeline = PipeCypherPipeline(
        config=_v3_config(), schema=finbench_reference_schema(), client=_Empty(), llm=NullLLM(), judge=DeterministicJudge()
    )
    item = {
        "template": "Which accounts are blocked?",
        "slots": {},
        "cypher": "MATCH (a:Account) WHERE a.isBlocked = true RETURN DISTINCT a.accountId AS accountId, "
        "a.accountType AS accountType, a.isBlocked AS isBlocked",
    }
    assert pipeline._template_from_item(item, "simple_retrieval", {"template_origin": "llm"}) is None
    assert any("returns no rows" in key for key in pipeline.template_rejections)


def test_slot_free_template_retired_after_one_gate_failure():
    pipeline = PipeCypherPipeline(
        config=_v3_config(), schema=finbench_reference_schema(), client=_ParamClient([], set()), llm=NullLLM(), judge=DeterministicJudge()
    )
    template = TemplateCandidate(template="Which 10 accounts sent the most transfers?", category="ranking_topk", slots={})
    record = pipeline.run_candidate.__self__  # noqa: F841 (pipeline reference)
    from pipecypher.models import GenerationRecord, ValidationResult

    rejected = GenerationRecord(
        question=template.template, cypher="MATCH (a) RETURN a", category="ranking_topk", graph_profile="finbench",
        accepted=False, validation=ValidationResult(True, True, True, "MATCH (a) RETURN a"),
        execution=ExecutionResult(success=True, rows=[{"a": 1}]),
        judge=JudgeResult.failed("reference has a tie at the ORDER BY/LIMIT boundary (rank 10 and rank 11 share the order key)"),
    )
    summary: dict = {}
    pipeline._retire_on_repeated_gate_failure(template, rejected, summary)
    assert pipeline._template_identity(template) in pipeline.saturated_templates
    assert summary["templates_retired_by_gates"] == 1


def test_identifier_tiebreak_is_stripped_unless_question_asks():
    from pipecypher.pipeline import _strip_identifier_tiebreak

    cypher = "MATCH (c:Company) RETURN c.id AS companyId, count(*) AS n ORDER BY n DESC, c.id ASC LIMIT 1"
    assert _strip_identifier_tiebreak(cypher, "Which company has the most employees?") == (
        "MATCH (c:Company) RETURN c.id AS companyId, count(*) AS n ORDER BY n DESC LIMIT 1"
    )
    assert _strip_identifier_tiebreak(cypher, "Top company by employees, then by id?") == cypher
    plain = "MATCH (c:Company) RETURN c.id, count(*) AS n ORDER BY n DESC LIMIT 1"
    assert _strip_identifier_tiebreak(plain, "Which company has the most employees?") == plain


def test_category_contract_for_boolean_and_ranking():
    pipeline = PipeCypherPipeline(
        config=_v3_config(), schema=finbench_reference_schema(), client=_ParamClient([], set()), llm=NullLLM(), judge=DeterministicJudge()
    )
    pipeline._active_category = "boolean_existence"
    listing = ExecutionResult(success=True, rows=[{"loanId": "1"}, {"loanId": "2"}])
    assert "yes/no" in pipeline._category_contract_problem("MATCH (l:Loan) RETURN l.loanId", listing)
    yes = ExecutionResult(success=True, rows=[{"has": True}])
    assert pipeline._category_contract_problem("MATCH (l:Loan) RETURN count(l) > 0 AS has", yes) is None
    pipeline._active_category = "ranking_topk"
    assert "ORDER BY" in pipeline._category_contract_problem("MATCH (a:Account) RETURN a.accountId", yes)


class _TruncatingLLM:
    """First template call returns truncated JSON (reasoning ate the budget)."""

    model = "fake"

    def __init__(self):
        self.budgets = []

    def chat_json(self, **kwargs):
        self.budgets.append(kwargs["max_tokens"])
        if len(self.budgets) == 1:
            return json.loads('[{"template": "Which blocked accounts')
        return [dict(_TEMPLATE_ITEM)]


def test_template_calls_get_headroom_and_truncation_is_retried():
    cfg = _v3_config()
    cfg.generation.template_source = "llm"
    cfg.generation.allow_seed_template_fallback = False
    llm = _TruncatingLLM()
    pipeline = PipeCypherPipeline(
        config=cfg, schema=finbench_reference_schema(), client=_ParamClient([], set()), llm=llm, judge=DeterministicJudge()
    )
    templates = pipeline.generate_templates("simple_retrieval")
    assert llm.budgets == [cfg.models.max_tokens * 3, cfg.models.max_tokens * 4]
    assert [t.template for t in templates] == [_TEMPLATE_ITEM["template"]]


def test_id_slot_after_named_id_property_is_not_relabelled():
    from pipecypher.pipeline import _phrase_id_slot

    q = "Which accounts does the company with companyId {company} own?"
    assert _phrase_id_slot(q, "company", "Company.companyId", "42") == q
    q2 = "How many people does {person} know?"
    assert _phrase_id_slot(q2, "person", "Person.id", "6") == "How many people does person with id 6 know?"


def test_predicted_cypher_drops_end_of_turn_marker():
    from pipecypher.text2cypher import clean_predicted_cypher

    raw = "MATCH (a:Account)-[:TRANSFER_TO]->(b:Account) RETURN count(distinct b) AS n<end_of_turn>"
    assert clean_predicted_cypher(raw) == "MATCH (a:Account)-[:TRANSFER_TO]->(b:Account) RETURN count(distinct b) AS n"
    assert clean_predicted_cypher("MATCH (n) RETURN n<|im_end|>\nextra") == "MATCH (n) RETURN n"
