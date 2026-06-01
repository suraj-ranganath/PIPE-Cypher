from pipecypher.graph_profiles import finbench_reference_schema
from pipecypher.validator import assert_read_only, normalize_cypher, structural_features, validate_cypher


def test_normalize_adds_return_distinct():
    query = "MATCH (p:Person) RETURN p.name AS name"
    assert normalize_cypher(query) == "MATCH (p:Person) RETURN DISTINCT p.name AS name"


def test_read_only_rejects_write():
    try:
        assert_read_only("MATCH (p:Person) DELETE p")
    except ValueError as exc:
        assert "DELETE" in str(exc)
    else:
        raise AssertionError("write query was not rejected")


def test_schema_validation_accepts_known_pattern():
    schema = finbench_reference_schema()
    query = "MATCH (p:Person)-[:OWN_ACCOUNT]->(a:Account) RETURN p.personName AS PersonName, a.accountId AS AccountId"
    result = validate_cypher(query, schema)
    assert result.ok
    assert result.normalized_cypher.startswith("MATCH")
    assert "RETURN DISTINCT" in result.normalized_cypher


def test_validation_can_disable_normalizing_rewrites():
    schema = finbench_reference_schema()
    query = "MATCH (p:Person)-[:OWN_ACCOUNT]->(a:Account) RETURN p.personName AS PersonName"
    result = validate_cypher(query, schema, normalize=False)
    assert result.ok
    assert "RETURN DISTINCT" not in result.normalized_cypher
    assert result.structural_features["return_arity"] == 1


def test_schema_validation_rejects_reverse_direction():
    schema = finbench_reference_schema()
    query = "MATCH (a:Account)-[:OWN_ACCOUNT]->(p:Person) RETURN a.accountId AS AccountId"
    result = validate_cypher(query, schema)
    assert not result.ok
    assert any(issue.code == "wrong_direction" for issue in result.issues)


def test_schema_validation_accepts_incoming_arrow_when_direction_is_preserved():
    schema = finbench_reference_schema()
    query = "MATCH (a:Account)<-[:OWN_ACCOUNT]-(p:Person) RETURN a.accountId AS AccountId"
    result = validate_cypher(query, schema)
    assert result.ok


def test_schema_validation_rejects_incoming_arrow_when_direction_is_reversed():
    schema = finbench_reference_schema()
    query = "MATCH (p:Person)<-[:OWN_ACCOUNT]-(a:Account) RETURN a.accountId AS AccountId"
    result = validate_cypher(query, schema)
    assert not result.ok
    assert any(issue.code == "wrong_direction" for issue in result.issues)


def test_schema_validation_rejects_undirected_relationship_patterns():
    schema = finbench_reference_schema()
    query = "MATCH (p:Person)-[:OWN_ACCOUNT]-(a:Account) RETURN a.accountId AS AccountId"
    result = validate_cypher(query, schema)
    assert not result.ok
    assert any(issue.code == "undirected_relationship" for issue in result.issues)


def test_schema_validation_rejects_untyped_relationship_patterns():
    schema = finbench_reference_schema()
    query = "MATCH (p:Person)-[r]->(a:Account) RETURN a.accountId AS AccountId"
    result = validate_cypher(query, schema)
    assert not result.ok
    assert any(issue.code == "missing_relationship_type" for issue in result.issues)


def test_structural_features_detect_path_and_ranking():
    query = "MATCH (a:Account)-[:TRANSFER_TO*1..2]->(b:Account) RETURN DISTINCT b.accountId AS id ORDER BY id LIMIT 10"
    features = structural_features(query)
    assert features["path_pattern"]
    assert features["ordering"]
    assert "TRANSFER_TO" in features["relationship_types"]


def test_contextual_return_columns_are_warned_not_blocked():
    schema = finbench_reference_schema()
    query = "MATCH (a:Account) RETURN DISTINCT a.accountId AS AccountId LIMIT 10"
    result = validate_cypher(query, schema)
    assert result.ok
    assert any(issue.code == "missing_context_column" for issue in result.warnings)


def test_generic_node_scan_is_warned_for_analysis():
    result = validate_cypher("MATCH (n) RETURN n LIMIT 1", finbench_reference_schema())
    assert result.ok
    assert any(issue.code == "generic_node_scan" for issue in result.warnings)
