"""Benchmark v2 generation controls: signature quotas, template induction,
LLM-template retention in mixed mode, question paraphrase guards, the
unordered-LIMIT truncation gate, and the symmetric-relationship policy."""

from __future__ import annotations

from pathlib import Path

from pipecypher.config import RunConfig, validate_config
from pipecypher.graph_profiles import default_cypher_for_template, finbench_reference_schema, snb_reference_schema
from pipecypher.judge import DeterministicJudge
from pipecypher.llm import ChatResponse, NullLLM
from pipecypher.models import ExecutionResult, GenerationRecord, JudgeResult, TemplateCandidate
from pipecypher.pipeline import PipeCypherPipeline
from pipecypher.validator import validate_cypher


def _pipeline(cfg: RunConfig, *, llm=None, client=None, schema=None) -> PipeCypherPipeline:
    return PipeCypherPipeline(
        config=cfg,
        schema=schema or finbench_reference_schema(),
        client=client or _RowsClient(),
        llm=llm or NullLLM(),
        judge=DeterministicJudge(),
    )


class _RowsClient:
    def __init__(self, rows=None, full_rows=None):
        self.rows = rows or [{"n": 1}]
        self.full_rows = full_rows
        self.calls: list[tuple[str, object]] = []

    def run(self, query, params=None, *, read_only=True, limit_rows=None):
        self.calls.append((query, limit_rows))
        if limit_rows is None and self.full_rows is not None:
            return ExecutionResult(success=True, rows=self.full_rows)
        return ExecutionResult(success=True, rows=self.rows)


def _record_for(template: TemplateCandidate, cypher: str, question: str) -> GenerationRecord:
    from pipecypher.diversity_metrics import canonical_query_signature

    return GenerationRecord(
        question=question,
        cypher=cypher,
        category=template.category,
        graph_profile="finbench",
        accepted=True,
        validation=validate_cypher(cypher, finbench_reference_schema()),
        execution=ExecutionResult(success=True, rows=[{"n": 1}]),
        judge=JudgeResult(True, 0.0, 1.0, 1.0, "easy"),
        generation_metadata={"query_signature": canonical_query_signature(cypher)},
    )


def test_signature_quota_rejects_and_saturates_template(tmp_path: Path):
    cfg = RunConfig()
    cfg.generation.categories = ["simple_retrieval"]
    cfg.generation.target_per_category = 5
    cfg.generation.template_source = "default"
    cfg.generation.max_entity_pct = 1.0
    cfg.generation.max_examples_per_signature = 2
    pipeline = _pipeline(cfg)
    counter = {"i": 0}

    def fake_templates(category):
        return [TemplateCandidate(template="Which accounts does {p} own?", category=category, slots={"p": "Person.personName"})]

    def fake_run(template):
        counter["i"] += 1
        cypher = (
            f"MATCH (p:Person {{personName: 'n{counter['i']}'}})-[:OWN_ACCOUNT]->(a:Account) "
            "RETURN DISTINCT a.accountId AS AccountId"
        )
        return _record_for(template, cypher, f"Which accounts does n{counter['i']} own?")

    pipeline.generate_templates = fake_templates
    pipeline.run_candidate = fake_run
    result = pipeline.run(tmp_path / "records.jsonl")
    accepted = [r for r in result.records if r.accepted]
    assert len(accepted) == 2  # quota caps the single signature
    summary = result.attempt_summary["by_category"]["simple_retrieval"]
    assert summary["unique_accepted_signatures"] == 1
    assert summary["no_reusable_template_break"] is True


def test_template_induction_adds_new_structures_when_saturated(tmp_path: Path):
    cfg = RunConfig()
    cfg.generation.categories = ["simple_retrieval"]
    cfg.generation.target_per_category = 4
    cfg.generation.template_source = "mixed"
    cfg.generation.max_entity_pct = 1.0
    cfg.generation.max_examples_per_signature = 2
    cfg.generation.template_induction_rounds = 1
    pipeline = _pipeline(cfg)
    counter = {"i": 0}

    def fake_templates(category):
        return [TemplateCandidate(template="Which accounts does {p} own?", category=category, slots={"p": "Person.personName"})]

    def fake_induce(category, existing, *, round_index):
        return [
            TemplateCandidate(
                template="Which loans did {p} apply for?",
                category=category,
                slots={"p": "Person.personName"},
                metadata={"template_origin": "llm_induced", "induction_round": round_index},
            )
        ]

    def fake_run(template):
        counter["i"] += 1
        rel = "APPLY_LOAN]->(x:Loan) RETURN DISTINCT x.loanId AS LoanId" if "loans" in template.template else "OWN_ACCOUNT]->(x:Account) RETURN DISTINCT x.accountId AS AccountId"
        cypher = f"MATCH (p:Person {{personName: 'n{counter['i']}'}})-[:{rel}"
        return _record_for(template, cypher, f"{template.template} n{counter['i']}")

    pipeline.generate_templates = fake_templates
    pipeline.induce_templates = fake_induce
    pipeline.run_candidate = fake_run
    result = pipeline.run(tmp_path / "records.jsonl")
    summary = result.attempt_summary["by_category"]["simple_retrieval"]
    assert summary["induced_templates"] == 1
    assert summary["induction_rounds"] == 1
    assert summary["accepted"] == 4
    assert summary["unique_accepted_signatures"] == 2


def test_mixed_mode_keeps_llm_templates_when_enabled():
    class TemplateLLM(NullLLM):
        model = "stub"

        def chat_json(self, **_):
            return [{"template": f"LLM template {i} for {{p}}?", "slots": {"p": "Person.personName"}} for i in range(5)]

    cfg = RunConfig()
    cfg.generation.template_source = "mixed"
    cfg.generation.template_candidates = 2
    legacy = _pipeline(cfg, llm=TemplateLLM()).generate_templates("simple_retrieval")
    cfg.generation.mixed_keep_llm_templates = True
    kept = _pipeline(cfg, llm=TemplateLLM()).generate_templates("simple_retrieval")
    llm_kept = [t for t in kept if t.metadata.get("template_origin") == "llm"]
    llm_legacy = [t for t in legacy if t.metadata.get("template_origin") == "llm"]
    assert len(llm_kept) == 5
    assert len(llm_kept) > len(llm_legacy)


def test_paraphrase_keeps_template_question_when_value_is_dropped():
    class ParaphraseLLM(NullLLM):
        def __init__(self, text):
            self.text = text

        def chat(self, **_):
            return ChatResponse(text=self.text, raw={})

    cfg = RunConfig()
    ok = _pipeline(cfg, llm=ParaphraseLLM("List every account that 'Gibbs' owns."))
    assert ok.paraphrase_question("Which accounts are owned by person 'Gibbs'?", ["'Gibbs'"]) == (
        "List every account that 'Gibbs' owns.",
        "paraphrased",
    )
    bad = _pipeline(cfg, llm=ParaphraseLLM("List every account that Gibs owns."))
    question, status = bad.paraphrase_question("Which accounts are owned by person 'Gibbs'?", ["'Gibbs'"])
    assert question == "Which accounts are owned by person 'Gibbs'?"
    assert status == "paraphrase_dropped_value"


def test_truncated_unordered_limit_gate():
    cfg = RunConfig()
    cfg.generation.reject_truncated_unordered_limit = True
    truncated = _pipeline(cfg, client=_RowsClient(full_rows=[{"a": i} for i in range(3)]))
    assert truncated._truncated_by_unordered_limit("MATCH (a:Account) RETURN DISTINCT a.accountId AS A LIMIT 3")
    complete = _pipeline(cfg, client=_RowsClient(full_rows=[{"a": 1}]))
    assert not complete._truncated_by_unordered_limit("MATCH (a:Account) RETURN DISTINCT a.accountId AS A LIMIT 3")
    assert not truncated._truncated_by_unordered_limit(
        "MATCH (a:Account) RETURN DISTINCT a.accountId AS A ORDER BY A LIMIT 3"
    )


def test_symmetric_relationship_policy_allows_undirected_knows_only():
    schema = snb_reference_schema()
    query = "MATCH (a:Person {id: 1})-[:KNOWS*1..2]-(b:Person) RETURN DISTINCT b.id AS PersonId"
    assert "undirected_relationship" in {i.code for i in validate_cypher(query, schema).errors}
    schema.symmetric_relationships = ["KNOWS"]
    assert validate_cypher(query, schema).ok
    other = "MATCH (p:Person)-[:LIKES]-(m:Post) RETURN DISTINCT m.id AS PostId"
    assert "undirected_relationship" in {i.code for i in validate_cypher(other, schema).errors}


def test_knows_seed_cypher_follows_symmetric_policy():
    template = TemplateCandidate(
        template="Which people are within two knows hops of person {personId}?",
        category="path_temporal",
        slots={"personId": "Person.id"},
    )
    directed = default_cypher_for_template(template, bindings={"personId": 7}, schema=snb_reference_schema())
    assert "-[:KNOWS*1..2]->" in directed
    schema = snb_reference_schema()
    schema.symmetric_relationships = ["KNOWS"]
    undirected = default_cypher_for_template(template, bindings={"personId": 7}, schema=schema)
    assert "-[:KNOWS*1..2]-(dst:Person)" in undirected


def test_pipeline_merges_configured_symmetric_relationships():
    cfg = RunConfig()
    cfg.generation.symmetric_relationships = ["KNOWS"]
    pipeline = _pipeline(cfg, schema=snb_reference_schema())
    assert pipeline.schema.symmetric_relationships == ["KNOWS"]


def test_v2_config_validation():
    cfg = RunConfig()
    cfg.generation.template_source = "default"
    cfg.generation.template_induction_rounds = 2
    cfg.generation.max_examples_per_signature = -1
    errors = validate_config(cfg)
    assert any("template_induction_rounds requires" in e for e in errors)
    assert any("max_examples_per_signature" in e for e in errors)


def _example(i: int, sig: str, category: str = "simple_retrieval") -> dict:
    return {
        "id": f"pc_{i:04d}",
        "graph_profile": "finbench",
        "category": category,
        "question": f"q{i}",
        "cypher": f"MATCH (n) RETURN n.{sig}",
        "query_signature": sig,
    }


def test_signature_disjoint_split_has_no_shared_signatures():
    from pipecypher.benchmark_export import assign_splits, split_signature_overlap

    examples = [_example(i, f"s{i % 20}") for i in range(200)]
    splits = assign_splits(examples, strategy="signature_disjoint")
    overlap = split_signature_overlap(splits)
    assert overlap["test_rows_sharing_train_signature"] == 0
    assert overlap["dev_rows_sharing_train_signature"] == 0
    assert splits["test"] and splits["dev"] and splits["train"]
    assert sum(len(rows) for rows in splits.values()) == 200


def test_signature_disjoint_split_keeps_low_signature_cells_in_train():
    from pipecypher.benchmark_export import assign_splits, export_stats

    examples = [_example(i, f"s{i % 2}", category="ranking_topk") for i in range(20)]
    splits = assign_splits(examples, strategy="signature_disjoint")
    assert len(splits["train"]) == 20
    stats = export_stats(examples, splits)
    assert stats["signature_split_cells_train_only"] == ["finbench::ranking_topk"]


def test_answer_contract_separates_policy_context_columns():
    from pipecypher.benchmark_export import answer_contract

    cypher = (
        "MATCH (p:Person {personName: 'x'})-[:OWN_ACCOUNT]->(a:Account) "
        "RETURN DISTINCT a.accountId AS AccountId, a.accountType AS AccountType, a.isBlocked AS IsBlocked"
    )
    contract = answer_contract(cypher, [{"AccountId": "1", "AccountType": "t", "IsBlocked": False}])
    assert contract["answer_columns"] == ["AccountId"]
    assert contract["context_columns"] == ["AccountType", "IsBlocked"]


def test_id_slots_are_phrased_with_their_label():
    from pipecypher.pipeline import _phrase_id_slot

    assert _phrase_id_slot("How many people does {p} know?", "p", "Person.id", "6") == (
        "How many people does person with id 6 know?"
    )
    assert _phrase_id_slot("Has person {p} liked a post?", "p", "Person.id", "6") == "Has person with id 6 liked a post?"
    assert _phrase_id_slot("Does person with id {p} exist?", "p", "Person.id", "6") == "Does person with id {p} exist?"
    assert _phrase_id_slot("Posts tagged {t}?", "t", "Tag.name", "X") == "Posts tagged {t}?"


def test_export_signature_cap_is_deterministic_and_global():
    from pipecypher.benchmark_export import cap_examples_per_signature

    examples = [_example(i, "s0") for i in range(12)] + [_example(100 + i, "s1") for i in range(3)]
    kept, dropped = cap_examples_per_signature(examples, 8)
    assert dropped == 4 and len(kept) == 11
    again, _ = cap_examples_per_signature(list(reversed(examples)), 8)
    assert [r["id"] for r in again] == [r["id"] for r in kept]


def test_export_cell_cap_per_graph_round_robin():
    from pipecypher.benchmark_export import cap_examples_per_cell

    rows = [dict(_example(i, f"s{i % 3}"), graph_profile="snb") for i in range(30)]
    rows += [dict(_example(100 + i, "t0"), graph_profile="finbench") for i in range(30)]
    kept, dropped = cap_examples_per_cell(rows, {"snb": 9, "finbench": 25})
    snb = [r for r in kept if r["graph_profile"] == "snb"]
    assert len(snb) == 9 and {r["query_signature"] for r in snb} == {"s0", "s1", "s2"}
    assert len([r for r in kept if r["graph_profile"] == "finbench"]) == 25
    assert dropped == 26


def test_judge_schema_slice_keeps_symmetric_relationships():
    from pipecypher.judge import schema_slice_for_cypher

    schema = snb_reference_schema()
    schema.symmetric_relationships = ["KNOWS"]
    sliced = schema_slice_for_cypher(schema, "MATCH (a:Person)-[:KNOWS]-(b:Person) RETURN DISTINCT b.id AS id")
    assert sliced.symmetric_relationships == ["KNOWS"]
    assert "Symmetric relationship types" in sliced.to_prompt()


def test_limit_boundary_tie_gate_rejects_tied_reference():
    cfg = RunConfig()
    cfg.generation.reject_limit_boundary_ties = True
    query = (
        "MATCH (l:Loan) RETURN DISTINCT l.loanId AS loanId, l.balance AS balance "
        "ORDER BY balance DESC LIMIT 1"
    )
    tied = _pipeline(cfg, client=_RowsClient(
        rows=[{"loanId": "a", "balance": 5}],
        full_rows=[{"loanId": "a", "balance": 5}, {"loanId": "b", "balance": 5}],
    ))
    *_, judge_result, _ = tied._evaluate_cypher(question="Which loan has the highest balance?", cypher=query)
    assert not judge_result.passed
    assert "tie at the ORDER BY/LIMIT boundary" in judge_result.failure_reason
    clean = _pipeline(cfg, client=_RowsClient(
        rows=[{"loanId": "a", "balance": 5}],
        full_rows=[{"loanId": "a", "balance": 5}, {"loanId": "b", "balance": 4}],
    ))
    *_, judge_result, _ = clean._evaluate_cypher(question="Which loan has the highest balance?", cypher=query)
    assert judge_result.passed


def test_rank_slot_bound_rejects_entity_id_as_k():
    cfg = RunConfig()
    pipeline = _pipeline(cfg)
    assert pipeline._is_valid_slot_binding("k", "175358910490739502")  # off by default (v1/v2 behaviour)
    cfg.generation.max_rank_slot_value = 100
    assert not pipeline._is_valid_slot_binding("k", "175358910490739502")
    assert not pipeline._is_valid_slot_binding("k", 4828140275517884106)
    assert not pipeline._is_valid_slot_binding("top_k", 0)
    assert pipeline._is_valid_slot_binding("k", 5)
    assert pipeline._is_valid_slot_binding("k", "10")
    assert pipeline._is_valid_slot_binding("accountId", "175358910490739502")
