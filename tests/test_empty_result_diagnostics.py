from __future__ import annotations

from pipecypher.empty_result_diagnostics import (
    build_prefix_count_queries,
    diagnose_empty_result,
    is_empty_diagnostic_supported,
)
from pipecypher.graph_profiles import finbench_reference_schema
from pipecypher.models import ExecutionResult
from pipecypher.validator import validate_cypher


class PrefixClient:
    def __init__(self, counts: list[int]):
        self.counts = list(counts)
        self.queries: list[str] = []

    def run(self, query, params=None, *, read_only=True, limit_rows=None):
        self.queries.append(query)
        count = self.counts.pop(0)
        return ExecutionResult(success=True, rows=[{"_prefix_count": count}])


def test_build_prefix_count_queries_counts_match_and_where_prefixes():
    cypher = (
        "MATCH (p:Person {personName: 'Alice'})-[:OWN_ACCOUNT]->(a:Account) "
        "WHERE a.isBlocked = true RETURN DISTINCT a.accountId AS AccountId"
    )

    prefixes = build_prefix_count_queries(cypher)

    assert len(prefixes) == 2
    assert prefixes[0][1].endswith("RETURN COUNT(*) AS _prefix_count")
    assert "WHERE" not in prefixes[0][1]
    assert "WHERE a.isBlocked = true" in prefixes[1][1]


def test_diagnose_empty_result_classifies_literal_miss_on_first_zero_prefix():
    cypher = (
        "MATCH (p:Person {personName: 'Missing'})-[:OWN_ACCOUNT]->(a:Account) "
        "RETURN DISTINCT a.accountId AS AccountId"
    )
    validation = validate_cypher(cypher, finbench_reference_schema())
    diagnostic = diagnose_empty_result(
        cypher=cypher,
        validation=validation,
        execution=ExecutionResult(success=True, rows=[]),
        client=PrefixClient([0]),
    )

    assert diagnostic is not None
    assert diagnostic.supported
    assert diagnostic.classification == "literal_miss"


def test_diagnose_empty_result_classifies_over_restrictive_where():
    cypher = (
        "MATCH (p:Person)-[:OWN_ACCOUNT]->(a:Account) "
        "WHERE a.isBlocked = true RETURN DISTINCT a.accountId AS AccountId"
    )
    validation = validate_cypher(cypher, finbench_reference_schema())
    diagnostic = diagnose_empty_result(
        cypher=cypher,
        validation=validation,
        execution=ExecutionResult(success=True, rows=[]),
        client=PrefixClient([10, 0]),
    )

    assert diagnostic is not None
    assert diagnostic.classification == "over_restrictive_predicate"


def test_empty_result_diagnostic_skips_union():
    assert not is_empty_diagnostic_supported(
        "MATCH (p:Person) RETURN p.personName UNION MATCH (a:Account) RETURN a.accountId"
    )
