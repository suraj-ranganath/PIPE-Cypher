from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


DEFAULT_CATEGORIES = [
    "simple_retrieval",
    "complex_retrieval",
    "simple_aggregation",
    "complex_aggregation",
    "boolean_existence",
    "negation_difference",
    "path_temporal",
    "ranking_topk",
]


@dataclass(frozen=True)
class NodeProperty:
    label: str
    property: str
    type: str = "ANY"


@dataclass(frozen=True)
class RelationshipProperty:
    type: str
    property: str
    value_type: str = "ANY"


@dataclass(frozen=True)
class RelationshipPattern:
    start_label: str
    type: str
    end_label: str
    count: int | None = None

    def compact(self) -> str:
        return f"(:{self.start_label})-[:{self.type}]->(:{self.end_label})"


@dataclass
class SchemaSummary:
    """Compact property-graph schema used for prompting and validation."""

    node_properties: list[NodeProperty] = field(default_factory=list)
    relationship_properties: list[RelationshipProperty] = field(default_factory=list)
    relationships: list[RelationshipPattern] = field(default_factory=list)
    categorical_properties: dict[str, list[str]] = field(default_factory=dict)
    graph_name: str = "unknown"
    source: str = "introspection"

    @property
    def labels(self) -> set[str]:
        labels = {prop.label for prop in self.node_properties}
        for rel in self.relationships:
            labels.add(rel.start_label)
            labels.add(rel.end_label)
        return labels

    @property
    def relationship_types(self) -> set[str]:
        return {rel.type for rel in self.relationships} | {
            prop.type for prop in self.relationship_properties
        }

    def properties_for_label(self, label: str) -> set[str]:
        return {prop.property for prop in self.node_properties if prop.label == label}

    def properties_for_relationship(self, rel_type: str) -> set[str]:
        return {prop.property for prop in self.relationship_properties if prop.type == rel_type}

    def has_relationship(self, start_label: str, rel_type: str, end_label: str) -> bool:
        return any(
            rel.start_label == start_label and rel.type == rel_type and rel.end_label == end_label
            for rel in self.relationships
        )

    def has_reverse_relationship(self, start_label: str, rel_type: str, end_label: str) -> bool:
        return any(
            rel.start_label == end_label and rel.type == rel_type and rel.end_label == start_label
            for rel in self.relationships
        )

    def to_prompt(self, max_items: int = 120) -> str:
        labels = sorted(self.labels)
        rels = sorted(self.relationships, key=lambda r: (r.start_label, r.type, r.end_label))
        node_props = sorted(self.node_properties, key=lambda p: (p.label, p.property))
        rel_props = sorted(self.relationship_properties, key=lambda p: (p.type, p.property))
        parts = [
            f"Graph profile: {self.graph_name}",
            "Node labels: " + ", ".join(labels[:max_items]),
            "Relationship patterns:",
        ]
        parts.extend(f"- {rel.compact()}" for rel in rels[:max_items])
        parts.append("Node properties:")
        parts.extend(f"- :{prop.label}.{prop.property} ({prop.type})" for prop in node_props[:max_items])
        if rel_props:
            parts.append("Relationship properties:")
            parts.extend(
                f"- :{prop.type}.{prop.property} ({prop.value_type})"
                for prop in rel_props[:max_items]
            )
        if self.categorical_properties:
            parts.append("Categorical property values:")
            for key, values in sorted(self.categorical_properties.items()):
                parts.append(f"- {key}: {', '.join(values[:20])}")
        return "\n".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SchemaSummary":
        return cls(
            node_properties=[NodeProperty(**x) for x in data.get("node_properties", [])],
            relationship_properties=[
                RelationshipProperty(
                    type=_normalize_schema_type(str(x.get("type", ""))),
                    property=x["property"],
                    value_type=x.get("value_type", "ANY"),
                )
                for x in data.get("relationship_properties", [])
            ],
            relationships=[
                RelationshipPattern(
                    start_label=x["start_label"],
                    type=_normalize_schema_type(str(x.get("type", ""))),
                    end_label=x["end_label"],
                    count=x.get("count"),
                )
                for x in data.get("relationships", [])
            ],
            categorical_properties=data.get("categorical_properties", {}),
            graph_name=data.get("graph_name", "unknown"),
            source=data.get("source", "file"),
        )


def _normalize_schema_type(value: str) -> str:
    """Normalize Neo4j metadata identifiers such as :`TRANSFER_TO`."""
    normalized = value.strip()
    if normalized.startswith(":"):
        normalized = normalized[1:].strip()
    if normalized.startswith("`") and normalized.endswith("`") and len(normalized) >= 2:
        normalized = normalized[1:-1]
    return normalized


@dataclass
class ValidationIssue:
    level: str
    code: str
    message: str


@dataclass
class ValidationResult:
    read_only: bool
    syntax_valid: bool
    schema_valid: bool
    normalized_cypher: str
    issues: list[ValidationIssue] = field(default_factory=list)
    structural_features: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.read_only and self.syntax_valid and self.schema_valid and not self.errors

    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.level == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.level == "warning"]


@dataclass
class ExecutionResult:
    success: bool
    rows: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    latency_ms: float | None = None

    @property
    def non_empty(self) -> bool:
        return bool(self.rows)


@dataclass
class JudgeResult:
    passed: bool
    ambiguity_score: float
    semantic_alignment_score: float
    schema_use_score: float
    difficulty: str
    failure_reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def failed(cls, reason: str) -> "JudgeResult":
        return cls(
            passed=False,
            ambiguity_score=1.0,
            semantic_alignment_score=0.0,
            schema_use_score=0.0,
            difficulty="unknown",
            failure_reason=reason,
        )


@dataclass
class GenerationRecord:
    question: str
    cypher: str
    category: str
    graph_profile: str
    accepted: bool
    validation: ValidationResult
    execution: ExecutionResult
    judge: JudgeResult
    retrieved_examples: list[dict[str, Any]] = field(default_factory=list)
    entity_values: list[str] = field(default_factory=list)
    reverse_cypher: str | None = None
    repair_attempts: int = 0
    model: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


@dataclass
class TemplateCandidate:
    template: str
    category: str
    slots: dict[str, str] = field(default_factory=dict)
    rationale: str = ""
