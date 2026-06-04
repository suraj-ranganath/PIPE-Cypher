from __future__ import annotations

import time
from typing import Any

try:
    from neo4j import READ_ACCESS, GraphDatabase
except Exception:  # pragma: no cover - optional until live graph runs
    GraphDatabase = None
    READ_ACCESS = "READ"

from .models import ExecutionResult
from .validator import assert_read_only


class Neo4jCypherClient:
    """Small Neo4j client wrapper with read-only enforcement for generated queries."""

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        database: str = "neo4j",
        timeout_sec: int = 60,
        enforce_read_transactions: bool = True,
    ) -> None:
        self.uri = uri
        self.user = user
        self.database = database
        self.timeout_sec = timeout_sec
        self.enforce_read_transactions = enforce_read_transactions
        if GraphDatabase is None:
            raise RuntimeError("neo4j package is not installed; install pipe-cypher with runtime deps")
        self._driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self) -> None:
        self._driver.close()

    def verify(self) -> None:
        self._driver.verify_connectivity()

    def run(
        self,
        query: str,
        params: dict[str, Any] | None = None,
        *,
        read_only: bool = True,
        limit_rows: int | None = None,
    ) -> ExecutionResult:
        if read_only:
            assert_read_only(query)
        started = time.perf_counter()
        try:
            session_kwargs: dict[str, Any] = {"database": self.database}
            if read_only and self.enforce_read_transactions:
                session_kwargs["default_access_mode"] = READ_ACCESS
            with self._driver.session(**session_kwargs) as session:
                result = session.run(query, params or {}, timeout=self.timeout_sec)
                rows = [dict(record) for record in result]
                if limit_rows is not None:
                    rows = rows[:limit_rows]
            latency_ms = (time.perf_counter() - started) * 1000
            return ExecutionResult(success=True, rows=rows, latency_ms=latency_ms)
        except Exception as exc:  # pragma: no cover - requires live Neo4j
            latency_ms = (time.perf_counter() - started) * 1000
            return ExecutionResult(success=False, error=str(exc), latency_ms=latency_ms)

    def explain(self, query: str) -> ExecutionResult:
        assert_read_only(query)
        return self.run("EXPLAIN " + query, read_only=True, limit_rows=1)


class NullCypherClient:
    """Offline client for deterministic smoke tests and docs builds."""

    def run(
        self,
        query: str,
        params: dict[str, Any] | None = None,
        *,
        read_only: bool = True,
        limit_rows: int | None = None,
    ) -> ExecutionResult:
        if read_only:
            assert_read_only(query)
        return ExecutionResult(success=False, rows=[], error="No Neo4j client configured")

    def explain(self, query: str) -> ExecutionResult:
        return self.run(query)


class SmokeCypherClient:
    """Deterministic successful execution stub for offline pipeline smoke tests."""

    def run(
        self,
        query: str,
        params: dict[str, Any] | None = None,
        *,
        read_only: bool = True,
        limit_rows: int | None = None,
    ) -> ExecutionResult:
        if read_only:
            assert_read_only(query)
        row = {"_smoke_result": "ok", "_query_preview": query[:120]}
        return ExecutionResult(success=True, rows=[row], latency_ms=0.0)

    def explain(self, query: str) -> ExecutionResult:
        return self.run(query)
