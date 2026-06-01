from pipecypher.config import RunConfig
from pipecypher.graph_profiles import default_templates, finbench_reference_schema
from pipecypher.judge import DeterministicJudge
from pipecypher.llm import NullLLM
from pipecypher.models import ExecutionResult
from pipecypher.pipeline import PipeCypherPipeline


class BindingCypherClient:
    def __init__(self):
        self.reverse_limit_rows = None

    def run(self, query, params=None, *, read_only=True, limit_rows=None):
        if "RETURN DISTINCT p.personName AS personName" in query:
            self.reverse_limit_rows = limit_rows
            return ExecutionResult(success=True, rows=[{"personName": "Bertrand"}])
        return ExecutionResult(
            success=True,
            rows=[{"AccountId": "acct-1", "AccountType": "checking", "IsBlocked": False}],
        )


class MultiBindingCypherClient:
    def run(self, query, params=None, *, read_only=True, limit_rows=None):
        if "RETURN DISTINCT p.personName AS personName" in query:
            return ExecutionResult(
                success=True,
                rows=[{"personName": "Bertrand"}, {"personName": "Chong"}],
            )
        return ExecutionResult(success=True, rows=[{"AccountId": "acct-1"}])


class ObjectBindingCypherClient:
    def run(self, query, params=None, *, read_only=True, limit_rows=None):
        if "RETURN DISTINCT p.personName AS personName" in query:
            return ExecutionResult(success=True, rows=[{"personName": object()}])
        if "slot0:Person" in query:
            return ExecutionResult(success=True, rows=[{"personName": "Bertrand"}])
        return ExecutionResult(success=True, rows=[{"AccountId": "acct-1"}])


def test_pipeline_uses_bound_slot_in_question_and_fallback_cypher():
    cfg = RunConfig()
    cfg.generation.template_source = "default"
    cfg.generation.repair_attempts = 0
    cfg.generation.generated_query_limit = 7
    client = BindingCypherClient()
    pipeline = PipeCypherPipeline(
        config=cfg,
        schema=finbench_reference_schema(),
        client=client,
        llm=NullLLM(),
        judge=DeterministicJudge(),
    )
    template = next(
        item
        for item in default_templates("finbench")
        if item.category == "simple_retrieval"
    )

    record = pipeline.run_candidate(template)

    assert record.accepted
    assert "Bertrand" in record.question
    assert "{personName: 'Bertrand'}" in record.cypher
    assert "$personName" not in (record.reverse_cypher or "")
    assert client.reverse_limit_rows == 7


def test_pipeline_cycles_slot_bindings_for_repeated_seed_template():
    cfg = RunConfig()
    cfg.generation.template_source = "default"
    cfg.generation.repair_attempts = 0
    pipeline = PipeCypherPipeline(
        config=cfg,
        schema=finbench_reference_schema(),
        client=MultiBindingCypherClient(),
        llm=NullLLM(),
        judge=DeterministicJudge(),
    )
    template = next(
        item
        for item in default_templates("finbench")
        if item.category == "simple_retrieval"
    )

    first = pipeline.run_candidate(template)
    second = pipeline.run_candidate(template)

    assert "Bertrand" in first.question
    assert "Chong" in second.question


def test_pipeline_skips_seen_slot_bindings_from_previous_runs():
    cfg = RunConfig()
    cfg.generation.template_source = "default"
    cfg.generation.repair_attempts = 0
    template = next(
        item
        for item in default_templates("finbench")
        if item.category == "simple_retrieval"
    )
    seen_question = "Which accounts are owned by person 'Bertrand'?"
    pipeline = PipeCypherPipeline(
        config=cfg,
        schema=finbench_reference_schema(),
        client=MultiBindingCypherClient(),
        llm=NullLLM(),
        judge=DeterministicJudge(),
        seen_question_keys={PipeCypherPipeline._question_key(template.category, seen_question)},
    )

    record = pipeline.run_candidate(template)

    assert "Chong" in record.question


def test_pipeline_rejects_object_slot_bindings_and_uses_generic_scalar_fallback():
    cfg = RunConfig()
    cfg.generation.template_source = "default"
    cfg.generation.repair_attempts = 0
    pipeline = PipeCypherPipeline(
        config=cfg,
        schema=finbench_reference_schema(),
        client=ObjectBindingCypherClient(),
        llm=NullLLM(),
        judge=DeterministicJudge(),
    )
    template = next(
        item
        for item in default_templates("finbench")
        if item.category == "simple_retrieval"
    )

    record = pipeline.run_candidate(template)

    assert "Bertrand" in record.question
    assert "<object object" not in record.question


def test_pipeline_adds_grounded_mentions_to_prompt_hints():
    cfg = RunConfig()
    pipeline = PipeCypherPipeline(
        config=cfg,
        schema=finbench_reference_schema(),
        client=BindingCypherClient(),
        llm=NullLLM(),
        judge=DeterministicJudge(),
    )

    hints = pipeline._entity_prompt_hints(
        "Which accounts are owned by person 'Bertrand'?",
        {"personName": "Bertrand | Person.personName"},
    )

    assert hints["personName"] == "Bertrand | Person.personName"
    assert hints["_grounded_mentions"][0]["canonical_value"] == "Bertrand"
    assert hints["_grounded_mentions"][0]["schema_path"] == "Person.personName"
    assert "(Person.personName: Bertrand)" in hints["_annotated_question"]
