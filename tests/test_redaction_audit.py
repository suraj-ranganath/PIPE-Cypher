from pipecypher.paper_tables import render_redaction_audit_table
from pipecypher.privacy import PrivacyPolicy
from pipecypher.redaction_audit import RedactionAuditConfig, audit_redaction, sensitive_values_for_example


def _example():
    return {
        "id": "pc_redact",
        "question": "Which account does person 'Kant' own?",
        "cypher": "MATCH (p:Person {personName: 'Kant'}) RETURN p.personName AS name",
        "normalized_cypher": "MATCH (p:Person {personName: 'Kant'}) RETURN p.personName AS name",
        "reverse_cypher": "MATCH (p:Person {personName: 'Kant'}) RETURN p",
        "entity_values": ["Kant"],
        "result_rows_sample": [{"name": "Kant", "accountId": "4739757132830738341"}],
    }


def test_sensitive_values_include_bindings_literals_and_result_strings():
    values = sensitive_values_for_example(_example())

    assert "Kant" in values
    assert "4739757132830738341" in values


def test_redaction_audit_has_zero_residuals_for_default_policy():
    summary = audit_redaction([_example()], policy=PrivacyPolicy(hash_placeholders=True))

    assert summary["examples"] == 1
    assert summary["sensitive_values"] >= 2
    assert summary["examples_with_residuals"] == 0
    assert summary["residual_values"] == 0
    assert summary["placeholder_linkability"]["unique_placeholders"] >= 1
    assert "tab:redaction_audit" in render_redaction_audit_table(summary)


def test_redaction_audit_detects_disabled_question_redaction_residual():
    summary = audit_redaction(
        [_example()],
        policy=PrivacyPolicy(redact_questions=False),
        config=RedactionAuditConfig(min_sensitive_chars=3),
    )

    assert summary["examples_with_residuals"] == 1
    assert summary["residuals_by_field"]["question"] >= 1
