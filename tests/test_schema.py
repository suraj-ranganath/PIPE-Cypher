from pipecypher.graph_profiles import finbench_reference_schema, snb_reference_schema
from pipecypher.models import SchemaSummary


def test_schema_round_trip_dict():
    schema = finbench_reference_schema()
    loaded = SchemaSummary.from_dict(schema.to_dict())
    assert loaded.graph_name == schema.graph_name
    assert "Person" in loaded.labels
    assert loaded.has_relationship("Person", "OWN_ACCOUNT", "Account")


def test_schema_prompt_contains_relationships_and_properties():
    prompt = finbench_reference_schema().to_prompt()
    assert "(:Person)-[:OWN_ACCOUNT]->(:Account)" in prompt
    assert ":Account.accountId" in prompt


def test_snb_reference_schema_matches_cypher_workload_shape():
    schema = snb_reference_schema()
    assert schema.has_relationship("Forum", "CONTAINER_OF", "Post")
    assert schema.has_relationship("Post", "HAS_CREATOR", "Person")
    assert schema.has_relationship("Person", "KNOWS", "Person")
    assert "Message" in schema.labels
    assert "creationDate" in schema.properties_for_relationship("KNOWS")
