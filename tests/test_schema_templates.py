from pipecypher.graph_profiles import default_cypher_for_template, default_reverse_cypher_for_template
from pipecypher.models import NodeProperty, RelationshipPattern, SchemaSummary
from pipecypher.schema import load_schema
from pipecypher.schema_templates import schema_derived_templates
from pipecypher.validator import validate_cypher


def _enterprise_schema() -> SchemaSummary:
    return SchemaSummary(
        node_properties=[
            NodeProperty("Case", "caseId", "STRING"),
            NodeProperty("Case", "status", "STRING"),
            NodeProperty("Case", "jurisdiction", "STRING"),
            NodeProperty("Customer", "customerId", "STRING"),
            NodeProperty("Customer", "country", "STRING"),
        ],
        relationships=[
            RelationshipPattern("Customer", "OWNS", "Case", 1000),
            RelationshipPattern("Case", "RELATED_TO", "Case", 200),
        ],
        categorical_properties={
            "Case.status": ["OPEN", "CLOSED"],
            "Case.jurisdiction": ["US", "GB"],
            "Customer.country": ["US", "GB"],
        },
        graph_name="enterprise_test",
    )


def test_schema_derived_ranking_templates_are_renderable_and_valid():
    schema = _enterprise_schema()
    templates = schema_derived_templates(schema, "ranking_topk", max_templates=20)

    assert any(item.metadata.get("schema_template_kind") == "topk_outgoing" for item in templates)
    scoped = next(
        item
        for item in templates
        if item.metadata.get("schema_template_kind") == "topk_outgoing_scoped"
    )
    value = "OPEN" if scoped.metadata["slot_property"] == "status" else "US"

    reverse = default_reverse_cypher_for_template(scoped, limit=9)
    cypher = default_cypher_for_template(
        scoped,
        schema=schema,
        bindings={"startValue": value},
        limit=9,
    )

    assert reverse is not None
    assert "support > 0" in reverse
    assert "RETURN DISTINCT startValue LIMIT 9" in reverse
    result = validate_cypher(cypher, schema)
    assert result.ok, [issue.code for issue in result.issues]
    assert "ORDER BY relatedCount DESC" in cypher
    assert f"{{{scoped.metadata['slot_property']}: '{value}'}}" in cypher


def test_schema_derived_aggregation_templates_are_renderable_and_valid():
    schema = _enterprise_schema()
    templates = schema_derived_templates(schema, "complex_aggregation", max_templates=20)

    assert any(item.metadata.get("schema_template_kind") == "count_outgoing" for item in templates)
    scoped = next(
        item
        for item in templates
        if item.metadata.get("schema_template_kind") == "count_outgoing_scoped"
    )
    value = "OPEN" if scoped.metadata["slot_property"] == "status" else "US"

    reverse = default_reverse_cypher_for_template(scoped, limit=9)
    cypher = default_cypher_for_template(
        scoped,
        schema=schema,
        bindings={"startValue": value},
        limit=9,
    )

    assert reverse is not None
    assert "support > 0" in reverse
    assert "COUNT(DISTINCT" in cypher
    result = validate_cypher(cypher, schema)
    assert result.ok, [issue.code for issue in result.issues]
    assert f"{{{scoped.metadata['slot_property']}: '{value}'}}" in cypher


def test_schema_derived_negation_reverse_is_outcome_aware():
    schema = _enterprise_schema()
    templates = schema_derived_templates(schema, "negation_difference", max_templates=20)
    scoped = next(
        item
        for item in templates
        if item.metadata.get("schema_template_kind") == "negation_outgoing_scoped"
    )
    value = "OPEN" if scoped.metadata["slot_property"] == "status" else "US"

    reverse = default_reverse_cypher_for_template(scoped, limit=7)
    cypher = default_cypher_for_template(
        scoped,
        schema=schema,
        bindings={"startValue": value},
        limit=7,
    )

    assert reverse is not None
    assert "AND NOT" in reverse
    assert "RETURN DISTINCT s." in reverse
    result = validate_cypher(cypher, schema)
    assert result.ok, [issue.code for issue in result.issues]
    assert "WHERE NOT" in cypher
    assert "LIMIT 7" in cypher


def test_icij_live_schema_gets_extra_schema_templates_for_sparse_categories():
    schema = load_schema("configs/schema_icij_offshoreleaks_live.json")

    aggregation = schema_derived_templates(schema, "complex_aggregation", max_templates=48)
    ranking = schema_derived_templates(schema, "ranking_topk", max_templates=48)
    negation = schema_derived_templates(schema, "negation_difference", max_templates=48)

    assert len(aggregation) >= 24
    assert len(ranking) >= 24
    assert len(negation) >= 24
    assert any(template.slots for template in aggregation)
    assert any(template.slots for template in ranking)
    assert any(template.slots for template in negation)
    assert any("registered_address" in template.template for template in aggregation)
    assert any("registered_address" in template.template for template in negation)
