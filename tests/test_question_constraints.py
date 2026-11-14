from pipecypher.question_constraints import apply_question_constraints, quoted_values
from pipecypher.validator import validate_cypher
from pipecypher.graph_profiles import finbench_reference_schema


def test_quoted_values():
    assert quoted_values("Show accounts for 'Alice' and 'Bob'") == ["Alice", "Bob"]


def test_quoted_value_rejects_contains():
    schema = finbench_reference_schema()
    validation = validate_cypher(
        "MATCH (p:Person) WHERE p.name CONTAINS 'Alice' RETURN DISTINCT p.name AS PersonName",
        schema,
    )
    updated = apply_question_constraints(validation, "Show person 'Alice'")
    assert not updated.ok
    assert any(issue.code == "quoted_value_fuzzy_match" for issue in updated.issues)

