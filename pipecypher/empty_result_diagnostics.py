from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from .cypher_parser import _top_level_clauses
from .models import ExecutionResult, ValidationResult
from .validator import is_read_only


RISKY_EMPTY_DIAGNOSTIC_TOKENS = (
    "UNION",
    "CALL",
    "UNWIND",
    "FOREACH",
    "LOAD CSV",
    "CREATE",
    "MERGE",
    "DELETE",
    "SET",
    "REMOVE",
)


class _CypherRunner(Protocol):
    def run(
        self,
        query: str,
        params: dict[str, Any] | None = None,
        *,
        read_only: bool = True,
        limit_rows: int | None = None,
    ) -> ExecutionResult:
        ...


@dataclass(frozen=True)
class EmptyResultStage:
    stage: str
    query: str
    success: bool
    count: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class EmptyResultDiagnostic:
    supported: bool
    classification: str
    reason: str
    stages: list[EmptyResultStage] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def diagnose_empty_result(
    *,
    cypher: str,
    validation: ValidationResult,
    execution: ExecutionResult,
    client: _CypherRunner,
) -> EmptyResultDiagnostic | None:
    """Diagnose safe execution-empty candidates using conservative prefix counts."""

    if not validation.ok:
        return None
    if not execution.success or execution.rows:
        return None
    if not is_empty_diagnostic_supported(validation.normalized_cypher or cypher):
        return EmptyResultDiagnostic(
            supported=False,
            classification="unsupported",
            reason="query contains a construct skipped by prefix diagnostics",
        )
    prefixes = build_prefix_count_queries(validation.normalized_cypher or cypher)
    if not prefixes:
        return EmptyResultDiagnostic(
            supported=False,
            classification="unsupported",
            reason="no safe MATCH/WHERE/WITH prefix could be extracted",
        )

    stages: list[EmptyResultStage] = []
    for stage_name, query in prefixes:
        result = client.run(query, limit_rows=1)
        if not result.success:
            stages.append(
                EmptyResultStage(
                    stage=stage_name,
                    query=query,
                    success=False,
                    error=result.error or "prefix execution failed",
                )
            )
            return EmptyResultDiagnostic(
                supported=True,
                classification="unsupported",
                reason=f"prefix diagnostic failed at {stage_name}",
                stages=stages,
            )
        count = _extract_count(result.rows)
        stages.append(EmptyResultStage(stage=stage_name, query=query, success=True, count=count))

    return _classify_prefix_counts(validation.normalized_cypher or cypher, stages)


def is_empty_diagnostic_supported(cypher: str) -> bool:
    if not is_read_only(cypher):
        return False
    upper = _strip_quoted_literals(cypher).upper()
    return not any(re.search(rf"(?<![A-Z0-9_]){re.escape(token)}(?![A-Z0-9_])", upper) for token in RISKY_EMPTY_DIAGNOSTIC_TOKENS)


def build_prefix_count_queries(cypher: str) -> list[tuple[str, str]]:
    clauses = [clause for clause in _top_level_clauses(cypher) if clause.name != "OPTIONAL MATCH"]
    if not clauses:
        return []
    return_index = next((idx for idx, clause in enumerate(clauses) if clause.name == "RETURN"), None)
    if return_index is None:
        return []

    prefixes: list[tuple[str, str]] = []
    for idx, clause in enumerate(clauses[:return_index]):
        if clause.name not in {"MATCH", "WHERE", "WITH"}:
            continue
        end = clauses[idx + 1].start if idx + 1 < len(clauses) else clauses[return_index].start
        prefix = cypher[:end].strip()
        if not prefix:
            continue
        stage = f"{idx + 1}:{clause.name.lower().replace(' ', '_')}"
        prefixes.append((stage, f"{prefix} RETURN COUNT(*) AS _prefix_count"))
    return prefixes


def _classify_prefix_counts(cypher: str, stages: list[EmptyResultStage]) -> EmptyResultDiagnostic:
    previous_count: int | None = None
    for stage in stages:
        count = stage.count or 0
        if count == 0:
            if previous_count is None:
                classification = (
                    "literal_miss" if _has_literal(stage.query) else "impossible_relationship_path"
                )
                reason = "first executable prefix returned zero rows"
            elif stage.stage.endswith("where"):
                classification = "literal_miss" if _has_literal(stage.query) else "over_restrictive_predicate"
                reason = "WHERE clause reduced a non-empty prefix to zero rows"
            elif stage.stage.endswith("match"):
                classification = "impossible_relationship_path"
                reason = "additional graph pattern reduced a non-empty prefix to zero rows"
            else:
                classification = "aggregation_filter_collapse"
                reason = "WITH or aggregation prefix reduced a non-empty prefix to zero rows"
            return EmptyResultDiagnostic(
                supported=True,
                classification=classification,
                reason=reason,
                stages=stages,
            )
        previous_count = count

    if _has_aggregation_or_limit(cypher):
        return EmptyResultDiagnostic(
            supported=True,
            classification="aggregation_filter_collapse",
            reason="prefixes were non-empty but final projection/order/limit produced no returned rows",
            stages=stages,
        )
    return EmptyResultDiagnostic(
        supported=True,
        classification="over_restrictive_predicate",
        reason="prefixes were non-empty but final query returned no rows",
        stages=stages,
    )


def _extract_count(rows: list[dict[str, Any]]) -> int | None:
    if not rows:
        return 0
    value = rows[0].get("_prefix_count")
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int | float):
        return int(value)
    return None


def _has_literal(cypher: str) -> bool:
    return bool(re.search(r"'(?:\\'|[^'])*'|\"(?:\\\"|[^\"])*\"", cypher))


def _has_aggregation_or_limit(cypher: str) -> bool:
    upper = _strip_quoted_literals(cypher).upper()
    return any(
        token in upper
        for token in ("COUNT(", "SUM(", "AVG(", "COLLECT(", "ORDER BY", "LIMIT")
    )


def _strip_quoted_literals(text: str) -> str:
    return re.sub(r"'(?:\\'|[^'])*'|\"(?:\\\"|[^\"])*\"", "''", text)
