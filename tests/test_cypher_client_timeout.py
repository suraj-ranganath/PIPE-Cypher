from __future__ import annotations

import pytest

neo4j = pytest.importorskip("neo4j")

from pipecypher import cypher_client
from pipecypher.cypher_client import Neo4jCypherClient


class _Session:
    def __init__(self, sink):
        self.sink = sink

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, statement, params=None, **kwargs):
        self.sink.append((statement, params, kwargs))
        return [{"n": 1}]


class _Driver:
    def __init__(self, sink):
        self.sink = sink

    def session(self, **_):
        return _Session(self.sink)

    def close(self):
        return None


def test_query_timeout_is_sent_on_query_object_not_as_parameter(monkeypatch):
    sink: list = []
    monkeypatch.setattr(cypher_client.GraphDatabase, "driver", lambda *a, **k: _Driver(sink))
    client = Neo4jCypherClient("bolt://x", "u", "p", timeout_sec=17)
    result = client.run("MATCH (n) RETURN n LIMIT 1")
    assert result.success
    statement, params, kwargs = sink[0]
    assert isinstance(statement, neo4j.Query)
    assert statement.timeout == 17
    assert params == {}
    assert "timeout" not in kwargs
