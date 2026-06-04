from __future__ import annotations

from collections import Counter

from pipecypher.diversity_metrics import canonical_query_signature
from pipecypher.diversity_selection import (
    assign_diversity_splits,
    select_diverse_examples,
    split_disjointness_audit,
)


def _row(idx: int, *, signature: str, category: str = "simple_retrieval") -> dict:
    if signature == "person":
        cypher = (
            f"MATCH (p:Person {{personName: 'Person {idx}'}}) "
            "RETURN DISTINCT p.personName AS PersonName"
        )
        labels = ["Person"]
        rels = []
        strategy = "node_scan"
    elif signature == "account":
        cypher = (
            f"MATCH (a:Account {{accountId: 'acct-{idx}'}}) "
            "RETURN DISTINCT a.accountId AS AccountId"
        )
        labels = ["Account"]
        rels = []
        strategy = "node_scan"
    else:
        cypher = (
            f"MATCH (p:Person {{personName: 'Person {idx}'}})-[:OWN_ACCOUNT]->(a:Account) "
            "RETURN DISTINCT a.accountId AS AccountId"
        )
        labels = ["Person", "Account"]
        rels = ["OWN_ACCOUNT"]
        strategy = "single_hop"
    return {
        "id": f"{signature}-{idx}",
        "graph_profile": "finbench",
        "category": category,
        "difficulty": "easy",
        "question": f"Question {idx} for {signature}?",
        "cypher": cypher,
        "normalized_cypher": cypher,
        "entity_values": [f"value-{idx}"],
        "gates": {
            "read_only": True,
            "syntax_valid": True,
            "schema_valid": True,
            "execution_success": True,
            "judge_pass": True,
        },
        "judge_scores": {"semantic_alignment": 1.0, "schema_use": 1.0},
        "structural_features": {
            "labels": labels,
            "relationship_types": rels,
            "primary_strategy": strategy,
            "optional_match": False,
            "aggregation": False,
            "ordering": False,
            "limit": False,
            "negation": False,
            "path_pattern": False,
            "relationship_pattern_count": len(rels),
            "node_pattern_count": len(labels),
            "return_arity": 1,
        },
    }


def test_select_diverse_examples_prefers_query_signature_coverage():
    pool = [_row(idx, signature="person") for idx in range(8)]
    pool.extend(_row(100, signature="account") for _ in range(1))
    pool.extend(_row(200, signature="path") for _ in range(1))

    selected = select_diverse_examples(pool, target_per_group=4, seed=7)["examples"]
    selected_signatures = {
        canonical_query_signature(row["normalized_cypher"])
        for row in selected
    }

    assert len(selected) == 4
    assert len(selected_signatures) == 3


def test_signature_disjoint_split_keeps_query_templates_in_one_split():
    rows = []
    for idx in range(12):
        rows.append(_row(idx, signature="person"))
    for idx in range(12, 20):
        rows.append(_row(idx, signature="path"))

    splits = assign_diversity_splits(rows, mode="signature_disjoint", seed=13)
    audit = split_disjointness_audit(splits, mode="signature_disjoint")

    assert audit["leakage_free"] is True
    assert sum(len(rows) for rows in splits.values()) == 20
    holders = Counter()
    for split, split_rows in splits.items():
        for row in split_rows:
            holders[(canonical_query_signature(row["normalized_cypher"]), split)] += 1
    assert len({signature for signature, _ in holders}) == 2


def test_signature_disjoint_split_uses_global_block_capacity():
    rows = []
    for category_idx in range(8):
        category = f"category_{category_idx}"
        for row_idx in range(50):
            row = _row(
                category_idx * 1000 + row_idx,
                signature="path",
                category=category,
            )
            cypher = (
                f"MATCH (n:Label{category_idx} {{id: 'value-{row_idx}'}}) "
                f"RETURN DISTINCT n.id AS Label{category_idx}Id"
            )
            row["cypher"] = cypher
            row["normalized_cypher"] = cypher
            rows.append(row)

    splits = assign_diversity_splits(rows, mode="signature_disjoint", seed=13)
    audit = split_disjointness_audit(splits, mode="signature_disjoint")

    assert audit["leakage_free"] is True
    assert sum(len(split_rows) for split_rows in splits.values()) == 400
    assert len(splits["train"]) < 400
    assert len(splits["dev"]) > 0
    assert len(splits["test"]) > 0
