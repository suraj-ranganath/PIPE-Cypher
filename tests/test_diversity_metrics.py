from pipecypher.diversity_metrics import (
    benchmark_diversity_report,
    canonical_query_signature,
    distinct_n,
    distribution_metrics,
    self_bleu,
    value_grounding_summary,
)
from pipecypher.paper_tables import render_diversity_table


def _example(question: str, category: str = "simple_retrieval", entity: str = "Alice") -> dict:
    return {
        "id": question,
        "graph_profile": "finbench",
        "category": category,
        "difficulty": "easy",
        "question": question,
        "cypher": (
            f"MATCH (p:Person {{personName: '{entity}'}}) "
            "RETURN DISTINCT p.personName AS Name"
        ),
        "normalized_cypher": (
            f"MATCH (p:Person {{personName: '{entity}'}}) RETURN DISTINCT p.personName AS Name"
        ),
        "entity_values": [entity],
        "structural_features": {
            "labels": ["Person"],
            "relationship_types": ["OWN_ACCOUNT"],
            "primary_strategy": "single_hop",
            "optional_match": False,
            "aggregation": False,
            "ordering": False,
            "limit": True,
            "negation": False,
            "path_pattern": False,
            "relationship_pattern_count": 1,
            "node_pattern_count": 2,
            "return_arity": 1,
        },
    }


def test_distinct_n_and_self_bleu_are_bounded():
    texts = ["show accounts for alice", "show accounts for bob", "count transfers"]

    assert 0 < distinct_n(texts, 1) <= 1
    assert 0 <= self_bleu(texts, max_examples=3, max_order=2) <= 1


def test_distribution_metrics_reports_entropy_and_counts():
    metrics = distribution_metrics({"a": 2, "b": 2})

    assert metrics["normalized_entropy"] == 1.0
    assert metrics["counts"] == {"a": 2, "b": 2}


def test_canonical_query_signature_masks_literals_and_variables():
    first = "MATCH (p:Person {personName: 'Alice'}) RETURN p.personName LIMIT 10"
    second = "MATCH (x:Person {personName: 'Bob'}) RETURN x.personName LIMIT 20"

    assert canonical_query_signature(first) == canonical_query_signature(second)


def test_benchmark_diversity_report_and_table_render():
    examples = [
        _example("Which accounts are owned by Alice?", entity="Alice"),
        _example("Which accounts are owned by Bob?", entity="Bob"),
        _example("How many transfers did Alice send?", "simple_aggregation", entity="Alice"),
    ]

    report = benchmark_diversity_report(
        examples,
        schema_inventory={
            "labels": {"Person", "Account"},
            "relationship_types": {"OWN_ACCOUNT", "TRANSFER_TO"},
            "properties": {"personName"},
        },
        self_bleu_sample_size=3,
    )
    table = render_diversity_table(report)

    assert report["n"] == 3
    assert report["schema_coverage"]["labels"]["coverage"] == 0.5
    assert report["value_grounding"]["unique_entity_values"] == 2
    assert report["value_grounding"]["entity_values_exact_quoted_rate"] == 1.0
    assert "Distinct-1" in table
    assert "Grounded values exactly quoted" in table


def test_value_grounding_summary_is_aggregate_only():
    report = value_grounding_summary(
        [
            _example("Show Alice.", entity="Alice"),
            _example("Show Alice again.", entity="Alice"),
            {
                **_example("Show missing literal.", entity="Mallory"),
                "cypher": "MATCH (p:Person) RETURN DISTINCT p.personName AS Name",
                "normalized_cypher": "MATCH (p:Person) RETURN DISTINCT p.personName AS Name",
            },
        ]
    )

    assert report["total_entity_mentions"] == 3
    assert report["unique_entity_values"] == 2
    assert report["top_entity_value_share"] == 2 / 3
    assert report["entity_values_exact_quoted_rate"] == 2 / 3
    assert "Alice" not in str(report)
