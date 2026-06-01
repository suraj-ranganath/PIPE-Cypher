from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .cypher_client import Neo4jCypherClient
from .models import NodeProperty, RelationshipPattern, RelationshipProperty, SchemaSummary


NODE_PROPERTIES_QUERY = """
CALL db.schema.nodeTypeProperties()
YIELD nodeLabels, propertyName, propertyTypes
UNWIND nodeLabels AS label
RETURN label, propertyName AS property, coalesce(head(propertyTypes), 'ANY') AS type
ORDER BY label, property
"""

REL_PROPERTIES_QUERY = """
CALL db.schema.relTypeProperties()
YIELD relType, propertyName, propertyTypes
RETURN relType AS type, propertyName AS property, coalesce(head(propertyTypes), 'ANY') AS value_type
ORDER BY type, property
"""

RELATIONSHIP_PATTERN_QUERY = """
MATCH (a)-[r]->(b)
WITH labels(a) AS start_labels, type(r) AS rel_type, labels(b) AS end_labels, count(*) AS c
UNWIND start_labels AS start_label
UNWIND end_labels AS end_label
RETURN start_label, rel_type, end_label, c
ORDER BY c DESC, start_label, rel_type, end_label
LIMIT $limit
"""

CATEGORICAL_VALUE_QUERY_TEMPLATE = """
MATCH (n:`{label}`)
WHERE n.`{property}` IS NOT NULL
WITH DISTINCT n.`{property}` AS value
ORDER BY value
LIMIT $limit
RETURN collect(value) AS values, count(value) AS distinct_count
"""


def introspect_schema(
    client: Neo4jCypherClient,
    *,
    graph_name: str,
    relationship_limit: int = 500,
    categorical_max_values: int = 12,
) -> SchemaSummary:
    node_properties = []
    rel_properties = []
    relationships = []

    node_result = client.run(NODE_PROPERTIES_QUERY, read_only=False)
    if node_result.success:
        node_properties = [
            NodeProperty(
                label=str(row.get("label")),
                property=str(row.get("property")),
                type=str(row.get("type", "ANY")),
            )
            for row in node_result.rows
            if row.get("label") and row.get("property")
        ]

    rel_prop_result = client.run(REL_PROPERTIES_QUERY, read_only=False)
    if rel_prop_result.success:
        rel_properties = [
            RelationshipProperty(
                type=str(row.get("type")),
                property=str(row.get("property")),
                value_type=str(row.get("value_type", "ANY")),
            )
            for row in rel_prop_result.rows
            if row.get("type") and row.get("property")
        ]

    rel_result = client.run(
        RELATIONSHIP_PATTERN_QUERY,
        params={"limit": relationship_limit},
        read_only=False,
    )
    if rel_result.success:
        relationships = [
            RelationshipPattern(
                start_label=str(row.get("start_label")),
                type=str(row.get("rel_type")),
                end_label=str(row.get("end_label")),
                count=int(row["c"]) if row.get("c") is not None else None,
            )
            for row in rel_result.rows
            if row.get("start_label") and row.get("rel_type") and row.get("end_label")
        ]

    categorical_properties = infer_categorical_properties(
        client,
        node_properties=node_properties,
        max_values=categorical_max_values,
    )

    return SchemaSummary(
        node_properties=node_properties,
        relationship_properties=rel_properties,
        relationships=relationships,
        categorical_properties=categorical_properties,
        graph_name=graph_name,
        source="neo4j",
    )


def infer_categorical_properties(
    client: Neo4jCypherClient,
    *,
    node_properties: list[NodeProperty],
    max_values: int = 12,
) -> dict[str, list[str]]:
    if max_values <= 0:
        return {}

    categorical: dict[str, list[str]] = {}
    for prop in node_properties:
        if not _is_categorical_candidate_type(prop.type):
            continue
        query = CATEGORICAL_VALUE_QUERY_TEMPLATE.format(
            label=_escape_cypher_identifier(prop.label),
            property=_escape_cypher_identifier(prop.property),
        )
        result = client.run(
            query,
            params={"limit": max_values + 1},
            read_only=False,
            limit_rows=1,
        )
        if not result.success or not result.rows:
            continue
        row = result.rows[0]
        values = [str(value) for value in row.get("values", []) if isinstance(value, str)]
        distinct_count = int(row.get("distinct_count", len(values)) or 0)
        if values and distinct_count <= max_values:
            categorical[f"{prop.label}.{prop.property}"] = sorted(values)
    return categorical


def _is_categorical_candidate_type(value_type: str) -> bool:
    normalized = value_type.upper()
    return "STRING" in normalized and "LIST" not in normalized and "[]" not in normalized


def _escape_cypher_identifier(identifier: str) -> str:
    return identifier.replace("`", "``")


def save_schema(schema: SchemaSummary, path: str | Path) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(schema.to_dict(), indent=2, sort_keys=True), encoding="utf-8")


def load_schema(path: str | Path) -> SchemaSummary:
    data: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    return SchemaSummary.from_dict(data)
