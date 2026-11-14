from pipecypher.graph_profiles import finbench_reference_schema, snb_reference_schema
from pipecypher.models import ExecutionResult, SchemaSummary
from pipecypher.schema import introspect_schema


def test_schema_round_trip_dict():
    schema = finbench_reference_schema()
    loaded = SchemaSummary.from_dict(schema.to_dict())
    assert loaded.graph_name == schema.graph_name
    assert "Person" in loaded.labels
    assert loaded.has_relationship("Person", "OWN_ACCOUNT", "Account")


def test_schema_loading_normalizes_neo4j_relationship_type_metadata():
    schema = SchemaSummary.from_dict(
        {
            "relationship_properties": [
                {"type": ":`TRANSFER_TO`", "property": "amount", "value_type": "Double"}
            ],
            "relationships": [
                {
                    "start_label": "Account",
                    "type": ":`TRANSFER_TO`",
                    "end_label": "Account",
                    "count": 7,
                }
            ],
            "graph_name": "finbench",
        }
    )

    assert "amount" in schema.properties_for_relationship("TRANSFER_TO")
    assert schema.has_relationship("Account", "TRANSFER_TO", "Account")


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


class FakeSchemaClient:
    def run(self, query, params=None, *, read_only=True, limit_rows=None):
        if "db.schema.nodeTypeProperties" in query:
            return ExecutionResult(
                success=True,
                rows=[
                    {"label": "Account", "property": "accountType", "type": "String"},
                    {"label": "Account", "property": "accountId", "type": "String"},
                    {"label": "Account", "property": "description", "type": "String"},
                    {"label": "Account", "property": "note", "type": "String"},
                    {"label": "Account", "property": "isBlocked", "type": "Boolean"},
                    {"label": "Person", "property": "email", "type": "String[]"},
                ],
            )
        if "db.schema.relTypeProperties" in query:
            return ExecutionResult(
                success=True,
                rows=[
                    {
                        "type": ":`OWN_ACCOUNT`",
                        "property": "createTime",
                        "value_type": "DateTime",
                    }
                ],
            )
        if "MATCH (a)-[r]->(b)" in query:
            return ExecutionResult(
                success=True,
                rows=[
                    {
                        "start_label": "Person",
                        "rel_type": "OWN_ACCOUNT",
                        "end_label": "Account",
                        "c": 10,
                    }
                ],
            )
        if "MATCH (n:`Account`)" in query and "n.`accountType`" in query:
            return ExecutionResult(
                success=True,
                rows=[{"values": ["checking", "savings"], "distinct_count": 2}],
            )
        if "MATCH (n:`Account`)" in query and "n.`accountId`" in query:
            limit = params["limit"]
            return ExecutionResult(
                success=True,
                rows=[
                    {
                        "values": [f"acct-{idx}" for idx in range(limit)],
                        "distinct_count": limit,
                    }
                ],
            )
        if "MATCH (n:`Account`)" in query and "n.`description`" in query:
            return ExecutionResult(
                success=True,
                rows=[{"values": ["x" * 100], "distinct_count": 1}],
            )
        if "MATCH (n:`Account`)" in query and "n.`note`" in query:
            return ExecutionResult(
                success=True,
                rows=[{"values": ["manual review"], "distinct_count": 1}],
            )
        if "MATCH (n:`Person`)" in query:
            raise AssertionError("list-valued string properties should not be scanned")
        raise AssertionError(f"unexpected query: {query}")


def test_schema_introspection_discovers_bounded_categorical_values():
    schema = introspect_schema(
        FakeSchemaClient(),
        graph_name="fake_finbench",
        categorical_max_values=4,
        categorical_max_value_chars=20,
        categorical_omitted_properties=("*.note",),
    )

    assert schema.categorical_properties == {
        "Account.accountType": ["checking", "savings"]
    }
    assert "Account.accountId" not in schema.categorical_properties
    assert "Account.description" not in schema.categorical_properties
    assert "Account.note" not in schema.categorical_properties
    assert schema.has_relationship("Person", "OWN_ACCOUNT", "Account")
    assert "createTime" in schema.properties_for_relationship("OWN_ACCOUNT")
