from pipecypher.graph_profiles import snb_reference_schema
from pipecypher.judge import DeterministicJudge, LLMJudge, schema_slice_for_cypher
from pipecypher.models import ExecutionResult, NodeProperty, RelationshipPattern, SchemaSummary
from pipecypher.prompts import JUDGE_PROMPT
from pipecypher.validator import validate_cypher


class _CategoricalFalseRejectLLM:
    model = "test-model"

    def chat_json(self, **_kwargs):
        return {
            "pass": False,
            "ambiguity_score": 0.0,
            "semantic_alignment_score": 0.0,
            "schema_use_score": 0.0,
            "difficulty": "easy",
            "failure_reason": (
                "The Cypher query uses 'merchant account', but the schema defines "
                "valid values as 'checking' and 'savings'."
            ),
        }


def test_schema_slice_keeps_only_query_relevant_snb_schema():
    schema = snb_reference_schema()
    sliced = schema_slice_for_cypher(
        schema,
        "MATCH (forum:Forum)-[:HAS_MEMBER]->(person:Person) "
        "RETURN DISTINCT forum.title AS ForumTitle, person.id AS PersonId LIMIT 10",
    )

    assert {"Forum", "Person"} <= sliced.labels
    assert "HAS_MEMBER" in sliced.relationship_types
    assert "Tag" not in sliced.labels
    assert len(sliced.to_prompt()) < len(schema.to_prompt())


def test_judge_prompt_does_not_treat_result_values_as_categorical_failures():
    assert "Categorical property values in the schema constrain literal values" in JUDGE_PROMPT
    assert "Do not reject because the execution sample returns a value" in JUDGE_PROMPT
    assert "result rows are observed graph outputs" in JUDGE_PROMPT


def test_llm_judge_overrides_categorical_result_value_false_rejection():
    schema = SchemaSummary(
        node_properties=[
            NodeProperty("Account", "accountId", "STRING"),
            NodeProperty("Account", "accountType", "STRING"),
        ],
        relationships=[RelationshipPattern("Account", "TRANSFER_TO", "Account")],
        categorical_properties={"Account.accountType": ["checking", "savings"]},
        graph_name="test",
    )
    cypher = (
        "MATCH (a:Account) "
        "RETURN DISTINCT a.accountId AS AccountId, a.accountType AS AccountType LIMIT 10"
    )
    validation = validate_cypher(cypher, schema)
    execution = ExecutionResult(
        success=True,
        rows=[{"AccountId": "a1", "AccountType": "merchant account"}],
    )
    judge = LLMJudge(_CategoricalFalseRejectLLM(), DeterministicJudge())

    result = judge.judge(
        question="Which accounts are present?",
        cypher=cypher,
        schema=schema,
        validation=validation,
        execution=execution,
    )

    assert result.passed
    assert result.failure_reason == ""
    assert result.raw["override"] == "categorical_result_value_guard"


def test_llm_judge_does_not_override_invalid_categorical_query_literal():
    schema = SchemaSummary(
        node_properties=[
            NodeProperty("Account", "accountId", "STRING"),
            NodeProperty("Account", "accountType", "STRING"),
        ],
        categorical_properties={"Account.accountType": ["checking", "savings"]},
        graph_name="test",
    )
    cypher = (
        "MATCH (a:Account) WHERE a.accountType = 'merchant account' "
        "RETURN DISTINCT a.accountId AS AccountId"
    )
    validation = validate_cypher(cypher, schema)
    execution = ExecutionResult(success=True, rows=[{"AccountId": "a1"}])
    judge = LLMJudge(_CategoricalFalseRejectLLM(), DeterministicJudge())

    result = judge.judge(
        question="Which merchant accounts are present?",
        cypher=cypher,
        schema=schema,
        validation=validation,
        execution=execution,
    )

    assert not validation.ok
    assert not result.passed
    assert "override" not in result.raw
