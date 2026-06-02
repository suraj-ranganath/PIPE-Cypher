from pipecypher.privacy import (
    PrivacyPolicy,
    ValueSamplingPolicy,
    redact_example,
    sample_categorical_values,
)


def _example():
    return {
        "id": "pc_test",
        "question": "Which accounts owned by person 'Kant' have not sent transfers?",
        "cypher": "MATCH (p:Person {personName: 'Kant'}) RETURN DISTINCT p.personName AS name",
        "normalized_cypher": "MATCH (p:Person {personName: 'Kant'}) RETURN DISTINCT p.personName AS name",
        "reverse_cypher": "MATCH (p:Person) RETURN DISTINCT p.personName AS personName LIMIT 10",
        "entity_values": ["Kant"],
        "result_rows_sample": [{"name": "Kant", "accountId": "4739757132830738341", "blocked": False}],
    }


def test_redact_example_replaces_literals_question_and_samples_without_private_mapping():
    redacted = redact_example(_example())

    assert "Kant" not in redacted["question"]
    assert "'Kant'" not in redacted["cypher"]
    assert redacted["cypher"] == (
        "MATCH (p:Person {personName: '__VALUE_001__'}) RETURN DISTINCT p.personName AS name"
    )
    assert redacted["entity_values"] == ["__VALUE_001__"]
    assert redacted["result_rows_sample"][0]["name"] == "__VALUE_001__"
    assert redacted["result_rows_sample"][0]["accountId"] == "__VALUE_002__"
    assert redacted["result_rows_sample"][0]["blocked"] is False
    assert "private_mapping" not in redacted["privacy_redaction"]


def test_redact_example_can_include_private_mapping_for_internal_debug_only():
    redacted = redact_example(_example(), policy=PrivacyPolicy(include_private_mapping=True))

    assert redacted["privacy_redaction"]["private_mapping"]["__VALUE_001__"] == "Kant"


def test_hash_placeholders_are_stable_without_exposing_values():
    first = redact_example(_example(), policy=PrivacyPolicy(hash_placeholders=True, hash_salt="s"))
    second = redact_example(_example(), policy=PrivacyPolicy(hash_placeholders=True, hash_salt="s"))

    assert first["entity_values"] == second["entity_values"]
    assert first["entity_values"][0].startswith("__VALUE_")
    assert "Kant" not in first["entity_values"][0]


def test_value_sampling_policy_omits_high_cardinality_values():
    sampled = sample_categorical_values(
        "Person.personName",
        ["A", "B", "C"],
        policy=ValueSamplingPolicy(max_values_per_property=2),
    )

    assert sampled == []


def test_value_sampling_policy_omits_long_and_wildcard_blocked_values():
    blocked = sample_categorical_values(
        "Entity.note",
        ["manual review"],
        policy=ValueSamplingPolicy(max_values_per_property=4, omitted_properties=("*.note",)),
    )
    too_long = sample_categorical_values(
        "Entity.status",
        ["x" * 100],
        policy=ValueSamplingPolicy(max_values_per_property=4, max_value_chars=20),
    )

    assert blocked == []
    assert too_long == []


def test_value_sampling_policy_hashes_allowed_values():
    sampled = sample_categorical_values(
        "Account.accountType",
        ["merchant account", "checking account"],
        policy=ValueSamplingPolicy(mode="hash", max_values_per_property=4, hash_salt="s"),
    )

    assert len(sampled) == 2
    assert all(len(value) == 12 for value in sampled)
