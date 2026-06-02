from pathlib import Path

from pipecypher.config import RunConfig
from pipecypher.cypher_client import SmokeCypherClient
from pipecypher.graph_profiles import finbench_reference_schema
from pipecypher.schema import load_schema
from pipecypher.judge import DeterministicJudge
from pipecypher.llm import NullLLM
from pipecypher.pipeline import PipeCypherPipeline


def test_pipeline_offline_smoke(tmp_path: Path):
    cfg = RunConfig()
    cfg.generation.categories = ["simple_retrieval", "ranking_topk"]
    cfg.generation.target_per_category = 1
    cfg.generation.require_non_empty = True
    pipeline = PipeCypherPipeline(
        config=cfg,
        schema=finbench_reference_schema(),
        client=SmokeCypherClient(),
        llm=NullLLM(),
        judge=DeterministicJudge(),
    )
    result = pipeline.run(tmp_path / "records.jsonl")
    assert result.output_path.exists()
    assert len(result.records) >= 2
    assert any(record.accepted for record in result.records)


def test_pipeline_tries_templates_in_order_before_reuse(tmp_path: Path):
    cfg = RunConfig()
    cfg.generation.categories = ["simple_retrieval"]
    cfg.generation.target_per_category = 2
    cfg.generation.template_source = "default"
    cfg.generation.max_entity_pct = 1.0
    pipeline = PipeCypherPipeline(
        config=cfg,
        schema=finbench_reference_schema(),
        client=SmokeCypherClient(),
        llm=NullLLM(),
        judge=DeterministicJudge(),
    )

    seen = []

    def fake_generate_templates(category):
        from pipecypher.models import TemplateCandidate

        return [
            TemplateCandidate(template="First template?", category=category),
            TemplateCandidate(template="Second template?", category=category),
        ]

    def fake_run_candidate(template):
        seen.append(template.template)
        from pipecypher.models import ExecutionResult, GenerationRecord, JudgeResult
        from pipecypher.validator import validate_cypher

        cypher = "MATCH (n) RETURN DISTINCT n LIMIT 1"
        return GenerationRecord(
            question=template.template,
            cypher=cypher,
            category=template.category,
            graph_profile="finbench",
            accepted=True,
            validation=validate_cypher(cypher, finbench_reference_schema()),
            execution=ExecutionResult(success=True, rows=[{"n": 1}]),
            judge=JudgeResult(True, 0.0, 1.0, 1.0, "easy"),
        )

    pipeline.generate_templates = fake_generate_templates
    pipeline.run_candidate = fake_run_candidate

    pipeline.run(tmp_path / "records.jsonl")

    assert seen[:2] == ["First template?", "Second template?"]


def test_pipeline_random_seed_makes_template_reuse_deterministic(tmp_path: Path):
    def run_with_seed(seed: int) -> list[str]:
        cfg = RunConfig()
        cfg.generation.categories = ["simple_retrieval"]
        cfg.generation.target_per_category = 5
        cfg.generation.random_seed = seed
        cfg.generation.max_entity_pct = 1.0
        pipeline = PipeCypherPipeline(
            config=cfg,
            schema=finbench_reference_schema(),
            client=SmokeCypherClient(),
            llm=NullLLM(),
            judge=DeterministicJudge(),
        )

        from pipecypher.models import TemplateCandidate

        templates = [
            TemplateCandidate(template="Template A?", category="simple_retrieval", slots={"a": "Account.accountId"}),
            TemplateCandidate(template="Template B?", category="simple_retrieval", slots={"b": "Account.accountId"}),
        ]
        seen = []

        def fake_generate_templates(category):
            return templates

        def fake_run_candidate(template):
            from pipecypher.models import ExecutionResult, GenerationRecord, JudgeResult
            from pipecypher.validator import validate_cypher

            seen.append(template.template)
            cypher = "MATCH (n) RETURN DISTINCT n LIMIT 1"
            return GenerationRecord(
                question=f"{template.template} #{len(seen)}",
                cypher=cypher,
                category=template.category,
                graph_profile="finbench",
                accepted=True,
                validation=validate_cypher(cypher, finbench_reference_schema()),
                execution=ExecutionResult(success=True, rows=[{"n": 1}]),
                judge=JudgeResult(True, 0.0, 1.0, 1.0, "easy"),
            )

        pipeline.generate_templates = fake_generate_templates
        pipeline.run_candidate = fake_run_candidate
        pipeline.run(tmp_path / f"records_{seed}_{len(list(tmp_path.iterdir()))}.jsonl")
        return seen

    assert run_with_seed(17) == run_with_seed(17)


def test_pipeline_stops_after_no_slot_templates_are_exhausted(tmp_path: Path):
    cfg = RunConfig()
    cfg.generation.categories = ["ranking_topk"]
    cfg.generation.target_per_category = 2
    cfg.generation.max_entity_pct = 1.0
    pipeline = PipeCypherPipeline(
        config=cfg,
        schema=finbench_reference_schema(),
        client=SmokeCypherClient(),
        llm=NullLLM(),
        judge=DeterministicJudge(),
    )

    def fake_generate_templates(category):
        from pipecypher.models import TemplateCandidate

        return [TemplateCandidate(template="Same question?", category=category)]

    def fake_run_candidate(template):
        from pipecypher.models import ExecutionResult, GenerationRecord, JudgeResult
        from pipecypher.validator import validate_cypher

        cypher = "MATCH (n) RETURN DISTINCT n LIMIT 1"
        return GenerationRecord(
            question=template.template,
            cypher=cypher,
            category=template.category,
            graph_profile="finbench",
            accepted=True,
            validation=validate_cypher(cypher, finbench_reference_schema()),
            execution=ExecutionResult(success=True, rows=[{"n": 1}]),
            judge=JudgeResult(True, 0.0, 1.0, 1.0, "easy"),
        )

    pipeline.generate_templates = fake_generate_templates
    pipeline.run_candidate = fake_run_candidate

    result = pipeline.run(tmp_path / "records.jsonl")

    assert sum(1 for record in result.records if record.accepted) == 1
    assert len(result.records) == 1


def test_pipeline_rejects_seen_questions_from_previous_runs(tmp_path: Path):
    cfg = RunConfig()
    cfg.generation.categories = ["ranking_topk"]
    cfg.generation.target_per_category = 1
    cfg.generation.max_entity_pct = 1.0
    from pipecypher.models import TemplateCandidate
    from pipecypher.pipeline import question_key

    seen_question = "Already accepted?"
    pipeline = PipeCypherPipeline(
        config=cfg,
        schema=finbench_reference_schema(),
        client=SmokeCypherClient(),
        llm=NullLLM(),
        judge=DeterministicJudge(),
        seen_question_keys={question_key("ranking_topk", seen_question)},
    )

    def fake_generate_templates(category):
        return [TemplateCandidate(template=seen_question, category=category)]

    def fake_run_candidate(template):
        from pipecypher.models import ExecutionResult, GenerationRecord, JudgeResult
        from pipecypher.validator import validate_cypher

        cypher = "MATCH (n) RETURN DISTINCT n LIMIT 1"
        return GenerationRecord(
            question=template.template,
            cypher=cypher,
            category=template.category,
            graph_profile="finbench",
            accepted=True,
            validation=validate_cypher(cypher, finbench_reference_schema()),
            execution=ExecutionResult(success=True, rows=[{"n": 1}]),
            judge=JudgeResult(True, 0.0, 1.0, 1.0, "easy"),
        )

    pipeline.generate_templates = fake_generate_templates
    pipeline.run_candidate = fake_run_candidate

    result = pipeline.run(tmp_path / "records.jsonl")

    assert not any(record.accepted for record in result.records)
    assert any(record.judge.failure_reason == "duplicate accepted question" for record in result.records)


def test_pipeline_marks_accepted_no_slot_templates_as_exhausted():
    cfg = RunConfig()
    pipeline = PipeCypherPipeline(
        config=cfg,
        schema=finbench_reference_schema(),
        client=SmokeCypherClient(),
        llm=NullLLM(),
        judge=DeterministicJudge(),
    )

    from pipecypher.models import TemplateCandidate

    no_slot = TemplateCandidate(template="Which account sent the highest total transfer amount?", category="ranking_topk")
    slotted = TemplateCandidate(
        template="For accounts owned by person '{personName}', which account sent the highest total transfer amount?",
        category="ranking_topk",
        slots={"personName": "Person.personName"},
    )

    pipeline.accepted_question_keys.add(pipeline._question_key(no_slot.category, no_slot.template))

    assert not pipeline._can_produce_new_question(no_slot.category, no_slot)
    assert pipeline._can_produce_new_question(slotted.category, slotted)


def test_pipeline_includes_schema_derived_templates_for_enterprise_onboarding():
    cfg = RunConfig()
    cfg.generation.graph_profile = "icij_offshoreleaks"
    cfg.generation.categories = ["ranking_topk"]
    cfg.generation.template_source = "default"
    cfg.generation.template_candidates = 4
    schema = load_schema("configs/schema_icij_offshoreleaks_live.json")
    pipeline = PipeCypherPipeline(
        config=cfg,
        schema=schema,
        client=SmokeCypherClient(),
        llm=NullLLM(),
        judge=DeterministicJudge(),
    )

    templates = pipeline.generate_templates("ranking_topk")

    assert any(template.metadata.get("schema_template_kind") for template in templates)
    assert any(template.slots for template in templates)
    assert len(templates) > len(
        [
            template
            for template in templates
            if template.template in {"Which jurisdictions have the most offshore entities?", "Which officers are connected to the most offshore entities?"}
        ]
    )


def test_pipeline_marks_exhausted_schema_slot_template_without_generic_fallback(tmp_path: Path):
    from pipecypher.models import (
        ExecutionResult,
        NodeProperty,
        RelationshipPattern,
        SchemaSummary,
        TemplateCandidate,
    )
    from pipecypher.schema_templates import SCHEMA_TEMPLATE_KIND

    class OneBindingClient:
        def run(self, query, params=None, *, read_only=True, limit_rows=None):
            if "RETURN DISTINCT s.status AS startValue" in query:
                return ExecutionResult(success=True, rows=[{"startValue": "OPEN"}])
            return ExecutionResult(success=True, rows=[{"ok": 1}])

    schema = SchemaSummary(
        node_properties=[
            NodeProperty("Case", "caseId", "STRING"),
            NodeProperty("Case", "status", "STRING"),
        ],
        relationships=[RelationshipPattern("Case", "RELATED_TO", "Case", 1)],
        categorical_properties={"Case.status": ["OPEN"]},
    )
    cfg = RunConfig()
    cfg.generation.categories = ["negation_difference"]
    cfg.generation.target_per_category = 2
    cfg.generation.max_entity_pct = 1.0
    template = TemplateCandidate(
        category="negation_difference",
        template="Which case records with status '{startValue}' have no outgoing :RELATED_TO relationship to case records?",
        slots={"startValue": "Case.status"},
        metadata={
            SCHEMA_TEMPLATE_KIND: "negation_outgoing_scoped",
            "start_label": "Case",
            "end_label": "Case",
            "relationship_type": "RELATED_TO",
            "slot": "startValue",
            "slot_property": "status",
        },
    )
    pipeline = PipeCypherPipeline(
        config=cfg,
        schema=schema,
        client=OneBindingClient(),
        llm=NullLLM(),
        judge=DeterministicJudge(),
    )

    def fake_generate_templates(category):
        return [template]

    pipeline.generate_templates = fake_generate_templates

    result = pipeline.run(tmp_path / "records.jsonl")

    assert sum(record.accepted for record in result.records) == 1
    assert any(record.judge.failure_reason == "slot bindings exhausted" for record in result.records)
    assert pipeline._template_identity(template) in pipeline.exhausted_slot_templates


def test_pipeline_skips_schema_slot_template_when_no_bindings_exist(tmp_path: Path):
    from pipecypher.models import (
        ExecutionResult,
        NodeProperty,
        RelationshipPattern,
        SchemaSummary,
        TemplateCandidate,
    )
    from pipecypher.schema_templates import SCHEMA_TEMPLATE_KIND

    class EmptyBindingClient:
        def run(self, query, params=None, *, read_only=True, limit_rows=None):
            if "RETURN DISTINCT s.status AS startValue" in query:
                return ExecutionResult(success=True, rows=[])
            return ExecutionResult(success=True, rows=[{"ok": 1}])

    schema = SchemaSummary(
        node_properties=[
            NodeProperty("Case", "caseId", "STRING"),
            NodeProperty("Case", "status", "STRING"),
        ],
        relationships=[RelationshipPattern("Case", "RELATED_TO", "Case", 1)],
        categorical_properties={"Case.status": ["OPEN"]},
    )
    cfg = RunConfig()
    cfg.generation.categories = ["complex_aggregation"]
    cfg.generation.target_per_category = 1
    template = TemplateCandidate(
        category="complex_aggregation",
        template="How many distinct case records are linked from case records with status '{startValue}' through :RELATED_TO?",
        slots={"startValue": "Case.status"},
        metadata={
            SCHEMA_TEMPLATE_KIND: "count_outgoing_scoped",
            "start_label": "Case",
            "end_label": "Case",
            "relationship_type": "RELATED_TO",
            "slot": "startValue",
            "slot_property": "status",
        },
    )
    pipeline = PipeCypherPipeline(
        config=cfg,
        schema=schema,
        client=EmptyBindingClient(),
        llm=NullLLM(),
        judge=DeterministicJudge(),
    )

    pipeline.generate_templates = lambda category: [template]

    result = pipeline.run(tmp_path / "records.jsonl")

    assert not any(record.accepted for record in result.records)
    assert result.records[0].judge.failure_reason == "slot bindings unavailable"
    assert "startValue" not in result.records[0].cypher


def test_pipeline_attaches_empty_result_diagnostic(tmp_path: Path):
    class EmptyClient:
        def run(self, query, params=None, *, read_only=True, limit_rows=None):
            from pipecypher.models import ExecutionResult
            from pipecypher.validator import assert_read_only

            if read_only:
                assert_read_only(query)
            if "_prefix_count" in query:
                return ExecutionResult(success=True, rows=[{"_prefix_count": 0}])
            return ExecutionResult(success=True, rows=[])

    cfg = RunConfig()
    cfg.generation.categories = ["simple_retrieval"]
    cfg.generation.target_per_category = 1
    cfg.generation.template_source = "default"
    cfg.generation.deterministic_cypher_fallback = False
    cfg.generation.repair_attempts = 0
    cfg.generation.empty_result_diagnostics = True
    pipeline = PipeCypherPipeline(
        config=cfg,
        schema=finbench_reference_schema(),
        client=EmptyClient(),
        llm=NullLLM(),
        judge=DeterministicJudge(),
    )

    result = pipeline.run(tmp_path / "records.jsonl")

    diagnostics = [record.empty_result_diagnostic for record in result.records]
    assert any(diagnostic and diagnostic["classification"] for diagnostic in diagnostics)
