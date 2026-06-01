from __future__ import annotations

from typing import Any


def strategy_tags(features: dict[str, Any]) -> list[str]:
    """Map structural Cypher features to workload strategy tags."""

    tags: list[str] = []
    rel_count = int(features.get("relationship_pattern_count", 0) or 0)
    if rel_count == 0:
        tags.append("node_scan")
    elif rel_count == 1:
        tags.append("single_hop")
    else:
        tags.append("join_heavy")
    if features.get("aggregation"):
        tags.append("aggregation")
    if features.get("ordering"):
        tags.append("order_rank")
    if features.get("negation"):
        tags.append("negation")
    if features.get("path_pattern"):
        tags.append("path")
    if features.get("optional_match"):
        tags.append("optional")
    if features.get("limit"):
        tags.append("bounded_result")
    return tags


def primary_strategy(features: dict[str, Any]) -> str:
    tags = strategy_tags(features)
    priority = ["path", "negation", "order_rank", "aggregation", "join_heavy", "single_hop", "node_scan"]
    for item in priority:
        if item in tags:
            return item
    return tags[0] if tags else "unknown"
