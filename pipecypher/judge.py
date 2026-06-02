from __future__ import annotations

import json
import re
from typing import Any

from .llm import OpenAICompatibleLLM
from .models import (
    ExecutionResult,
    JudgeResult,
    NodeProperty,
    RelationshipPattern,
    RelationshipProperty,
    SchemaSummary,
    ValidationResult,
)
from .prompts import JUDGE_PROMPT, SYSTEM_JSON_ENGINEER


class DeterministicJudge:
    """Conservative non-LLM judge used for offline smoke runs."""

    def __init__(
        self,
        *,
        min_semantic_alignment: float = 0.75,
        min_schema_use: float = 0.8,
        max_ambiguity: float = 0.35,
    ) -> None:
        self.min_semantic_alignment = min_semantic_alignment
        self.min_schema_use = min_schema_use
        self.max_ambiguity = max_ambiguity

    def judge(
        self,
        *,
        question: str,
        cypher: str,
        schema: SchemaSummary,
        validation: ValidationResult,
        execution: ExecutionResult,
    ) -> JudgeResult:
        ambiguity = 0.2
        semantic = 0.85
        schema_use = 1.0 if validation.schema_valid else 0.0
        reason = ""
        if not validation.ok:
            reason = "deterministic validation failed"
            semantic = 0.0
        elif execution.success and not execution.rows:
            reason = "execution returned no rows"
            semantic = 0.65
        passed = (
            not reason
            and ambiguity <= self.max_ambiguity
            and semantic >= self.min_semantic_alignment
            and schema_use >= self.min_schema_use
        )
        return JudgeResult(
            passed=passed,
            ambiguity_score=ambiguity,
            semantic_alignment_score=semantic,
            schema_use_score=schema_use,
            difficulty=validation.structural_features.get("difficulty", "unknown"),
            failure_reason="" if passed else reason or "below judge threshold",
        )


class LLMJudge:
    def __init__(
        self,
        llm: OpenAICompatibleLLM,
        fallback: DeterministicJudge,
        *,
        temperature: float = 0.0,
        max_tokens: int = 512,
    ) -> None:
        self.llm = llm
        self.fallback = fallback
        self.temperature = temperature
        self.max_tokens = max_tokens

    def judge(
        self,
        *,
        question: str,
        cypher: str,
        schema: SchemaSummary,
        validation: ValidationResult,
        execution: ExecutionResult,
    ) -> JudgeResult:
        prompt = JUDGE_PROMPT.format(
            schema=schema_slice_for_cypher(schema, cypher).to_prompt(max_items=80),
            question=question,
            cypher=cypher,
            rows=json.dumps(execution.rows[:5], default=str),
            validation=json.dumps(
                {
                    "ok": validation.ok,
                    "issues": [issue.__dict__ for issue in validation.issues],
                    "features": validation.structural_features,
                },
                default=str,
            ),
        )
        try:
            data: dict[str, Any] = self.llm.chat_json(
                system=SYSTEM_JSON_ENGINEER,
                user=prompt,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                response_format={"type": "json_object"},
            )
            result = JudgeResult(
                passed=bool(data.get("pass", False)),
                ambiguity_score=float(data.get("ambiguity_score", 1.0)),
                semantic_alignment_score=float(data.get("semantic_alignment_score", 0.0)),
                schema_use_score=float(data.get("schema_use_score", 0.0)),
                difficulty=str(
                    data.get(
                        "difficulty",
                        validation.structural_features.get("difficulty", "unknown"),
                    )
                ),
                failure_reason=str(data.get("failure_reason", "")),
                raw=data,
            )
            return override_categorical_result_value_rejection(
                result,
                cypher=cypher,
                validation=validation,
                execution=execution,
            )
        except Exception as exc:
            result = self.fallback.judge(
                question=question,
                cypher=cypher,
                schema=schema,
                validation=validation,
                execution=execution,
            )
            result.raw = {"fallback_after_error": str(exc)}
            return result


def override_categorical_result_value_rejection(
    result: JudgeResult,
    *,
    cypher: str,
    validation: ValidationResult,
    execution: ExecutionResult,
) -> JudgeResult:
    """Correct a narrow LLM-judge failure mode around sampled categorical values.

    Categorical lists constrain literals written in the Cypher query. They do
    not constrain values observed in result rows, especially when an enterprise
    value-sampling policy redacts, hashes, or bounds categorical metadata.
    """

    if result.passed or not _is_categorical_result_value_false_rejection(
        result,
        cypher=cypher,
        validation=validation,
        execution=execution,
    ):
        return result

    raw = dict(result.raw)
    raw["original_judge"] = {
        "pass": result.passed,
        "ambiguity_score": result.ambiguity_score,
        "semantic_alignment_score": result.semantic_alignment_score,
        "schema_use_score": result.schema_use_score,
        "difficulty": result.difficulty,
        "failure_reason": result.failure_reason,
    }
    raw["override"] = "categorical_result_value_guard"
    return JudgeResult(
        passed=True,
        ambiguity_score=min(result.ambiguity_score, 0.2),
        semantic_alignment_score=max(result.semantic_alignment_score, 0.85),
        schema_use_score=max(result.schema_use_score, 1.0),
        difficulty=result.difficulty,
        failure_reason="",
        raw=raw,
    )


def _is_categorical_result_value_false_rejection(
    result: JudgeResult,
    *,
    cypher: str,
    validation: ValidationResult,
    execution: ExecutionResult,
) -> bool:
    if not validation.ok or not execution.success or not execution.rows:
        return False
    if any(issue.code == "invalid_categorical_value" for issue in validation.issues):
        return False

    reason = result.failure_reason.strip().lower()
    if not reason:
        return False
    categorical_terms = (
        "categorical",
        "valid value",
        "valid values",
        "allowed value",
        "allowed values",
        "schema defines",
        "schema-defined",
    )
    if not any(term in reason for term in categorical_terms):
        return False

    cypher_lower = cypher.lower()
    for value in _execution_string_values(execution):
        normalized = value.lower()
        if normalized in reason and normalized not in cypher_lower:
            return True
    return any(
        term in reason
        for term in ("execution sample", "result row", "result rows", "returns a value")
    )


def _execution_string_values(execution: ExecutionResult) -> set[str]:
    values: set[str] = set()
    for row in execution.rows[:5]:
        for value in row.values():
            if isinstance(value, str):
                text = value.strip()
                if 2 <= len(text) <= 100:
                    values.add(text)
    return values


def schema_slice_for_cypher(schema: SchemaSummary, cypher: str) -> SchemaSummary:
    labels = set(re.findall(r"\([^)]+:([A-Za-z_][A-Za-z0-9_]*)", cypher))
    rel_types = set(re.findall(r"\[[^\]]*:([A-Za-z_][A-Za-z0-9_]*)", cypher))
    prop_refs = set(re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b", cypher))
    variable_labels = {
        var: label
        for var, label in re.findall(r"\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([A-Za-z_][A-Za-z0-9_]*)", cypher)
    }
    prop_names_by_label: dict[str, set[str]] = {}
    for var, prop in prop_refs:
        label = variable_labels.get(var)
        if label:
            prop_names_by_label.setdefault(label, set()).add(prop)

    if rel_types:
        relationships = [rel for rel in schema.relationships if rel.type in rel_types]
    else:
        relationships = [
            rel
            for rel in schema.relationships
            if rel.start_label in labels or rel.end_label in labels
        ]
    for rel in relationships:
        labels.add(rel.start_label)
        labels.add(rel.end_label)
        rel_types.add(rel.type)

    node_properties = [
        prop
        for prop in schema.node_properties
        if prop.label in labels
        and (
            not prop_names_by_label.get(prop.label)
            or prop.property in prop_names_by_label[prop.label]
            or prop.property in {"id", "name", "title", "firstName", "lastName"}
        )
    ]
    relationship_properties = [
        prop for prop in schema.relationship_properties if prop.type in rel_types
    ]
    if not relationships and not node_properties:
        return schema
    return SchemaSummary(
        node_properties=_dedupe_node_properties(node_properties),
        relationship_properties=_dedupe_relationship_properties(relationship_properties),
        relationships=_dedupe_relationships(relationships),
        categorical_properties={
            key: values
            for key, values in schema.categorical_properties.items()
            if key.split(".", 1)[0] in labels
        },
        graph_name=schema.graph_name,
        source=f"{schema.source}:judge_slice",
    )


def _dedupe_node_properties(properties: list[NodeProperty]) -> list[NodeProperty]:
    seen: set[tuple[str, str, str]] = set()
    out: list[NodeProperty] = []
    for prop in properties:
        key = (prop.label, prop.property, prop.type)
        if key in seen:
            continue
        seen.add(key)
        out.append(prop)
    return out


def _dedupe_relationship_properties(properties: list[RelationshipProperty]) -> list[RelationshipProperty]:
    seen: set[tuple[str, str, str]] = set()
    out: list[RelationshipProperty] = []
    for prop in properties:
        key = (prop.type, prop.property, prop.value_type)
        if key in seen:
            continue
        seen.add(key)
        out.append(prop)
    return out


def _dedupe_relationships(relationships: list[RelationshipPattern]) -> list[RelationshipPattern]:
    seen: set[tuple[str, str, str]] = set()
    out: list[RelationshipPattern] = []
    for rel in relationships:
        key = (rel.start_label, rel.type, rel.end_label)
        if key in seen:
            continue
        seen.add(key)
        out.append(rel)
    return out
