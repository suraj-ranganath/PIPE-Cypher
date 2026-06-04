from pipecypher.diversity_metrics import (
    benchmark_diversity_report,
    canonical_query_signature,
    distinct_n,
    distribution_metrics,
    expected_distinct_ratio,
    operator_combination_signature,
    pairwise_question_similarity,
    self_bleu,
    structural_substructures,
    template_family_signature,
    value_grounding_summary,
)
from pipecypher.paper_tables import render_diversity_table, render_query_signature_concentration_table


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
    assert 0 < expected_distinct_ratio(texts, 1) <= 1
    assert 0 <= self_bleu(texts, max_examples=3, max_order=2) <= 1
    pairwise = pairwise_question_similarity(texts, max_examples=3)
    assert 0 <= pairwise["mean_nearest_neighbor_jaccard"] <= 1


def test_distribution_metrics_reports_entropy_and_counts():
    metrics = distribution_metrics({"a": 2, "b": 2})

    assert metrics["normalized_entropy"] == 1.0
    assert metrics["counts"] == {"a": 2, "b": 2}


def test_canonical_query_signature_masks_literals_and_variables():
    first = "MATCH (p:Person {personName: 'Alice'}) RETURN p.personName LIMIT 10"
    second = "MATCH (x:Person {personName: 'Bob'}) RETURN x.personName LIMIT 20"

    assert canonical_query_signature(first) == canonical_query_signature(second)


def test_template_family_and_structural_substructures_are_cypher_aware():
    row = {
        **_example("Which accounts are owned by Alice?", entity="Alice"),
        "template": "Which accounts are owned by person '{personName}'?",
        "structural_features": {
            "labels": ["Person", "Account"],
            "relationship_types": ["OWN_ACCOUNT"],
            "relationship_observations": [
                {
                    "start_label": "Person",
                    "relationship_type": "OWN_ACCOUNT",
                    "end_label": "Account",
                    "direction": "outgoing",
                }
            ],
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

    assert template_family_signature(row).startswith("template:")
    assert operator_combination_signature(row) == "single_hop+limit"
    atoms = structural_substructures(row)
    assert "triple:Person-[OWN_ACCOUNT:outgoing]->Account" in atoms
    assert "op:limit" in atoms


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
    assert "simple_retrieval" in report["by_category"]
    assert "pipe_diversity_index" in report
    assert "template_families" in report
    assert report["structural_substructures"]["unique_substructure_count"] > 0
    assert report["query_templates"]["top_signatures"][0]["count"] == 3
    assert report["schema_coverage"]["labels"]["coverage"] == 0.5
    assert report["value_grounding"]["unique_entity_values"] == 2
    assert report["value_grounding"]["entity_values_exact_quoted_rate"] == 1.0
    assert "Distinct-1" in table
    assert "PIPE-Diversity index" in table
    assert "Template-family entropy" in table
    assert "Grounded values exactly quoted" in table
    signature_table = render_query_signature_concentration_table(report)
    assert r"\label{tab:query_signature_concentration}" in signature_table
    assert report["query_templates"]["top_signatures"][0]["signature_id"] in signature_table


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
