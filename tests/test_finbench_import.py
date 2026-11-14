from pipecypher.finbench_import import generate_import_cypher
from pipecypher.graph_profiles import finbench_reference_schema


def test_generate_import_cypher_contains_core_entities_and_relationships():
    cypher = generate_import_cypher()
    assert "LOAD CSV WITH HEADERS FROM 'file:///finbench/snapshot/Person.csv'" in cypher
    assert "MERGE (n:Account" in cypher
    assert "CREATE (src)-[r:TRANSFER_TO]->(dst)" in cypher
    assert "CREATE (src)-[r:OWN_ACCOUNT]->(dst)" in cypher


def test_finbench_reference_schema_matches_snapshot_relationships():
    schema = finbench_reference_schema()
    assert schema.has_relationship("Medium", "SIGN_IN", "Account")
    assert schema.has_relationship("Loan", "DEPOSIT", "Account")
    assert "personName" in schema.properties_for_label("Person")
    assert "amount" in schema.properties_for_relationship("TRANSFER_TO")
    assert any(prop.type == "BOOLEAN" for prop in schema.node_properties if prop.property == "isBlocked")
    assert any(prop.value_type == "FLOAT" for prop in schema.relationship_properties if prop.property == "amount")
