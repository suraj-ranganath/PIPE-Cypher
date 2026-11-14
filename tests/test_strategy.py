from pipecypher.strategy import primary_strategy, strategy_tags


def test_strategy_tags_path_and_rank():
    features = {
        "relationship_pattern_count": 1,
        "path_pattern": True,
        "ordering": True,
        "aggregation": False,
        "negation": False,
        "optional_match": False,
        "limit": True,
    }
    tags = strategy_tags(features)
    assert "path" in tags
    assert "order_rank" in tags
    assert primary_strategy(features) == "path"


def test_order_rank_takes_priority_over_aggregation():
    features = {
        "relationship_pattern_count": 1,
        "path_pattern": False,
        "ordering": True,
        "aggregation": True,
        "negation": False,
        "optional_match": False,
        "limit": True,
    }
    assert primary_strategy(features) == "order_rank"


def test_strategy_tags_join_heavy():
    features = {
        "relationship_pattern_count": 3,
        "path_pattern": False,
        "ordering": False,
        "aggregation": False,
        "negation": False,
        "optional_match": False,
        "limit": False,
    }
    assert primary_strategy(features) == "join_heavy"
