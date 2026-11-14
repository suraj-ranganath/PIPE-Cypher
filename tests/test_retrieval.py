from pipecypher.retrieval import ExampleStore, placeholderize_example


def test_placeholderize_example_replaces_entity_values_with_typed_placeholders():
    example = {
        "question": "Which accounts are owned by person 'Alice Zhang'?",
        "cypher": (
            "MATCH (p:Person {personName: 'Alice Zhang'})-[:OWN_ACCOUNT]->(a:Account) "
            "RETURN DISTINCT a.accountId AS AccountId"
        ),
        "category": "simple_retrieval",
        "entity_values": ["Alice Zhang"],
    }

    safe = placeholderize_example(example)

    assert "Alice Zhang" not in safe["question"]
    assert "Alice Zhang" not in safe["cypher"]
    assert "'{{PERSONNAME_1}}'" in safe["question"]
    assert "{personName: '{{PERSONNAME_1}}'}" in safe["cypher"]
    assert safe["placeholder_map"] == {"Alice Zhang": "{{PERSONNAME_1}}"}


def test_placeholderize_example_uses_question_quotes_when_entity_values_missing():
    example = {
        "question": "Show company 'Acme Finance'",
        "cypher": "MATCH (c:Company {companyName: 'Acme Finance'}) RETURN DISTINCT c.companyName",
    }

    safe = placeholderize_example(example)

    assert "Acme Finance" not in safe["question"]
    assert "Acme Finance" not in safe["cypher"]
    assert "{{COMPANYNAME_1}}" in safe["question"]


def test_format_examples_anonymizes_by_default_but_can_show_raw_examples():
    store = ExampleStore()
    store.add(
        question="Which accounts are owned by person 'Alice Zhang'?",
        cypher="MATCH (p:Person {personName: 'Alice Zhang'}) RETURN DISTINCT p.personName",
        category="simple_retrieval",
        entity_values=["Alice Zhang"],
    )
    retrieved = store.top_k("accounts for Alice", category="simple_retrieval", k=1)

    anonymized = store.format_examples(retrieved)
    raw = store.format_examples(retrieved, anonymize=False)

    assert "Alice Zhang" not in anonymized
    assert "{{PERSONNAME_1}}" in anonymized
    assert "Alice Zhang" in raw
