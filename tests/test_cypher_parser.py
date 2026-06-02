from pipecypher.cypher_parser import analyze_cypher
from pipecypher.graph_profiles import finbench_reference_schema
from pipecypher.validator import normalize_cypher, structural_features, validate_cypher


def test_analyze_cypher_extracts_return_aliases_and_relationships():
    analysis = analyze_cypher(
        "MATCH (p:Person)-[:OWN_ACCOUNT]->(a:Account) "
        "RETURN DISTINCT p.personName AS PersonName, a.accountId AS AccountId "
        "ORDER BY PersonName LIMIT 10"
    )

    assert analysis.rewrite_safe
    assert analysis.variable_labels == {"p": "Person", "a": "Account"}
    assert [item.alias for item in analysis.projection_items] == ["PersonName", "AccountId"]
    assert analysis.order_by_items == ("PersonName",)
    assert analysis.limit_value == "10"
    assert analysis.relationships[0].start_label == "Person"
    assert analysis.relationships[0].rel_type == "OWN_ACCOUNT"
    assert analysis.relationships[0].end_label == "Account"
    assert analysis.relationships[0].direction == "outgoing"


def test_analyze_cypher_marks_cypher_example_reference_risky_rewrite_constructs():
    analysis = analyze_cypher(
        "MATCH (p:Person) WHERE EXISTS { MATCH (p)-[:OWN_ACCOUNT]->(:Account) } "
        "RETURN p.personName AS PersonName "
        "UNION MATCH (c:Company) RETURN c.companyName AS CompanyName"
    )

    assert not analysis.rewrite_safe
    assert "UNION" in analysis.risky_features
    assert "WHERE EXISTS" in analysis.risky_features
    assert any("risky construct `UNION`" == reason for reason in analysis.rewrite_skip_reasons)


def test_normalize_skips_return_distinct_rewrite_when_query_is_risky():
    query = (
        "MATCH (p:Person) RETURN p.personName AS Name "
        "UNION MATCH (c:Company) RETURN c.companyName AS Name"
    )

    assert normalize_cypher(query) == query

    result = validate_cypher(query, finbench_reference_schema())
    assert result.ok
    assert any(issue.code == "rewrite_skipped" for issue in result.warnings)
    assert any(issue.code == "missing_return_distinct" for issue in result.warnings)
    assert not result.structural_features["rewrite_safe"]


def test_structural_features_include_parser_aware_projection_metadata():
    features = structural_features(
        "MATCH (p:Person)-[:OWN_ACCOUNT]->(a:Account) "
        "RETURN DISTINCT p.personName AS PersonName, a.accountId AS AccountId"
    )

    assert features["return_arity"] == 2
    assert features["return_aliases"] == ["PersonName", "AccountId"]
    assert features["variable_labels"] == {"p": "Person", "a": "Account"}
    assert features["relationship_observations"] == [
        {
            "start_label": "Person",
            "relationship_type": "OWN_ACCOUNT",
            "end_label": "Account",
            "direction": "outgoing",
        }
    ]


def test_structural_features_extract_order_skip_limit_items():
    features = structural_features(
        "MATCH (a:Account) "
        "RETURN DISTINCT a.accountId AS id "
        "ORDER BY id DESC, a.accountType ASC SKIP 5 LIMIT 10"
    )

    assert features["ordering"]
    assert features["skip"]
    assert features["limit"]
    assert features["order_by_items"] == ["id DESC", "a.accountType ASC"]
    assert features["skip_value"] == "5"
    assert features["limit_value"] == "10"


def test_clause_extraction_ignores_order_and_limit_inside_string_literals():
    analysis = analyze_cypher(
        "MATCH (a:Account) "
        "RETURN DISTINCT 'ORDER BY x LIMIT 1' AS text, a.accountId AS id "
        "ORDER BY id LIMIT 3"
    )

    assert [item.alias for item in analysis.projection_items] == ["text", "id"]
    assert analysis.order_by_items == ("id",)
    assert analysis.limit_value == "3"
