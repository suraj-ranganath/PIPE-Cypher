from pipecypher import cypher_client
from pipecypher.cypher_client import Neo4jCypherClient


class _FakeResult:
    def __iter__(self):
        return iter([])


class _FakeSession:
    def __init__(self, kwargs):
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def run(self, query, params, timeout):
        self.query = query
        self.params = params
        self.timeout = timeout
        return _FakeResult()


class _FakeDriver:
    def __init__(self):
        self.session_kwargs = []

    def session(self, **kwargs):
        self.session_kwargs.append(kwargs)
        return _FakeSession(kwargs)

    def close(self):
        pass


class _FakeGraphDatabase:
    last_driver = None

    @classmethod
    def driver(cls, uri, auth):
        cls.last_driver = _FakeDriver()
        return cls.last_driver


def test_read_only_run_uses_driver_read_access(monkeypatch):
    monkeypatch.setattr(cypher_client, "GraphDatabase", _FakeGraphDatabase)
    monkeypatch.setattr(cypher_client, "READ_ACCESS", "READ")
    client = Neo4jCypherClient("bolt://x", "u", "p", enforce_read_transactions=True)

    result = client.run("MATCH (n) RETURN n")

    assert result.success
    assert _FakeGraphDatabase.last_driver.session_kwargs[-1]["default_access_mode"] == "READ"


def test_non_read_only_run_does_not_request_read_access(monkeypatch):
    monkeypatch.setattr(cypher_client, "GraphDatabase", _FakeGraphDatabase)
    client = Neo4jCypherClient("bolt://x", "u", "p", enforce_read_transactions=True)

    result = client.run("MATCH (n) RETURN n", read_only=False)

    assert result.success
    assert "default_access_mode" not in _FakeGraphDatabase.last_driver.session_kwargs[-1]


def test_explain_keeps_read_only_enforcement(monkeypatch):
    monkeypatch.setattr(cypher_client, "GraphDatabase", _FakeGraphDatabase)
    monkeypatch.setattr(cypher_client, "READ_ACCESS", "READ")
    client = Neo4jCypherClient("bolt://x", "u", "p", enforce_read_transactions=True)

    result = client.explain("MATCH (n) RETURN n")

    assert result.success
    assert _FakeGraphDatabase.last_driver.session_kwargs[-1]["default_access_mode"] == "READ"
