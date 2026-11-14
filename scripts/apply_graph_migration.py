#!/usr/bin/env python3
"""Apply a declared schema migration or data-drift step to a COPY of a graph.

This is the only PIPE-Cypher script that writes to a graph, and it exists solely
for the benchmark-refresh experiment. Writes are confined by layered guards:

1. ``--target-bolt-uri`` and ``--confirm-copy-database <name>`` are required, and
   the confirmation must equal ``--target-database``.
2. The target endpoint/database is compared against every protected run config
   (default: the FinBench, SNB, and ICIJ ``*_full.yaml`` configs, read as raw YAML
   so environment overrides cannot hide them). A match is refused unless
   ``--i-know-this-is-a-copy`` is passed.
3. The default mode is a dry-run plan. Nothing is written without ``--apply``.
4. With ``--apply`` (or ``--inspect-target``) the script reads ``db.info()`` on the
   target and on every reachable protected endpoint and refuses when the store
   ids match (same database or byte-identical copy) unless overridden.
5. Read-only preconditions must pass before any write, so a migration that was
   already applied (or a wrong graph) stops before mutating anything.

Every run writes a JSON ledger (target endpoint without credentials, store id,
metadata/cypher checksums, git revision, selection digests, per-statement
batches and affected counts, pre/postcondition values).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import yaml

from pipecypher.refresh_audit import normalize_bolt_endpoint

DEFAULT_MIGRATIONS_DIR = "configs/migrations/finbench"
DEFAULT_PRIMARY_CONFIG = "configs/finbench_full.yaml"
DEFAULT_EXTRA_PROTECTED_CONFIGS = ("configs/snb_full.yaml", "configs/icij_offshoreleaks_full.yaml")

EXIT_OK = 0
EXIT_SAFETY = 2
EXIT_PRECONDITION = 3
EXIT_WRITE = 4
EXIT_POSTCONDITION = 5

META_KEYS = frozenset(
    {
        "id",
        "graph_profile",
        "kind",
        "description",
        "cypher_file",
        "batch_size",
        "selection",
        "generator",
        "preconditions",
        "postconditions",
        "expected_schema_diff",
        "expected_benchmark_impact",
    }
)
REQUIRED_META_KEYS = frozenset({"id", "graph_profile", "kind", "description", "cypher_file"})
MIGRATION_KINDS = frozenset({"schema_migration", "data_drift"})
SELECTION_KEYS = frozenset({"query", "key_fields", "fraction", "salt", "param_name"})
GENERATOR_KEYS = frozenset(
    {
        "kind",
        "accounts_query",
        "stats_query",
        "vocab_query",
        "fraction_of_existing",
        "salt",
        "comment_marker",
        "param_name",
    }
)
CHECK_KEYS = frozenset({"name", "query", "expect", "severity"})


class MigrationSpecError(ValueError):
    """Raised when migration metadata is malformed (treated as a launch blocker)."""


# ---------------------------------------------------------------------------
# Metadata loading


@dataclass
class MigrationSpec:
    id: str
    graph_profile: str
    kind: str
    description: str
    meta_path: Path
    cypher_path: Path
    statements: list[str]
    batch_size: int = 1000
    selection: dict[str, Any] | None = None
    generator: dict[str, Any] | None = None
    preconditions: list[dict[str, Any]] = field(default_factory=list)
    postconditions: list[dict[str, Any]] = field(default_factory=list)
    expected_schema_diff: dict[str, Any] = field(default_factory=dict)
    expected_benchmark_impact: str = ""

    @property
    def param_name(self) -> str | None:
        block = self.selection or self.generator
        if not block:
            return None
        return str(block.get("param_name") or "rows")

    def checksums(self) -> dict[str, str]:
        return {
            "meta_sha256": _sha256_file(self.meta_path),
            "cypher_sha256": _sha256_file(self.cypher_path),
        }


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def split_cypher_statements(text: str) -> list[str]:
    """Split a ``.cypher`` file on top-level ``;`` (ignores quotes and ``//`` comments)."""

    statements: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False
    i = 0
    while i < len(text):
        char = text[i]
        if quote:
            current.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            i += 1
            continue
        if char == "/" and text[i : i + 2] == "//":
            newline = text.find("\n", i)
            i = len(text) if newline == -1 else newline
            continue
        if char in {"'", '"'}:
            quote = char
            current.append(char)
        elif char == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
        else:
            current.append(char)
        i += 1
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def _check_keys(block: Mapping[str, Any], allowed: frozenset[str], where: str) -> None:
    unknown = sorted(set(block) - allowed)
    if unknown:
        raise MigrationSpecError(f"{where}: unknown keys: {', '.join(unknown)}")


def _load_checks(raw: Any, where: str) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for index, item in enumerate(raw or []):
        if not isinstance(item, Mapping):
            raise MigrationSpecError(f"{where}[{index}] must be a mapping")
        _check_keys(item, CHECK_KEYS, f"{where}[{index}]")
        if not item.get("name") or not item.get("query"):
            raise MigrationSpecError(f"{where}[{index}] needs name and query")
        severity = str(item.get("severity", "error"))
        if severity not in {"error", "warning"}:
            raise MigrationSpecError(f"{where}[{index}].severity must be error or warning")
        expect = str(item.get("expect", "nonnegative"))
        parse_expectation(expect)  # validate early
        checks.append(
            {"name": str(item["name"]), "query": str(item["query"]), "expect": expect, "severity": severity}
        )
    return checks


def load_migration(path: str | Path) -> MigrationSpec:
    meta_path = Path(path)
    data = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, Mapping):
        raise MigrationSpecError(f"{meta_path}: metadata must be a mapping")
    _check_keys(data, META_KEYS, str(meta_path))
    missing = sorted(REQUIRED_META_KEYS - set(data))
    if missing:
        raise MigrationSpecError(f"{meta_path}: missing keys: {', '.join(missing)}")
    if data["kind"] not in MIGRATION_KINDS:
        raise MigrationSpecError(f"{meta_path}: kind must be one of {sorted(MIGRATION_KINDS)}")
    selection = data.get("selection")
    generator = data.get("generator")
    if selection and generator:
        raise MigrationSpecError(f"{meta_path}: use either selection or generator, not both")
    if selection:
        _check_keys(selection, SELECTION_KEYS, f"{meta_path}:selection")
        for key in ("query", "key_fields", "fraction", "salt"):
            if key not in selection:
                raise MigrationSpecError(f"{meta_path}: selection.{key} is required")
        if not 0 < float(selection["fraction"]) < 1:
            raise MigrationSpecError(f"{meta_path}: selection.fraction must be in (0, 1)")
    if generator:
        _check_keys(generator, GENERATOR_KEYS, f"{meta_path}:generator")
        if generator.get("kind") not in GENERATORS:
            raise MigrationSpecError(
                f"{meta_path}: generator.kind must be one of {sorted(GENERATORS)}"
            )
    cypher_path = (meta_path.parent / str(data["cypher_file"])).resolve()
    if not cypher_path.exists():
        raise MigrationSpecError(f"{meta_path}: cypher_file not found: {cypher_path}")
    statements = split_cypher_statements(cypher_path.read_text(encoding="utf-8"))
    if not statements:
        raise MigrationSpecError(f"{cypher_path}: no statements")
    spec = MigrationSpec(
        id=str(data["id"]),
        graph_profile=str(data["graph_profile"]),
        kind=str(data["kind"]),
        description=" ".join(str(data["description"]).split()),
        meta_path=meta_path.resolve(),
        cypher_path=cypher_path,
        statements=statements,
        batch_size=int(data.get("batch_size", 1000)),
        selection=dict(selection) if selection else None,
        generator=dict(generator) if generator else None,
        preconditions=_load_checks(data.get("preconditions"), f"{meta_path}:preconditions"),
        postconditions=_load_checks(data.get("postconditions"), f"{meta_path}:postconditions"),
        expected_schema_diff=dict(data.get("expected_schema_diff") or {}),
        expected_benchmark_impact=" ".join(str(data.get("expected_benchmark_impact", "")).split()),
    )
    param = spec.param_name
    uses_param = [s for s in statements if param and re.search(rf"\${re.escape(param)}\b", s)]
    if param and not uses_param:
        raise MigrationSpecError(f"{cypher_path}: no statement uses ${param}")
    if not param and any(re.search(r"\$rows\b", s) for s in statements):
        raise MigrationSpecError(f"{cypher_path}: $rows used but no selection/generator declared")
    if spec.batch_size <= 0:
        raise MigrationSpecError(f"{meta_path}: batch_size must be > 0")
    return spec


def resolve_migration_path(value: str, migrations_dir: str | Path) -> Path:
    candidate = Path(value)
    if candidate.exists():
        return candidate
    for name in (f"{value}.meta.yaml", f"{value}.yaml"):
        path = project_path(migrations_dir) / name
        if path.exists():
            return path
    raise MigrationSpecError(f"migration not found: {value} (looked in {migrations_dir})")


def list_migrations(migrations_dir: str | Path) -> list[MigrationSpec]:
    return [load_migration(path) for path in sorted(project_path(migrations_dir).glob("*.meta.yaml"))]


# ---------------------------------------------------------------------------
# Expectations


_EXPECT_RE = re.compile(r"^(==|!=|<=|>=|<|>)\s*(.+)$")


def parse_expectation(expect: str) -> tuple[str, str | None]:
    text = expect.strip()
    if text in {"positive", "zero", "nonnegative"}:
        return text, None
    match = _EXPECT_RE.match(text)
    if not match:
        raise MigrationSpecError(f"unsupported expectation: {expect!r}")
    return match.group(1), match.group(2)


def evaluate_expression(expr: str, env: Mapping[str, Any]) -> float:
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?|[+-]", expr)
    if "".join(tokens) != re.sub(r"\s+", "", expr):
        raise MigrationSpecError(f"unsupported expression: {expr!r}")
    total = 0.0
    sign = 1
    expect_operand = True
    for token in tokens:
        if token in {"+", "-"}:
            if expect_operand:
                raise MigrationSpecError(f"malformed expression: {expr!r}")
            sign = 1 if token == "+" else -1
            expect_operand = True
            continue
        if not expect_operand:
            raise MigrationSpecError(f"malformed expression: {expr!r}")
        if re.match(r"^\d", token):
            value = float(token)
        else:
            if token not in env or env[token] is None:
                raise MigrationSpecError(f"expression references unknown value {token!r}")
            value = float(env[token])
        total += sign * value
        expect_operand = False
    if expect_operand:
        raise MigrationSpecError(f"malformed expression: {expr!r}")
    return total


def expectation_holds(expect: str, value: Any, env: Mapping[str, Any]) -> bool:
    op, expr = parse_expectation(expect)
    if value is None:
        return False
    number = float(value)
    if op == "positive":
        return number > 0
    if op == "zero":
        return number == 0
    if op == "nonnegative":
        return number >= 0
    target = evaluate_expression(str(expr), env)
    return {
        "==": number == target,
        "!=": number != target,
        "<=": number <= target,
        ">=": number >= target,
        "<": number < target,
        ">": number > target,
    }[op]


# ---------------------------------------------------------------------------
# Deterministic selection and generation


def hash_fraction(salt: str, key_values: list[Any]) -> float:
    payload = json.dumps(key_values, sort_keys=True, default=str, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256((salt + "\x1f" + payload).encode("utf-8")).hexdigest()
    return int(digest[:16], 16) / float(1 << 64)


def select_rows(
    rows: list[Mapping[str, Any]],
    *,
    key_fields: list[str],
    fraction: float,
    salt: str,
) -> list[dict[str, Any]]:
    """Deterministic hash-of-properties selection (independent of element ids and row order)."""

    seen: set[str] = set()
    selected: list[dict[str, Any]] = []
    for row in rows:
        key = [row.get(name) for name in key_fields]
        canonical = json.dumps(key, default=str, ensure_ascii=False)
        if canonical in seen:
            continue
        seen.add(canonical)
        if hash_fraction(salt, key) < fraction:
            selected.append({name: row.get(name) for name in key_fields})
    selected.sort(key=lambda r: json.dumps([r[name] for name in key_fields], default=str))
    return selected


def rows_digest(rows: list[Mapping[str, Any]]) -> str:
    lines = sorted(json.dumps(dict(row), sort_keys=True, default=str, ensure_ascii=False) for row in rows)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def generate_synthetic_transfers(
    read: Callable[[str], list[dict[str, Any]]],
    spec: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Deterministic new transfer edges between existing accounts.

    Endpoints, amounts, payment vocabulary, and timestamps are derived from a
    salted SHA-256 of the edge ordinal, so two copies loaded from the same import
    receive identical edges. Timestamps start one minute after the latest
    existing transfer ("new data arriving").
    """

    accounts = sorted({str(row["accountId"]) for row in read(str(spec["accounts_query"])) if row.get("accountId")})
    if len(accounts) < 2:
        raise MigrationSpecError("synthetic_transfers needs at least two accounts")
    stats_rows = read(str(spec["stats_query"]))
    if not stats_rows:
        raise MigrationSpecError("synthetic_transfers stats_query returned no rows")
    existing = int(stats_rows[0].get("n") or 0)
    base_time = stats_rows[0].get("max_create_time")
    if existing <= 0 or not base_time:
        raise MigrationSpecError("synthetic_transfers needs existing transfers with createTime")
    vocab: list[dict[str, Any]] = []
    if spec.get("vocab_query"):
        vocab = sorted(
            (dict(row) for row in read(str(spec["vocab_query"]))),
            key=lambda r: json.dumps(r, sort_keys=True, default=str),
        )
    n_new = int(round(existing * float(spec.get("fraction_of_existing", 0.05))))
    salt = str(spec["salt"])
    marker = str(spec.get("comment_marker") or "pipecypher_refresh_synthetic")
    rows: list[dict[str, Any]] = []
    for ordinal in range(n_new):
        digest = hashlib.sha256(f"{salt}\x1f{ordinal}".encode("utf-8")).hexdigest()
        src_index = int(digest[0:16], 16) % len(accounts)
        dst_index = int(digest[16:32], 16) % (len(accounts) - 1)
        if dst_index >= src_index:
            dst_index += 1
        choice = vocab[int(digest[44:52], 16) % len(vocab)] if vocab else {}
        rows.append(
            {
                "src": accounts[src_index],
                "dst": accounts[dst_index],
                "amount": round(1.0 + (int(digest[32:44], 16) % 5_000_000) / 100.0, 2),
                "baseTime": str(base_time),
                "offsetMinutes": ordinal + 1,
                "orderNum": "PCR" + digest[52:64],
                "comment": marker,
                "payType": choice.get("payType"),
                "goodsType": choice.get("goodsType"),
            }
        )
    info = {
        "accounts": len(accounts),
        "existing_transfers": existing,
        "base_time": str(base_time),
        "vocabulary_size": len(vocab),
        "generated": len(rows),
    }
    return rows, info


GENERATORS: dict[str, Callable[..., tuple[list[dict[str, Any]], dict[str, Any]]]] = {
    "synthetic_transfers": generate_synthetic_transfers,
}


# ---------------------------------------------------------------------------
# Safety


@dataclass(frozen=True)
class ProtectedEndpoint:
    config_path: str
    uri: str
    database: str
    user: str = "neo4j"
    password: str = "password"


def project_path(raw: str | Path) -> Path:
    """Resolve a repo-relative default path independent of the working directory."""

    path = Path(raw)
    if path.exists() or path.is_absolute():
        return path
    candidate = PROJECT_ROOT / path
    return candidate if candidate.exists() else path


def load_protected_endpoints(primary_config: str, extra_configs: list[str]) -> tuple[list[ProtectedEndpoint], list[str]]:
    """Read neo4j endpoints from raw YAML (no env overrides). Missing extras are noted."""

    endpoints: list[ProtectedEndpoint] = []
    notes: list[str] = []
    for index, raw_path in enumerate([primary_config, *extra_configs]):
        path = project_path(raw_path)
        if not path.exists():
            if index == 0:
                raise MigrationSpecError(f"primary config not found: {path}")
            notes.append(f"protected config not found (skipped): {path}")
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        neo4j = (data.get("neo4j") or {}) if isinstance(data, Mapping) else {}
        endpoints.append(
            ProtectedEndpoint(
                config_path=str(path),
                uri=str(neo4j.get("uri") or "bolt://localhost:7687"),
                database=str(neo4j.get("database") or "neo4j"),
                user=str(neo4j.get("user") or "neo4j"),
                password=str(neo4j.get("password") or "password"),
            )
        )
    return endpoints, notes


@dataclass
class SafetyDecision:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def evaluate_target_safety(
    *,
    target_uri: str,
    target_database: str,
    confirm_copy_database: str,
    protected: list[ProtectedEndpoint],
    allow_override: bool = False,
) -> SafetyDecision:
    decision = SafetyDecision()
    if not target_uri.strip():
        decision.errors.append("--target-bolt-uri is required")
    if not confirm_copy_database.strip():
        decision.errors.append("--confirm-copy-database is required")
    elif confirm_copy_database != target_database:
        decision.errors.append(
            f"--confirm-copy-database {confirm_copy_database!r} does not match "
            f"--target-database {target_database!r}"
        )
    if not target_uri.strip():
        return decision
    target_endpoint = normalize_bolt_endpoint(target_uri)
    for endpoint in protected:
        if normalize_bolt_endpoint(endpoint.uri) != target_endpoint:
            continue
        where = f"{target_endpoint[0]}:{target_endpoint[1]}/{target_database}"
        if endpoint.database == target_database:
            message = f"target {where} is the protected graph declared in {endpoint.config_path}"
            if allow_override:
                decision.warnings.append(message + " (overridden by --i-know-this-is-a-copy)")
            else:
                decision.errors.append(message)
        else:
            decision.warnings.append(
                f"target shares a server with {endpoint.config_path} "
                f"(database {endpoint.database!r} vs {target_database!r})"
            )
    return decision


DB_INFO_QUERY = "CALL db.info() YIELD id, name, creationDate RETURN id, name, toString(creationDate) AS creationDate"
NODE_COUNT_QUERY = "MATCH (n) RETURN count(n) AS n"


def live_identity_check(
    target_client: Any,
    protected_clients: Mapping[str, Any],
    *,
    allow_override: bool = False,
) -> tuple[SafetyDecision, dict[str, Any]]:
    """Compare ``db.info()`` store ids of the target and every reachable protected graph."""

    decision = SafetyDecision()
    target = target_client.run(DB_INFO_QUERY, read_only=True)
    if not target.success or not target.rows:
        decision.errors.append(f"could not read db.info() on target: {target.error}")
        return decision, {}
    target_info = {k: str(v) for k, v in target.rows[0].items()}
    count = target_client.run(NODE_COUNT_QUERY, read_only=True)
    target_info["node_count"] = (count.rows[0].get("n") if count.success and count.rows else None)
    if not target_info["node_count"]:
        decision.errors.append("target graph is empty or unreadable; load the copy first")
    for name, client in protected_clients.items():
        if client is None:
            decision.warnings.append(f"protected endpoint {name} unreachable; identity not compared")
            continue
        result = client.run(DB_INFO_QUERY, read_only=True)
        if not result.success or not result.rows:
            decision.warnings.append(f"protected endpoint {name} unreadable; identity not compared")
            continue
        if str(result.rows[0].get("id")) == target_info.get("id"):
            message = f"target store id equals protected graph {name} (same database or byte copy)"
            if allow_override:
                decision.warnings.append(message + " (overridden by --i-know-this-is-a-copy)")
            else:
                decision.errors.append(message)
    return decision, target_info


# ---------------------------------------------------------------------------
# Execution


@dataclass
class MigrationOutcome:
    exit_code: int
    ledger: dict[str, Any]


def _read(client: Any, query: str, params: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    result = client.run(query, dict(params or {}), read_only=True)
    if not result.success:
        raise MigrationSpecError(f"read query failed: {result.error}")
    return list(result.rows)


def _first_value(rows: list[dict[str, Any]]) -> Any:
    if not rows:
        return None
    row = rows[0]
    if "n" in row:
        return row["n"]
    return next(iter(row.values()), None)


def run_checks(client: Any, checks: list[dict[str, Any]], env: dict[str, Any], stage: str) -> tuple[list[dict[str, Any]], bool]:
    results: list[dict[str, Any]] = []
    failed = False
    for check in checks:
        params = {k: v for k, v in env.items() if isinstance(v, (int, float, str)) or v is None}
        try:
            value = _first_value(_read(client, check["query"], params))
            holds = expectation_holds(check["expect"], value, env)
            error = None
        except MigrationSpecError as exc:
            value, holds, error = None, False, str(exc)
        env[check["name"]] = value
        results.append(
            {
                "stage": stage,
                "name": check["name"],
                "expect": check["expect"],
                "severity": check["severity"],
                "value": value,
                "passed": holds,
                "error": error,
            }
        )
        if not holds and check["severity"] == "error":
            failed = True
    return results, failed


def compute_param_rows(client: Any, spec: MigrationSpec) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if spec.selection:
        candidates = _read(client, str(spec.selection["query"]))
        rows = select_rows(
            candidates,
            key_fields=[str(k) for k in spec.selection["key_fields"]],
            fraction=float(spec.selection["fraction"]),
            salt=str(spec.selection["salt"]),
        )
        info = {
            "kind": "hash_selection",
            "candidates": len(candidates),
            "selected": len(rows),
            "fraction": float(spec.selection["fraction"]),
            "salt": str(spec.selection["salt"]),
            "key_fields": list(spec.selection["key_fields"]),
            "selection_digest": rows_digest(rows),
        }
        return rows, info
    if spec.generator:
        generator = GENERATORS[str(spec.generator["kind"])]
        rows, info = generator(lambda q: _read(client, q), spec.generator)
        info = {"kind": str(spec.generator["kind"]), **info, "generated_digest": rows_digest(rows)}
        return rows, info
    return [], {}


def execute_migration(
    spec: MigrationSpec,
    client: Any,
    *,
    apply: bool,
    ledger: dict[str, Any],
) -> MigrationOutcome:
    """Run preconditions, compute parameters, and (only with ``apply``) write."""

    env: dict[str, Any] = {}
    pre, pre_failed = run_checks(client, spec.preconditions, env, "pre")
    ledger["preconditions"] = pre
    if pre_failed:
        ledger["status"] = "precondition_failed"
        return MigrationOutcome(EXIT_PRECONDITION, ledger)

    rows, param_info = compute_param_rows(client, spec)
    ledger["parameters"] = param_info
    env["selected"] = len(rows) if spec.selection else 0
    env["generated"] = len(rows) if spec.generator else 0
    env["affected"] = 0
    if not apply:
        ledger["status"] = "planned"
        return MigrationOutcome(EXIT_OK, ledger)

    statements_log: list[dict[str, Any]] = []
    ledger["statements"] = statements_log
    param = spec.param_name
    for index, statement in enumerate(spec.statements):
        uses_rows = bool(param and re.search(rf"\${re.escape(param)}\b", statement))
        batches = (
            [rows[i : i + spec.batch_size] for i in range(0, len(rows), spec.batch_size)]
            if uses_rows
            else [None]
        )
        entry = {
            "index": index,
            "sha256": hashlib.sha256(statement.encode("utf-8")).hexdigest(),
            "uses_rows": uses_rows,
            "batches": len(batches),
            "affected": 0,
            "latency_ms": 0.0,
        }
        statements_log.append(entry)
        for batch in batches:
            started = time.perf_counter()
            params = {param: batch} if uses_rows and param else {}
            result = client.run(statement, params, read_only=False)
            entry["latency_ms"] += (time.perf_counter() - started) * 1000
            if not result.success:
                entry["error"] = str(result.error)[:1000]
                ledger["status"] = "write_failed"
                return MigrationOutcome(EXIT_WRITE, ledger)
            affected = sum(int(row.get("affected") or 0) for row in result.rows if isinstance(row, Mapping))
            entry["affected"] += affected
            env["affected"] += affected

    post, post_failed = run_checks(client, spec.postconditions, env, "post")
    ledger["postconditions"] = post
    ledger["affected_total"] = env["affected"]
    if post_failed:
        ledger["status"] = "postcondition_failed"
        return MigrationOutcome(EXIT_POSTCONDITION, ledger)
    ledger["status"] = "applied"
    return MigrationOutcome(EXIT_OK, ledger)


def render_plan(spec: MigrationSpec, decision: SafetyDecision, args: argparse.Namespace) -> str:
    lines = [
        f"Migration: {spec.id} ({spec.kind}, graph_profile={spec.graph_profile})",
        f"Description: {spec.description}",
        f"Metadata: {spec.meta_path}",
        f"Cypher: {spec.cypher_path}",
        f"Target: {args.target_bolt_uri} database={args.target_database}",
        "Safety: " + ("OK" if decision.ok else "REFUSED"),
    ]
    lines += [f"  error: {e}" for e in decision.errors]
    lines += [f"  warning: {w}" for w in decision.warnings]
    if spec.selection:
        lines.append(
            "Selection: hash(" + ", ".join(spec.selection["key_fields"]) + f") < {spec.selection['fraction']}"
            f" salt={spec.selection['salt']}"
        )
    if spec.generator:
        lines.append(
            f"Generator: {spec.generator['kind']} fraction_of_existing="
            f"{spec.generator.get('fraction_of_existing')} salt={spec.generator.get('salt')}"
        )
    for check in spec.preconditions:
        lines.append(f"Precondition {check['name']}: expect {check['expect']} [{check['severity']}]")
    for index, statement in enumerate(spec.statements):
        batched = " (batched over $" + str(spec.param_name) + ")" if spec.param_name and f"${spec.param_name}" in statement else ""
        lines.append(f"Statement {index}{batched}:")
        lines += ["    " + line for line in statement.splitlines()]
    for check in spec.postconditions:
        lines.append(f"Postcondition {check['name']}: expect {check['expect']} [{check['severity']}]")
    if spec.expected_schema_diff:
        lines.append("Expected schema diff: " + json.dumps(spec.expected_schema_diff, sort_keys=True))
    lines.append("Mode: " + ("APPLY" if args.apply else "dry run (no writes; pass --apply to write)"))
    return "\n".join(lines)


def _git_revision() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except Exception:
        return None


def _default_client_factory(uri: str, user: str, password: str, database: str, timeout: int) -> Any:
    from pipecypher.cypher_client import Neo4jCypherClient

    return Neo4jCypherClient(uri, user, password, database=database, timeout_sec=timeout)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply a PIPE-Cypher refresh-experiment migration to a COPY of a graph (dry run by default)."
    )
    parser.add_argument("--migration", help="Migration id (resolved in --migrations-dir) or path to *.meta.yaml")
    parser.add_argument("--migrations-dir", default=DEFAULT_MIGRATIONS_DIR)
    parser.add_argument("--list", action="store_true", help="List available migrations and exit")
    parser.add_argument("--target-bolt-uri", default="", help="Bolt URI of the COPY instance (required)")
    parser.add_argument("--target-database", default="neo4j")
    parser.add_argument("--target-user", default="neo4j")
    parser.add_argument(
        "--target-password",
        default=os.environ.get("PIPE_CYPHER_COPY_NEO4J_PASSWORD", "password"),
        help="Defaults to $PIPE_CYPHER_COPY_NEO4J_PASSWORD or 'password' (auth disabled copies ignore it)",
    )
    parser.add_argument(
        "--confirm-copy-database",
        default="",
        help="Must equal --target-database; states that the target is a disposable copy (required)",
    )
    parser.add_argument("--primary-config", default=DEFAULT_PRIMARY_CONFIG)
    parser.add_argument(
        "--protected-config",
        action="append",
        default=None,
        help="Extra run configs whose graphs must never be written (default: SNB and ICIJ full configs)",
    )
    parser.add_argument("--i-know-this-is-a-copy", action="store_true", dest="override")
    parser.add_argument("--apply", action="store_true", help="Actually write to the target copy")
    parser.add_argument(
        "--inspect-target",
        action="store_true",
        help="Dry run that also connects read-only: identity check, preconditions, selection sizes",
    )
    parser.add_argument("--timeout-sec", type=int, default=600)
    parser.add_argument("--ledger-out", default="", help="Default: artifacts/refresh/<id>/migration_ledger.json")
    return parser


def main(
    argv: list[str] | None = None,
    *,
    client_factory: Callable[..., Any] | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.list:
            for spec in list_migrations(args.migrations_dir):
                print(f"{spec.id}\t{spec.kind}\t{spec.description}")
            return EXIT_OK
        if not args.migration:
            print("error: --migration is required (or use --list)", file=sys.stderr)
            return EXIT_SAFETY
        spec = load_migration(resolve_migration_path(args.migration, args.migrations_dir))
        extra = args.protected_config if args.protected_config is not None else list(DEFAULT_EXTRA_PROTECTED_CONFIGS)
        if Path(args.primary_config).resolve() != (PROJECT_ROOT / DEFAULT_PRIMARY_CONFIG).resolve():
            # A custom primary never removes protection from the default primary graph.
            extra = [str(PROJECT_ROOT / DEFAULT_PRIMARY_CONFIG), *extra]
        protected, notes = load_protected_endpoints(args.primary_config, extra)
    except MigrationSpecError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_SAFETY

    decision = evaluate_target_safety(
        target_uri=args.target_bolt_uri,
        target_database=args.target_database,
        confirm_copy_database=args.confirm_copy_database,
        protected=protected,
        allow_override=args.override,
    )
    decision.warnings.extend(notes)
    print(render_plan(spec, decision, args))
    if not decision.ok:
        print("REFUSED: no connection was opened and nothing was written.", file=sys.stderr)
        return EXIT_SAFETY
    if not (args.apply or args.inspect_target):
        print("Dry run only: no connection opened. Use --inspect-target to size the change or --apply to write.")
        return EXIT_OK

    factory = client_factory or _default_client_factory
    ledger: dict[str, Any] = {
        "migration_id": spec.id,
        "kind": spec.kind,
        "graph_profile": spec.graph_profile,
        "description": spec.description,
        **spec.checksums(),
        "meta_path": str(spec.meta_path.relative_to(PROJECT_ROOT)) if spec.meta_path.is_relative_to(PROJECT_ROOT) else str(spec.meta_path),
        "target_endpoint": "%s:%s" % normalize_bolt_endpoint(args.target_bolt_uri),
        "target_database": args.target_database,
        "mode": "apply" if args.apply else "inspect",
        "git_revision": _git_revision(),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "safety_warnings": list(decision.warnings),
        "expected_schema_diff": spec.expected_schema_diff,
    }
    target = factory(args.target_bolt_uri, args.target_user, args.target_password, args.target_database, args.timeout_sec)
    protected_clients: dict[str, Any] = {}
    for endpoint in protected:
        try:
            protected_clients[endpoint.config_path] = factory(
                endpoint.uri, endpoint.user, endpoint.password, endpoint.database, 30
            )
        except Exception:
            protected_clients[endpoint.config_path] = None
    try:
        identity, target_info = live_identity_check(target, protected_clients, allow_override=args.override)
        ledger["target_db_info"] = target_info
        ledger["identity_warnings"] = identity.warnings
        for warning in identity.warnings:
            print(f"warning: {warning}")
        if not identity.ok:
            for error in identity.errors:
                print(f"REFUSED: {error}", file=sys.stderr)
            ledger["status"] = "identity_refused"
            ledger["identity_errors"] = identity.errors
            _write_ledger(args, spec, ledger)
            return EXIT_SAFETY
        started = time.perf_counter()
        outcome = execute_migration(spec, target, apply=args.apply, ledger=ledger)
        ledger["wall_seconds"] = round(time.perf_counter() - started, 3)
    finally:
        for client in [target, *protected_clients.values()]:
            close = getattr(client, "close", None)
            if callable(close):
                close()
    ledger["finished_at"] = datetime.now(timezone.utc).isoformat()
    path = _write_ledger(args, spec, ledger)
    print(json.dumps({k: ledger.get(k) for k in ("status", "parameters", "affected_total")}, default=str, indent=2))
    print(f"Ledger: {path}")
    return outcome.exit_code


def _write_ledger(args: argparse.Namespace, spec: MigrationSpec, ledger: dict[str, Any]) -> Path:
    path = Path(args.ledger_out or f"artifacts/refresh/{spec.id}/migration_ledger.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    raise SystemExit(main())
