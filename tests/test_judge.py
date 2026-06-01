from pipecypher.graph_profiles import snb_reference_schema
from pipecypher.judge import schema_slice_for_cypher


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
