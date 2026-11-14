from __future__ import annotations

import json

import pytest

from pipecypher.difficulty import (
    DEFAULT_MODEL_PATH,
    TIERS,
    DifficultyModel,
    difficulty_features,
    difficulty_score,
    difficulty_tier,
    load_difficulty_model,
    model_from_dict,
    tier_quota_counts,
)


def test_features_count_structure():
    cypher = (
        "MATCH (p:Person {id: 7})-[:KNOWS*1..2]-(f:Person)-[r:LIKES]->(m:Post) "
        "WHERE m.creationDate > datetime('2012-01-01') AND NOT (f)-[:HAS_INTEREST]->(:Tag) "
        "WITH f, count(m) AS likes, max(r.creationDate) AS last "
        "RETURN f.id AS friendId, likes, last ORDER BY likes DESC LIMIT 5"
    )
    f = difficulty_features(cypher)
    assert f["hops"] == 3
    assert f["var_length"] == 1
    assert f["stages"] == 1
    assert f["aggregations"] == 2
    assert f["grouping_keys"] == 1  # WITH f, count(...), max(...)
    assert f["negation"] == 1
    assert f["predicates"] == 3  # inline {id: 7} + two WHERE conjuncts
    assert f["temporal_refs"] >= 2
    assert f["rel_props"] == 1
    assert f["return_arity"] == 3
    assert f["order_by"] == 1 and f["limit"] == 1
    assert f["labels"] == 3


def test_starts_with_and_string_literals_are_not_stages():
    cypher = "MATCH (t:Tag) WHERE t.name STARTS WITH 'WITH x MATCH' RETURN t.name AS name"
    f = difficulty_features(cypher)
    assert f["stages"] == 0
    assert f["match_clauses"] == 1
    assert f["predicates"] == 1


def test_shipped_model_orders_simple_and_complex_queries():
    model = load_difficulty_model()
    easy = "MATCH (a:Account {accountId: '42'}) RETURN a.accountType AS accountType"
    hard = (
        "MATCH (p:Person {personId: '1'})-[:GUARANTEE*1..5]->(q:Person)-[:OWN]->(a:Account) "
        "WHERE NOT EXISTS { MATCH (a)-[:SIGN_IN]-(:Medium) } "
        "MATCH (a)-[t:TRANSFER_TO]->(b:Account) WHERE t.createTime > datetime('2022-01-01') "
        "RETURN q.personId, q.personName, a.accountId, b.accountId, t.amount, t.createTime "
        "ORDER BY t.amount DESC LIMIT 3"
    )
    assert model.thresholds[0] < model.thresholds[1]
    assert difficulty_score(easy, model) < difficulty_score(hard, model)
    assert difficulty_tier(easy, model) == "easy"
    assert difficulty_tier(hard, model) == "hard"


def test_caps_bound_feature_contributions():
    model = DifficultyModel(weights={"return_arity": 2.0}, caps={"return_arity": 3.0}, thresholds=(4.0, 6.0))
    wide = "MATCH (n:Person) RETURN n.a, n.b, n.c, n.d, n.e, n.f, n.g"
    assert model.score(difficulty_features(wide)) == 6.0
    assert model.tier(6.0) == "hard"
    assert model.tier(5.9) == "medium"
    assert model.tier(3.9) == "easy"


def test_quota_counts_sum_to_target_and_fall_back_to_default():
    model = model_from_dict(
        {
            "weights": {},
            "thresholds": [1, 2],
            "quotas": {
                "path_temporal": {"easy": 0.05, "medium": 0.25, "hard": 0.70},
                "_default": {"easy": 0.35, "medium": 0.35, "hard": 0.30},
            },
        }
    )
    counts = tier_quota_counts("path_temporal", 101, model)
    assert sum(counts.values()) == 101
    assert counts["hard"] > counts["medium"] > counts["easy"]
    default = tier_quota_counts("unknown_category", 20, model)
    assert sum(default.values()) == 20
    assert tier_quota_counts("path_temporal", 0, model) == {tier: 0 for tier in TIERS}


def test_shipped_quotas_rows_sum_to_one_and_balance_overall():
    data = json.loads(DEFAULT_MODEL_PATH.read_text())
    quotas = {cat: shares for cat, shares in data["quotas"].items() if not cat.startswith("_")}
    assert len(quotas) == 8
    for shares in quotas.values():
        assert sum(shares.values()) == pytest.approx(1.0)
    overall = {tier: sum(shares[tier] for shares in quotas.values()) / len(quotas) for tier in TIERS}
    assert overall == pytest.approx({"easy": 0.35, "medium": 0.35, "hard": 0.30}, abs=0.01)
