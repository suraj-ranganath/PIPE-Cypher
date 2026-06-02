from pipecypher.graph_profiles import snb_reference_schema
from pipecypher.judge import schema_slice_for_cypher
from pipecypher.prompts import JUDGE_PROMPT


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
