"""Benchmark refresh audit for schema migrations and data drift.

Given an exported benchmark and two read-only graph handles (the original graph
and a migrated copy), every reference Cypher query is re-executed on both and
classified as one of:

``unchanged_answer``         executes on both graphs with the same row set
``silently_changed_answer``  executes on both graphs, different row set
``now_empty``                non-empty on the original, empty on the migrated copy
``execution_error``          fails at runtime on the migrated copy
``broken_schema``            new validator errors against the migrated schema
``original_execution_error`` fails on the original graph (pre-existing defect;
                             excluded from refresh rates and reported separately)

Precedence: ``original_execution_error`` > ``broken_schema`` > ``execution_error``
> ``now_empty`` > ``silently_changed_answer`` > ``unchanged_answer``. For
``broken_schema`` items the runtime outcome on the migrated graph is still
recorded, because Neo4j usually does not raise on unknown labels/types/properties
and instead returns empty or different rows.

The module also derives (a) a *static* impact plan from schema atoms alone,
(b) an execution-verified incremental refresh plan, (c) optional rename-aware
mechanical rewrites, and (d) the "accuracy misestimate" of a downstream model
scored against stale versus refreshed references. Nothing here writes to a graph:
all execution goes through the read-only ``client.run`` path.
"""

from __future__ import annotations

import functools
import hashlib
import json
import math
import re
import socket
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from .cypher_parser import OptionalCypherParser
from .diversity_metrics import canonical_query_signature, template_family_signature
from .models import ExecutionResult, SchemaSummary
from .schema_diff import (
    DEFAULT_REWRITE_CONFIDENCE,
    SchemaDiff,
    parse_pattern_text,
    prune_ghost_schema_entries,
)
from .validator import clean_cypher, structural_features, validate_cypher

REFRESH_CLASSES = (
    "unchanged_answer",
    "silently_changed_answer",
    "now_empty",
    "execution_error",
    "broken_schema",
    "original_execution_error",
)
REFRESH_ACTIONS = ("reuse", "refresh_answer", "rename_rewrite", "regenerate", "exclude")
STATIC_ACTIONS = ("reuse", "reexecute", "rewrite", "regenerate")
CARRIED_FORWARD_ACTIONS = ("reuse", "refresh_answer", "rename_rewrite")

_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
_NODE_RE = re.compile(
    r"\(\s*(?P<var>" + _IDENT + r")?\s*"
    r"(?P<labels>(?::\s*" + _IDENT + r"\s*)*)"
    r"(?P<props>\{[^{}]*\})?\s*\)"
)
_REL_RE = re.compile(
    r"(?P<left><)?-\s*\[\s*(?P<var>" + _IDENT + r")?\s*"
    r"(?::\s*(?P<types>" + _IDENT + r"(?:\s*\|\s*:?\s*" + _IDENT + r")*))?\s*"
    r"(?P<varlen>\*[0-9.\s]*)?\s*(?P<props>\{[^{}]*\})?\s*\]\s*-(?P<right>>)?"
)
_PROP_ACCESS_RE = re.compile(r"(?<![\w.$])(?P<var>" + _IDENT + r")\.(?P<prop>" + _IDENT + r")")
_MAP_KEY_RE = re.compile(r"(?P<key>" + _IDENT + r")\s*:")
_MAP_STRING_KEY_RE = re.compile(r"(?P<key>" + _IDENT + r")\s*:\s*['\"]")
_ALIAS_RE = re.compile(r"\b(?P<src>" + _IDENT + r")\s+AS\s+(?P<dst>" + _IDENT + r")\b", re.I)
_TOKEN_RE = re.compile(_IDENT)
_LITERAL_COMPARE_RE = re.compile(r"^\s*(?:=|<>|IN\b|STARTS\s+WITH|ENDS\s+WITH|CONTAINS)\s*['\"\[]", re.I)

LOCAL_HOST_ALIASES = {"", "localhost", "127.0.0.1", "::1", "0.0.0.0", "[::1]"}


class ReadOnlyClient(Protocol):
    def run(
        self,
        query: str,
        params: dict[str, Any] | None = None,
        *,
        read_only: bool = True,
        limit_rows: int | None = None,
    ) -> ExecutionResult: ...


# ---------------------------------------------------------------------------
# Endpoint helpers (shared with scripts/apply_graph_migration.py)


def normalize_bolt_endpoint(uri: str, *, default_port: int = 7687) -> tuple[str, int]:
    """Return a comparable ``(host, port)`` for a Bolt/Neo4j URI.

    Loopback names and this machine's own hostname collapse to ``localhost`` so
    ``bolt://127.0.0.1:7687`` and ``neo4j://localhost`` compare equal.
    """

    raw = uri.strip()
    if "://" not in raw:
        raw = "bolt://" + raw
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    try:
        port = parsed.port or default_port
    except ValueError:
        port = default_port
    if host in LOCAL_HOST_ALIASES or host.startswith("127."):
        return "localhost", port
    local_names = _local_host_names()
    if host in local_names or host.split(".")[0] in local_names:
        return "localhost", port
    return host, port


@functools.lru_cache(maxsize=1)
def _local_host_names() -> frozenset[str]:
    try:
        hostname = socket.gethostname().lower()
        names = {hostname, socket.getfqdn().lower(), hostname.split(".")[0]}
    except OSError:  # pragma: no cover - platform specific
        names = set()
    names.discard("")
    return frozenset(names)


def endpoints_match(left_uri: str, right_uri: str) -> bool:
    return normalize_bolt_endpoint(left_uri) == normalize_bolt_endpoint(right_uri)


# ---------------------------------------------------------------------------
# Cypher atom extraction


def mask_string_literals(query: str) -> str:
    """Replace string-literal contents with ``_`` while preserving offsets."""

    out: list[str] = []
    quote: str | None = None
    escaped = False
    for char in query:
        if quote:
            if escaped:
                escaped = False
                out.append("_")
            elif char == "\\":
                escaped = True
                out.append("_")
            elif char == quote:
                quote = None
                out.append(char)
            else:
                out.append("_")
            continue
        if char in {"'", '"'}:
            quote = char
        out.append(char)
    return "".join(out)


@dataclass
class _NodeMatch:
    start: int
    end: int
    var: str | None
    labels: list[tuple[str, int, int]]
    props_span: tuple[int, int] | None


@dataclass
class _RelMatch:
    start: int
    end: int
    var: str | None
    types: list[tuple[str, int, int]]
    props_span: tuple[int, int] | None
    direction: str


@dataclass
class CypherStructure:
    nodes: list[_NodeMatch]
    rels: list[_RelMatch]
    var_labels: dict[str, str]
    var_rel_types: dict[str, str]
    masked: str


def _tokens_in_group(match: re.Match[str], group: str) -> list[tuple[str, int, int]]:
    text = match.group(group)
    if not text:
        return []
    base = match.start(group)
    return [(tok.group(0), base + tok.start(), base + tok.end()) for tok in _TOKEN_RE.finditer(text)]


def parse_cypher_structure(query: str) -> CypherStructure:
    masked = mask_string_literals(query)
    nodes: list[_NodeMatch] = []
    for match in _NODE_RE.finditer(masked):
        nodes.append(
            _NodeMatch(
                start=match.start(),
                end=match.end(),
                var=match.group("var"),
                labels=_tokens_in_group(match, "labels"),
                props_span=match.span("props") if match.group("props") else None,
            )
        )
    rels: list[_RelMatch] = []
    for match in _REL_RE.finditer(masked):
        left, right = bool(match.group("left")), bool(match.group("right"))
        if left and not right:
            direction = "incoming"
        elif right and not left:
            direction = "outgoing"
        else:
            direction = "undirected"
        rels.append(
            _RelMatch(
                start=match.start(),
                end=match.end(),
                var=match.group("var"),
                types=_tokens_in_group(match, "types"),
                props_span=match.span("props") if match.group("props") else None,
                direction=direction,
            )
        )
    var_labels: dict[str, str] = {}
    for node in nodes:
        if node.var and node.labels:
            var_labels.setdefault(node.var, node.labels[0][0])
    var_rel_types: dict[str, str] = {}
    for rel in rels:
        if rel.var and len(rel.types) == 1:
            var_rel_types.setdefault(rel.var, rel.types[0][0])
    for alias in _ALIAS_RE.finditer(masked):
        src, dst = alias.group("src"), alias.group("dst")
        if src in var_labels:
            var_labels.setdefault(dst, var_labels[src])
        if src in var_rel_types:
            var_rel_types.setdefault(dst, var_rel_types[src])
    return CypherStructure(nodes, rels, var_labels, var_rel_types, masked)


def _node_label(node: _NodeMatch | None, var_labels: Mapping[str, str]) -> str:
    if node is None:
        return "*"
    if node.labels:
        return node.labels[0][0]
    if node.var and node.var in var_labels:
        return var_labels[node.var]
    return "*"


def _adjacent_nodes(
    structure: CypherStructure,
) -> list[tuple[_RelMatch, _NodeMatch | None, _NodeMatch | None]]:
    by_end = {node.end: node for node in structure.nodes}
    by_start = {node.start: node for node in structure.nodes}
    text = structure.masked
    triples = []
    for rel in structure.rels:
        k = rel.start
        while k > 0 and text[k - 1].isspace():
            k -= 1
        j = rel.end
        while j < len(text) and text[j].isspace():
            j += 1
        triples.append((rel, by_end.get(k), by_start.get(j)))
    return triples


def extract_schema_atoms(query: str) -> set[str]:
    """Extract the schema atoms a Cypher query touches (see ``schema_diff``)."""

    structure = parse_cypher_structure(query)
    masked = structure.masked
    atoms: set[str] = set()
    for node in structure.nodes:
        for label, _, _ in node.labels:
            atoms.add(f"label:{label}")
        if node.props_span:
            owner = _node_label(node, structure.var_labels)
            props_text = masked[node.props_span[0] : node.props_span[1]]
            for key in _MAP_KEY_RE.finditer(props_text):
                atoms.add(f"prop:{owner}.{key.group('key')}")
            for key in _MAP_STRING_KEY_RE.finditer(props_text):
                atoms.add(f"cat:{owner}.{key.group('key')}")
    for rel, left, right in _adjacent_nodes(structure):
        for rel_type, _, _ in rel.types:
            atoms.add(f"rel:{rel_type}")
            left_label = _node_label(left, structure.var_labels)
            right_label = _node_label(right, structure.var_labels)
            if rel.direction == "outgoing":
                atoms.add(f"pattern:(:{left_label})-[:{rel_type}]->(:{right_label})")
            elif rel.direction == "incoming":
                atoms.add(f"pattern:(:{right_label})-[:{rel_type}]->(:{left_label})")
            else:
                atoms.add(f"pattern:(:{left_label})-[:{rel_type}]->(:{right_label})")
                atoms.add(f"pattern:(:{right_label})-[:{rel_type}]->(:{left_label})")
            if rel.props_span:
                props_text = masked[rel.props_span[0] : rel.props_span[1]]
                for key in _MAP_KEY_RE.finditer(props_text):
                    atoms.add(f"relprop:{rel_type}.{key.group('key')}")
    for access in _PROP_ACCESS_RE.finditer(masked):
        var, prop = access.group("var"), access.group("prop")
        after = masked[access.end() : access.end() + 1]
        if after == "(":
            continue  # namespaced function call, e.g. duration.between(...)
        if var in structure.var_labels:
            owner_kind, owner = "prop", structure.var_labels[var]
        elif var in structure.var_rel_types:
            owner_kind, owner = "relprop", structure.var_rel_types[var]
        else:
            owner_kind, owner = "prop", "*"
        atoms.add(f"{owner_kind}:{owner}.{prop}")
        if owner_kind == "prop" and _LITERAL_COMPARE_RE.match(masked[access.end() :]):
            atoms.add(f"cat:{owner}.{prop}")
    return atoms


def atom_matches(item_atom: str, changed_atom: str) -> bool:
    """Wildcard-aware match between an item atom and a schema-diff atom."""

    item_kind, _, item_body = item_atom.partition(":")
    changed_kind, _, changed_body = changed_atom.partition(":")
    if item_kind != changed_kind:
        return False
    if item_kind in {"label", "rel"}:
        return item_body == changed_body
    if item_kind in {"prop", "relprop", "cat"}:
        item_owner, _, item_prop = item_body.partition(".")
        changed_owner, _, changed_prop = changed_body.partition(".")
        if item_prop != changed_prop:
            return False
        return "*" in {item_owner, changed_owner} or item_owner == changed_owner
    if item_kind == "pattern":
        item_pattern = parse_pattern_text(item_body)
        changed_pattern = parse_pattern_text(changed_body)
        if not item_pattern or not changed_pattern:
            return item_body == changed_body
        if item_pattern[1] != changed_pattern[1]:
            return False
        return all(
            "*" in {a, b} or a == b
            for a, b in ((item_pattern[0], changed_pattern[0]), (item_pattern[2], changed_pattern[2]))
        )
    return item_body == changed_body


def touched_atoms(item_atoms: Iterable[str], changed_atoms: Iterable[str]) -> list[str]:
    item_list = list(item_atoms)
    return sorted(
        {changed for changed in changed_atoms if any(atom_matches(item, changed) for item in item_list)}
    )


# ---------------------------------------------------------------------------
# Answer comparison


def canonical_value(value: Any, *, float_digits: int = 10, sort_lists: bool = True) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        if value == 0:
            return "0"
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return format(value, f".{float_digits}g")
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, Mapping):
        items = sorted((str(k), v) for k, v in value.items())
        return "{" + ",".join(
            json.dumps(k) + ":" + canonical_value(v, float_digits=float_digits, sort_lists=sort_lists)
            for k, v in items
        ) + "}"
    if isinstance(value, (list, tuple, set, frozenset)):
        parts = [canonical_value(v, float_digits=float_digits, sort_lists=sort_lists) for v in value]
        if sort_lists or isinstance(value, (set, frozenset)):
            parts.sort()
        return "[" + ",".join(parts) + "]"
    if hasattr(value, "items") and hasattr(value, "labels"):  # neo4j Node
        props = dict(value.items())
        return "node" + canonical_value(
            {"labels": sorted(value.labels), "properties": props}, float_digits=float_digits
        )
    if hasattr(value, "items") and hasattr(value, "type"):  # neo4j Relationship
        props = dict(value.items())
        return "rel" + canonical_value(
            {"type": str(value.type), "properties": props}, float_digits=float_digits
        )
    if hasattr(value, "iso_format"):
        return str(value.iso_format())
    return str(value)


def canonical_row(row: Mapping[str, Any], *, float_digits: int = 10) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((str(k), canonical_value(v, float_digits=float_digits)) for k, v in row.items()))


def compare_answers(
    original_rows: list[dict[str, Any]],
    migrated_rows: list[dict[str, Any]],
    *,
    float_digits: int = 10,
) -> dict[str, Any]:
    original = [canonical_row(r, float_digits=float_digits) for r in original_rows]
    migrated = [canonical_row(r, float_digits=float_digits) for r in migrated_rows]
    a, b = set(original), set(migrated)
    union = a | b
    return {
        "equal": a == b,
        "ordered_equal": original == migrated,
        "jaccard": (len(a & b) / len(union)) if union else 1.0,
        "original_only": len(a - b),
        "migrated_only": len(b - a),
    }


def _limit_risk(query: str, row_count: int) -> dict[str, bool]:
    upper = mask_string_literals(query).upper()
    limit_match = re.search(r"\bLIMIT\s+(\d+)", upper)
    has_order = bool(re.search(r"\bORDER\s+BY\b", upper))
    unordered_limit = bool(limit_match) and not has_order
    truncated = bool(limit_match) and row_count >= int(limit_match.group(1))
    return {"unordered_limit": unordered_limit, "truncated_at_limit": truncated}


def safe_run(client: ReadOnlyClient, query: str) -> ExecutionResult:
    """Read-only execution that never raises (write tokens become a failure)."""

    try:
        return client.run(query, read_only=True)
    except ValueError as exc:
        return ExecutionResult(success=False, error=f"read_only_violation: {exc}")
    except Exception as exc:  # pragma: no cover - defensive for live drivers
        return ExecutionResult(success=False, error=f"{type(exc).__name__}: {exc}")


def classify_refresh_outcome(
    *,
    original: ExecutionResult,
    migrated: ExecutionResult,
    new_schema_errors: list[str],
    float_digits: int = 10,
) -> dict[str, Any]:
    """Classify one benchmark item; pure function over execution results."""

    comparison: dict[str, Any] | None = None
    if original.success and migrated.success:
        comparison = compare_answers(original.rows, migrated.rows, float_digits=float_digits)
    if not migrated.success:
        runtime_outcome = "error"
    elif not migrated.rows:
        runtime_outcome = "empty" if original.rows else ("unchanged" if original.success else "empty")
    elif comparison is not None and comparison["equal"]:
        runtime_outcome = "unchanged"
    else:
        runtime_outcome = "changed"

    if not original.success:
        refresh_class = "original_execution_error"
    elif new_schema_errors:
        refresh_class = "broken_schema"
    elif not migrated.success:
        refresh_class = "execution_error"
    elif original.rows and not migrated.rows:
        refresh_class = "now_empty"
    elif comparison is not None and not comparison["equal"]:
        refresh_class = "silently_changed_answer"
    else:
        refresh_class = "unchanged_answer"
    return {
        "refresh_class": refresh_class,
        "migrated_runtime_outcome": runtime_outcome,
        "answer_comparison": comparison,
    }


_PARSER: OptionalCypherParser | None = None


def _validate(query: str, schema: SchemaSummary | None = None) -> Any:
    """``validate_cypher`` with one shared optional-parser instance."""

    global _PARSER
    if _PARSER is None:
        _PARSER = OptionalCypherParser()
    return validate_cypher(query, schema, parser=_PARSER)


def _issue_keys(result: Any, level: str) -> set[tuple[str, str]]:
    return {(issue.code, issue.message) for issue in result.issues if issue.level == level}


def new_validation_issues(
    query: str,
    original_schema: SchemaSummary,
    migrated_schema: SchemaSummary,
) -> dict[str, list[dict[str, str]]]:
    """Validator issues that appear only under the migrated schema."""

    before = _validate(query, original_schema)
    after = _validate(query, migrated_schema)
    new_errors = sorted(_issue_keys(after, "error") - _issue_keys(before, "error"))
    new_warnings = sorted(_issue_keys(after, "warning") - _issue_keys(before, "warning"))
    return {
        "errors": [{"code": code, "message": message} for code, message in new_errors],
        "warnings": [{"code": code, "message": message} for code, message in new_warnings],
    }


# ---------------------------------------------------------------------------
# Rename-aware rewrite (conservative, token-span based, fully logged)


@dataclass
class RenameRewrite:
    attempted: bool
    applied: bool
    cypher: str
    replacements: list[dict[str, Any]] = field(default_factory=list)
    skipped_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempted": self.attempted,
            "applied": self.applied,
            "replacements": self.replacements,
            "skipped_reason": self.skipped_reason,
        }


def rename_rewrite_cypher(
    query: str,
    diff: SchemaDiff,
    *,
    min_confidence: float = DEFAULT_REWRITE_CONFIDENCE,
) -> RenameRewrite:
    """Rewrite label/type/property tokens using confident renames from a diff.

    Only identifier tokens inside node labels, relationship types, inline
    property-map keys, and ``var.prop`` accesses with a resolved owner are
    replaced; literals are never touched. The rewrite is skipped (and the reason
    logged) for backtick-quoted identifiers, procedure ``CALL`` clauses, or a
    renamed property accessed through a variable whose label cannot be resolved.
    """

    rel_map = diff.rename_map("relationship_type", min_confidence=min_confidence)
    label_map = diff.rename_map("label", min_confidence=min_confidence)
    node_prop_map = diff.rename_map("node_property", min_confidence=min_confidence)
    rel_prop_map = diff.rename_map("relationship_property", min_confidence=min_confidence)
    if not (rel_map or label_map or node_prop_map or rel_prop_map):
        return RenameRewrite(False, False, query, skipped_reason="no confident renames in diff")
    if "`" in query:
        return RenameRewrite(True, False, query, skipped_reason="backtick-quoted identifiers")
    structure = parse_cypher_structure(query)
    masked = structure.masked
    if re.search(r"\bCALL\b", masked, re.I):
        return RenameRewrite(True, False, query, skipped_reason="procedure or subquery CALL clause")

    renamed_node_props = {key.partition(".")[2] for key in node_prop_map}
    renamed_rel_props = {key.partition(".")[2] for key in rel_prop_map}
    replacements: list[tuple[int, int, str, dict[str, Any]]] = []

    def add(start: int, end: int, new: str, kind: str, old: str) -> None:
        replacements.append((start, end, new, {"kind": kind, "before": old, "after": new, "offset": start}))

    for node in structure.nodes:
        for label, start, end in node.labels:
            if label in label_map:
                add(start, end, label_map[label], "label", label)
        if node.props_span:
            owner = _node_label(node, structure.var_labels)
            offset = node.props_span[0]
            props_text = masked[node.props_span[0] : node.props_span[1]]
            for key in _MAP_KEY_RE.finditer(props_text):
                name = key.group("key")
                mapped = node_prop_map.get(f"{owner}.{name}")
                if mapped:
                    add(offset + key.start("key"), offset + key.end("key"), mapped, "node_property", name)
                elif owner == "*" and name in renamed_node_props:
                    return RenameRewrite(
                        True, False, query, skipped_reason=f"unresolved owner for renamed property `{name}`"
                    )
    for rel in structure.rels:
        for rel_type, start, end in rel.types:
            if rel_type in rel_map:
                add(start, end, rel_map[rel_type], "relationship_type", rel_type)
        if rel.props_span and len(rel.types) == 1:
            owner = rel.types[0][0]
            offset = rel.props_span[0]
            props_text = masked[rel.props_span[0] : rel.props_span[1]]
            for key in _MAP_KEY_RE.finditer(props_text):
                name = key.group("key")
                mapped = rel_prop_map.get(f"{owner}.{name}")
                if mapped:
                    add(
                        offset + key.start("key"),
                        offset + key.end("key"),
                        mapped,
                        "relationship_property",
                        name,
                    )
    for access in _PROP_ACCESS_RE.finditer(masked):
        var, prop = access.group("var"), access.group("prop")
        if masked[access.end() : access.end() + 1] == "(":
            continue
        start, end = access.span("prop")
        if var in structure.var_labels:
            mapped = node_prop_map.get(f"{structure.var_labels[var]}.{prop}")
            if mapped:
                add(start, end, mapped, "node_property", prop)
        elif var in structure.var_rel_types:
            mapped = rel_prop_map.get(f"{structure.var_rel_types[var]}.{prop}")
            if mapped:
                add(start, end, mapped, "relationship_property", prop)
        elif prop in renamed_node_props or prop in renamed_rel_props:
            return RenameRewrite(
                True, False, query, skipped_reason=f"unresolved owner for renamed property `{prop}`"
            )

    if not replacements:
        return RenameRewrite(True, False, query, skipped_reason="query uses no renamed schema atoms")
    rewritten = query
    for start, end, new, _info in sorted(replacements, key=lambda r: r[0], reverse=True):
        rewritten = rewritten[:start] + new + rewritten[end:]
    return RenameRewrite(
        True,
        True,
        rewritten,
        replacements=[info for *_rest, info in sorted(replacements, key=lambda r: r[0])],
    )


# ---------------------------------------------------------------------------
# Benchmark loading


def load_benchmark_rows(path: str | Path) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Load ``all.jsonl`` (or a JSONL file) plus an id->split map when available."""

    base = Path(path)
    split_by_id: dict[str, str] = {}
    if base.is_dir():
        rows = _read_jsonl(base / "all.jsonl")
        for split in ("train", "dev", "test"):
            split_path = base / f"{split}.jsonl"
            if split_path.exists():
                for row in _read_jsonl(split_path):
                    split_by_id[str(row.get("id"))] = split
    else:
        rows = _read_jsonl(base)
    for row in rows:
        if row.get("split") and str(row.get("id")) not in split_by_id:
            split_by_id[str(row.get("id"))] = str(row["split"])
    return rows, split_by_id


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def reference_cypher(row: Mapping[str, Any]) -> str:
    return str(row.get("normalized_cypher") or row.get("cypher") or "")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Audit


@dataclass
class RefreshAuditOptions:
    migration_id: str
    graph_profile: str
    float_digits: int = 10
    rename_rewrite: bool = True
    rename_min_confidence: float = DEFAULT_REWRITE_CONFIDENCE
    prune_ghost_schema_entries: bool = True
    result_sample_limit: int = 5
    top_n: int = 25


def static_action_for(
    item_atoms: Iterable[str],
    diff: SchemaDiff | None,
    *,
    min_confidence: float = DEFAULT_REWRITE_CONFIDENCE,
) -> tuple[str, list[str], list[str]]:
    """Plan an item from schema atoms only (no execution)."""

    if diff is None:
        return "reexecute", [], []
    atoms = list(item_atoms)
    breaking = touched_atoms(atoms, diff.breaking_atoms())
    drift = touched_atoms(atoms, diff.drift_atoms())
    if breaking:
        renamed = diff.renamed_atoms(min_confidence=min_confidence)
        action = "rewrite" if all(atom in renamed for atom in breaking) else "regenerate"
    elif drift:
        action = "reexecute"
    else:
        action = "reuse"
    return action, breaking, drift


def audit_benchmark_refresh(
    rows: list[dict[str, Any]],
    *,
    original_client: ReadOnlyClient,
    migrated_client: ReadOnlyClient,
    original_schema: SchemaSummary,
    migrated_schema: SchemaSummary,
    options: RefreshAuditOptions,
    diff: SchemaDiff | None = None,
    split_by_id: Mapping[str, str] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Audit every item of ``options.graph_profile``.

    Returns ``(item_records, carried_forward_rows)``. Item records contain ids,
    classes, atoms, and execution metadata (no question text or literals);
    carried-forward rows are benchmark rows that remain usable after the
    migration, with refreshed answer samples and a ``refresh`` provenance block.
    """

    split_by_id = split_by_id or {}
    if options.prune_ghost_schema_entries:
        migrated_schema, _ = prune_ghost_schema_entries(migrated_schema)
        original_schema, _ = prune_ghost_schema_entries(original_schema)
    audited = [row for row in rows if str(row.get("graph_profile")) == options.graph_profile]
    items: list[dict[str, Any]] = []
    carried: list[dict[str, Any]] = []
    refreshed_at = datetime.now(timezone.utc).isoformat()
    for index, row in enumerate(audited):
        if progress:
            progress(index, len(audited))
        query = reference_cypher(row)
        item_id = str(row.get("id"))
        atoms = sorted(extract_schema_atoms(query))
        static_action, breaking, drift = static_action_for(
            atoms, diff, min_confidence=options.rename_min_confidence
        )
        issues = new_validation_issues(query, original_schema, migrated_schema)
        original = safe_run(original_client, query)
        migrated = safe_run(migrated_client, query)
        outcome = classify_refresh_outcome(
            original=original,
            migrated=migrated,
            new_schema_errors=[issue["code"] for issue in issues["errors"]],
            float_digits=options.float_digits,
        )
        refresh_class = outcome["refresh_class"]
        limit_risk = _limit_risk(query, len(original.rows))
        record: dict[str, Any] = {
            "id": item_id,
            "migration_id": options.migration_id,
            "graph_profile": options.graph_profile,
            "category": row.get("category"),
            "difficulty": row.get("difficulty") or (row.get("structural_features") or {}).get("difficulty"),
            "split": split_by_id.get(item_id),
            "template_family": template_family_signature(row),
            "query_signature": canonical_query_signature(query),
            "reference_cypher_sha256": sha256_text(query),
            "refresh_class": refresh_class,
            "migrated_runtime_outcome": outcome["migrated_runtime_outcome"],
            "answer_comparison": outcome["answer_comparison"],
            "schema_atoms": atoms,
            "touched_breaking_atoms": breaking,
            "touched_drift_atoms": drift,
            "static_action": static_action,
            "new_schema_errors": issues["errors"],
            "new_schema_warnings": issues["warnings"],
            "original_execution": _execution_meta(original),
            "migrated_execution": _execution_meta(migrated),
            "unordered_limit": limit_risk["unordered_limit"],
            "truncated_at_limit": limit_risk["truncated_at_limit"],
            "nondeterminism_risk": limit_risk["unordered_limit"] and limit_risk["truncated_at_limit"],
        }

        action, carried_query, carried_result, rewrite = _decide_action(
            refresh_class=refresh_class,
            query=query,
            original=original,
            migrated=migrated,
            migrated_client=migrated_client,
            original_schema=original_schema,
            migrated_schema=migrated_schema,
            diff=diff,
            options=options,
        )
        record["refresh_action"] = action
        if rewrite is not None:
            record["rename_rewrite"] = rewrite
        items.append(record)

        if action in CARRIED_FORWARD_ACTIONS and carried_result is not None:
            carried.append(
                _carried_forward_row(
                    row,
                    action=action,
                    refresh_class=refresh_class,
                    query=carried_query,
                    original_query=query,
                    result=carried_result,
                    options=options,
                    refreshed_at=refreshed_at,
                    split=split_by_id.get(item_id),
                )
            )
    return items, carried


def _execution_meta(result: ExecutionResult) -> dict[str, Any]:
    return {
        "success": bool(result.success),
        "row_count": len(result.rows) if result.success else None,
        "error": (str(result.error)[:500] if result.error else None),
        "latency_ms": result.latency_ms,
    }


def _decide_action(
    *,
    refresh_class: str,
    query: str,
    original: ExecutionResult,
    migrated: ExecutionResult,
    migrated_client: ReadOnlyClient,
    original_schema: SchemaSummary,
    migrated_schema: SchemaSummary,
    diff: SchemaDiff | None,
    options: RefreshAuditOptions,
) -> tuple[str, str, ExecutionResult | None, dict[str, Any] | None]:
    if refresh_class == "original_execution_error":
        return "exclude", query, None, None
    if refresh_class == "unchanged_answer":
        return "reuse", query, migrated, None
    if refresh_class == "silently_changed_answer":
        return "refresh_answer", query, migrated, None
    if refresh_class in {"now_empty", "execution_error"}:
        return "regenerate", query, None, None
    # broken_schema
    if not options.rename_rewrite or diff is None:
        return "regenerate", query, None, None
    rewrite = rename_rewrite_cypher(query, diff, min_confidence=options.rename_min_confidence)
    log = rewrite.to_dict()
    if not rewrite.applied:
        return "regenerate", query, None, log
    rewritten = rewrite.cypher
    # Errors the reference already had under its own schema are pre-existing
    # defects, not rewrite failures; anything else blocks the rewrite.
    baseline = _issue_keys(_validate(query, original_schema), "error")
    post_validation = _validate(rewritten, migrated_schema)
    post_errors = _issue_keys(post_validation, "error") - baseline
    log["rewritten_cypher_sha256"] = sha256_text(rewritten)
    log["post_rewrite_error_codes"] = sorted({issue.code for issue in post_validation.errors})
    log["post_rewrite_new_error_codes"] = sorted({code for code, _message in post_errors})
    if post_errors:
        log["outcome"] = "invalid_after_rewrite"
        return "regenerate", query, None, log
    result = safe_run(migrated_client, rewritten)
    log["execution"] = _execution_meta(result)
    if not result.success:
        log["outcome"] = "execution_error_after_rewrite"
        return "regenerate", query, None, log
    if not result.rows:
        log["outcome"] = "empty_after_rewrite"
        return "regenerate", query, None, log
    comparison = compare_answers(original.rows, result.rows, float_digits=options.float_digits)
    log["answer_preserved"] = bool(comparison["equal"])
    log["answer_jaccard"] = comparison["jaccard"]
    log["outcome"] = "rewritten"
    return "rename_rewrite", rewritten, result, log


def _jsonable_rows(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return json.loads(json.dumps(rows[:limit], default=str))


def _carried_forward_row(
    row: dict[str, Any],
    *,
    action: str,
    refresh_class: str,
    query: str,
    original_query: str,
    result: ExecutionResult,
    options: RefreshAuditOptions,
    refreshed_at: str,
    split: str | None,
) -> dict[str, Any]:
    new_row = dict(row)
    gates_rechecked: dict[str, Any] = {"execution_success": True, "non_empty": bool(result.rows)}
    if action == "rename_rewrite":
        validation = _validate(query)
        new_row["cypher"] = query
        new_row["normalized_cypher"] = clean_cypher(query)
        new_row["structural_features"] = structural_features(clean_cypher(query))
        gates_rechecked.update(
            {
                "read_only": validation.read_only,
                "syntax_valid": validation.syntax_valid,
                "schema_valid": True,
            }
        )
    if action != "reuse":
        new_row["result_rows_sample"] = _jsonable_rows(result.rows, options.result_sample_limit)
        new_row["result_row_count_observed"] = len(result.rows)
    new_row["refresh"] = {
        "migration_id": options.migration_id,
        "action": action,
        "refresh_class": refresh_class,
        "original_cypher_sha256": sha256_text(original_query),
        "refreshed_at": refreshed_at,
        "split": split,
        "gates_rechecked": gates_rechecked,
        # A token-renamed reference keeps the question but has not been re-judged.
        "judge_recheck_required": action == "rename_rewrite",
    }
    return new_row


# ---------------------------------------------------------------------------
# Reporting


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _class_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(str(item["refresh_class"]) for item in items)
    return {name: counts.get(name, 0) for name in REFRESH_CLASSES}


def _class_block(items: list[dict[str, Any]]) -> dict[str, Any]:
    counts = _class_counts(items)
    valid = len(items) - counts["original_execution_error"]
    block: dict[str, Any] = {"n": len(items), "n_valid_original": valid, "counts": counts}
    block["rates"] = {
        name: _rate(counts[name], valid) for name in REFRESH_CLASSES if name != "original_execution_error"
    }
    affected = valid - counts["unchanged_answer"]
    block["affected"] = affected
    block["affected_rate"] = _rate(affected, valid)
    return block


def _grouped(items: list[dict[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        groups[str(item.get(key))].append(item)
    return {name: _class_block(group) for name, group in sorted(groups.items())}


def _top_groups(items: list[dict[str, Any]], key: str, top_n: int) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        groups[str(item.get(key))].append(item)
    affected_groups = {
        name: group
        for name, group in groups.items()
        if any(item["refresh_class"] not in {"unchanged_answer", "original_execution_error"} for item in group)
    }
    ranked = sorted(
        affected_groups.items(),
        key=lambda kv: (-_class_block(kv[1])["affected"], kv[0]),
    )
    return {
        "distinct_total": len(groups),
        "distinct_affected": len(affected_groups),
        "distinct_fully_reusable": sum(
            1
            for group in groups.values()
            if all(item["refresh_action"] == "reuse" for item in group)
        ),
        "top_affected": [
            {"signature": name, **_class_block(group)} for name, group in ranked[:top_n]
        ],
    }


def incremental_refresh_plan(items: list[dict[str, Any]], *, top_n: int = 25) -> dict[str, Any]:
    actions = Counter(str(item["refresh_action"]) for item in items)
    n = len(items)
    by_category: dict[str, dict[str, Any]] = {}
    targets: dict[str, int] = {}
    targets_by_split: dict[str, dict[str, int]] = {}
    category_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        category_groups[str(item.get("category"))].append(item)
    for category, group in sorted(category_groups.items()):
        counts = Counter(str(item["refresh_action"]) for item in group)
        regenerate = counts.get("regenerate", 0)
        by_category[category] = {
            "total": len(group),
            **{action: counts.get(action, 0) for action in REFRESH_ACTIONS},
            "needs_regeneration": regenerate > 0,
        }
        if regenerate:
            targets[category] = regenerate
            split_counts = Counter(
                str(item.get("split") or "unknown")
                for item in group
                if item["refresh_action"] == "regenerate"
            )
            targets_by_split[category] = dict(sorted(split_counts.items()))
    family_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        family_groups[str(item.get("template_family"))].append(item)
    families_regen = sorted(
        (
            {
                "template_family": family,
                "regenerate": sum(1 for i in group if i["refresh_action"] == "regenerate"),
                "total": len(group),
            }
            for family, group in family_groups.items()
            if any(i["refresh_action"] == "regenerate" for i in group)
        ),
        key=lambda row: (-row["regenerate"], row["template_family"]),
    )
    stale_atoms = Counter(
        atom
        for item in items
        if item["refresh_action"] in {"regenerate", "rename_rewrite"}
        for atom in item.get("touched_breaking_atoms", [])
    )
    carried = sum(actions.get(action, 0) for action in CARRIED_FORWARD_ACTIONS)
    excluded = actions.get("exclude", 0)
    regenerate_total = actions.get("regenerate", 0)
    return {
        "actions": {action: actions.get(action, 0) for action in REFRESH_ACTIONS},
        "carried_forward": carried,
        "carried_forward_fraction": _rate(carried, n - excluded),
        "regenerate_fraction": _rate(regenerate_total, n - excluded),
        "by_category": by_category,
        "categories_needing_regeneration": sorted(targets),
        "categories_reusable": sorted(c for c in by_category if c not in targets),
        "regeneration_targets": targets,
        "regeneration_targets_by_split": targets_by_split,
        "template_families_needing_regeneration": len(families_regen),
        "template_families_total": len(family_groups),
        "top_template_families_needing_regeneration": families_regen[:top_n],
        "stale_schema_atoms": dict(stale_atoms.most_common()),
        "generation_load_proxy": {
            "full_refresh_examples": n - excluded,
            "incremental_regeneration_examples": regenerate_total,
            "incremental_to_full_ratio": _rate(regenerate_total, n - excluded),
            "llm_free_carried_forward": actions.get("reuse", 0) + actions.get("refresh_answer", 0),
            "judge_rechecks_for_rewrites": actions.get("rename_rewrite", 0),
        },
    }


def static_impact_report(items: list[dict[str, Any]]) -> dict[str, Any]:
    """How well does schema-atom impact analysis predict execution outcomes?"""

    valid = [i for i in items if i["refresh_class"] != "original_execution_error"]
    confusion: dict[str, dict[str, int]] = {
        action: {name: 0 for name in REFRESH_CLASSES if name != "original_execution_error"}
        for action in STATIC_ACTIONS
    }
    for item in valid:
        confusion[str(item["static_action"])][str(item["refresh_class"])] += 1
    affected = [i for i in valid if i["refresh_class"] != "unchanged_answer"]
    flagged = [i for i in valid if i["static_action"] != "reuse"]
    hits = [i for i in affected if i["static_action"] != "reuse"]
    broken = [i for i in valid if i["refresh_class"] == "broken_schema"]
    broken_flagged = [i for i in broken if i["static_action"] in {"rewrite", "regenerate"}]
    missed = [i for i in affected if i["static_action"] == "reuse"]
    return {
        "confusion": confusion,
        "affected": len(affected),
        "flagged": len(flagged),
        "recall": _rate(len(hits), len(affected)) if affected else 1.0,
        "precision": _rate(len(hits), len(flagged)) if flagged else 1.0,
        "broken_schema_recall": _rate(len(broken_flagged), len(broken)) if broken else 1.0,
        "missed_by_static": len(missed),
        "missed_examples": [
            {"id": i["id"], "refresh_class": i["refresh_class"], "category": i.get("category")}
            for i in missed[:20]
        ],
        "reexecution_avoided": sum(1 for i in valid if i["static_action"] == "reuse"),
    }


def summarize_refresh_audit(
    items: list[dict[str, Any]],
    *,
    options: RefreshAuditOptions,
    diff: SchemaDiff | None = None,
    n_rows_total: int | None = None,
    provenance: Mapping[str, Any] | None = None,
    partial: bool = False,
) -> dict[str, Any]:
    broken = [i for i in items if i["refresh_class"] == "broken_schema"]
    silent = [i for i in items if i["refresh_class"] == "silently_changed_answer"]
    rewrites = [i.get("rename_rewrite") for i in items if i.get("rename_rewrite")]
    rewrite_skips = Counter(
        str(log.get("skipped_reason") or log.get("outcome")) for log in rewrites if log
    )
    summary: dict[str, Any] = {
        "migration_id": options.migration_id,
        "graph_profile": options.graph_profile,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "partial": bool(partial),
        "n_rows_total": n_rows_total,
        "n_audited": len(items),
        "overall": _class_block(items),
        "by_category": _grouped(items, "category"),
        "by_difficulty": _grouped(items, "difficulty"),
        "by_split": _grouped(items, "split"),
        "by_signature": _top_groups(items, "query_signature", options.top_n),
        "by_template_family": _top_groups(items, "template_family", options.top_n),
        "broken_schema_runtime_outcomes": dict(
            Counter(str(i["migrated_runtime_outcome"]) for i in broken)
        ),
        "new_schema_error_codes": dict(
            Counter(issue["code"] for i in items for issue in i.get("new_schema_errors", []))
        ),
        "new_schema_warning_codes": dict(
            Counter(issue["code"] for i in items for issue in i.get("new_schema_warnings", []))
        ),
        "affected_schema_atoms": dict(
            Counter(
                atom
                for i in items
                if i["refresh_class"] not in {"unchanged_answer", "original_execution_error"}
                for atom in [*i.get("touched_breaking_atoms", []), *i.get("touched_drift_atoms", [])]
            ).most_common()
        ),
        "nondeterminism": {
            "items_with_unordered_truncated_limit": sum(1 for i in items if i.get("nondeterminism_risk")),
            "silently_changed_with_unordered_truncated_limit": sum(
                1 for i in silent if i.get("nondeterminism_risk")
            ),
        },
        "rename_rewrite": {
            "enabled": options.rename_rewrite,
            "min_confidence": options.rename_min_confidence,
            "attempted": sum(1 for log in rewrites if log and log.get("attempted")),
            "applied": sum(1 for i in items if i["refresh_action"] == "rename_rewrite"),
            "answer_preserved": sum(
                1
                for i in items
                if i["refresh_action"] == "rename_rewrite" and i["rename_rewrite"].get("answer_preserved")
            ),
            "outcomes": dict(rewrite_skips),
        },
        "static_impact": static_impact_report(items),
        "incremental_plan": incremental_refresh_plan(items, top_n=options.top_n),
        "latency_ms": {
            "original_total": sum(
                float(i["original_execution"]["latency_ms"] or 0.0) for i in items
            ),
            "migrated_total": sum(
                float(i["migrated_execution"]["latency_ms"] or 0.0) for i in items
            ),
        },
    }
    if diff is not None:
        summary["schema_diff"] = diff.to_dict()
    if provenance:
        summary["provenance"] = dict(provenance)
    return summary


def assemble_refreshed_rows(
    carried_rows: list[dict[str, Any]],
    regenerated_rows: list[dict[str, Any]],
    targets_by_split: Mapping[str, Mapping[str, int]],
    *,
    split_order: tuple[str, ...] = ("test", "dev", "train"),
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Build refreshed splits: carried-forward rows keep their split, new rows fill deficits.

    Regenerated rows are assigned per category in id order to the splits that lost
    items (held-out splits first), so split sizes and category balance match the
    original package. Surplus regenerated rows are reported and left out; deficits
    that could not be filled are reported, never silently ignored.
    """

    splits: dict[str, list[dict[str, Any]]] = defaultdict(list)
    carried_ids: set[str] = set()
    for row in carried_rows:
        split = str((row.get("refresh") or {}).get("split") or row.get("split") or "unknown")
        splits[split].append(row)
        carried_ids.add(str(row.get("id")))
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    duplicates = 0
    for row in regenerated_rows:
        if str(row.get("id")) in carried_ids:
            duplicates += 1
            continue
        by_category[str(row.get("category"))].append(row)
    unfilled: dict[str, dict[str, int]] = {}
    surplus: dict[str, int] = {}
    for category in sorted(set(targets_by_split) | set(by_category)):
        pool = sorted(by_category.get(category, []), key=lambda r: str(r.get("id")))
        wanted = dict(targets_by_split.get(category, {}))
        ordered = [s for s in split_order if s in wanted] + sorted(s for s in wanted if s not in split_order)
        for split in ordered:
            need = int(wanted[split])
            take, pool = pool[:need], pool[need:]
            splits[split].extend(take)
            if len(take) < need:
                unfilled.setdefault(category, {})[split] = need - len(take)
        if pool:
            surplus[category] = len(pool)
    report = {
        "split_counts": {split: len(rows) for split, rows in sorted(splits.items())},
        "carried_forward": len(carried_rows),
        "regenerated_used": sum(len(rows) for rows in splits.values()) - len(carried_rows),
        "regenerated_duplicates_of_carried": duplicates,
        "unfilled_deficits": unfilled,
        "surplus_regenerated": surplus,
        "complete": not unfilled,
    }
    return dict(splits), report


def reusable_seen_records(carried_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows compatible with ``scripts/run_pipeline.py --seen-records``."""

    return [
        {
            "id": row.get("id"),
            "graph_profile": row.get("graph_profile"),
            "category": row.get("category"),
            "question": row.get("question"),
            "accepted": True,
        }
        for row in carried_rows
    ]


# ---------------------------------------------------------------------------
# Accuracy misestimate


def accuracy_misestimate(
    predictions: list[dict[str, Any]],
    stale_rows: list[dict[str, Any]],
    refreshed_rows: list[dict[str, Any]],
    *,
    migrated_clients: Mapping[str, ReadOnlyClient],
    audit_items: list[dict[str, Any]] | None = None,
    scorer: Callable[[list[dict[str, Any]], list[dict[str, Any]]], Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Score predictions on the migrated graph against stale vs refreshed references.

    *Stale* scoring executes the original (pre-migration) reference on the
    migrated graph, which is what an un-refreshed benchmark harness would do.
    *Refreshed* scoring executes the refreshed reference with the same id (reused,
    answer-refreshed, or rename-rewritten). Ids without a refreshed reference are
    *retired* and only contribute to stale accuracy. ``scorer`` defaults to the
    strict downstream scorer ``pipecypher.evaluation.answer_set_scores``.
    """

    if scorer is None:
        from .evaluation import answer_set_scores as scorer  # lazy: keep audit import light

    stale_by_id = {str(row.get("id")): row for row in stale_rows}
    refreshed_by_id = {str(row.get("id")): row for row in refreshed_rows}
    class_by_id = {str(item.get("id")): str(item.get("refresh_class")) for item in audit_items or []}
    gold_cache: dict[tuple[str, str], ExecutionResult] = {}

    def run_gold(graph: str, query: str) -> ExecutionResult:
        key = (graph, query)
        if key not in gold_cache:
            gold_cache[key] = safe_run(migrated_clients[graph], query)
        return gold_cache[key]

    def correct(pred: ExecutionResult | None, gold: ExecutionResult) -> bool:
        if pred is None or not pred.success or not gold.success:
            return False
        return bool(getattr(scorer(pred.rows, gold.rows), "exact", False))

    per_item: list[dict[str, Any]] = []
    unknown = unmigrated = 0
    for prediction in predictions:
        item_id = str(prediction.get("id"))
        stale = stale_by_id.get(item_id)
        if stale is None:
            unknown += 1
            continue
        graph = str(stale.get("graph_profile"))
        if graph not in migrated_clients:
            unmigrated += 1
            continue
        predicted = str(prediction.get("predicted_cypher") or prediction.get("cypher") or "")
        pred_exec = safe_run(migrated_clients[graph], clean_cypher(predicted)) if predicted.strip() else None
        stale_gold = run_gold(graph, reference_cypher(stale))
        refreshed = refreshed_by_id.get(item_id)
        refreshed_gold = run_gold(graph, reference_cypher(refreshed)) if refreshed else None
        per_item.append(
            {
                "id": item_id,
                "graph_profile": graph,
                "category": stale.get("category"),
                "refresh_class": class_by_id.get(item_id),
                "refresh_action": (refreshed or {}).get("refresh", {}).get("action") if refreshed else "retired",
                "prediction_executed": bool(pred_exec and pred_exec.success),
                "prediction_empty": bool(pred_exec and pred_exec.success and not pred_exec.rows),
                "stale_gold_success": stale_gold.success,
                "stale_gold_empty": stale_gold.success and not stale_gold.rows,
                "stale_correct": correct(pred_exec, stale_gold),
                "has_refreshed_reference": refreshed is not None,
                "refreshed_correct": correct(pred_exec, refreshed_gold) if refreshed_gold else None,
            }
        )

    summary = _misestimate_block(per_item)
    summary.update(
        {
            "n_predictions": len(predictions),
            "n_unknown_id": unknown,
            "n_unmigrated_graph": unmigrated,
            "scorer": getattr(scorer, "__name__", str(scorer)),
            "by_category": _misestimate_grouped(per_item, "category"),
        }
    )
    if audit_items:
        summary["by_refresh_class"] = _misestimate_grouped(per_item, "refresh_class")
    return summary, per_item


def _misestimate_block(rows: list[dict[str, Any]]) -> dict[str, Any]:
    paired = [r for r in rows if r["has_refreshed_reference"]]
    retired = [r for r in rows if not r["has_refreshed_reference"]]
    stale_acc = _rate(sum(r["stale_correct"] for r in rows), len(rows))
    refreshed_acc = _rate(sum(bool(r["refreshed_correct"]) for r in paired), len(paired))
    paired_stale = _rate(sum(r["stale_correct"] for r in paired), len(paired))
    return {
        "n_scored": len(rows),
        "stale_accuracy": stale_acc,
        "refreshed_accuracy": refreshed_acc,
        "n_with_refreshed_reference": len(paired),
        "n_retired": len(retired),
        "retired_stale_accuracy": _rate(sum(r["stale_correct"] for r in retired), len(retired)),
        "stale_correct_on_empty_gold": sum(1 for r in rows if r["stale_correct"] and r["stale_gold_empty"]),
        "paired": {
            "n": len(paired),
            "stale_accuracy": paired_stale,
            "refreshed_accuracy": refreshed_acc,
            "misestimate_pp": 100.0 * (paired_stale - refreshed_acc),
            "stale_only_correct": sum(1 for r in paired if r["stale_correct"] and not r["refreshed_correct"]),
            "refreshed_only_correct": sum(
                1 for r in paired if r["refreshed_correct"] and not r["stale_correct"]
            ),
            "both_correct": sum(1 for r in paired if r["stale_correct"] and r["refreshed_correct"]),
            "both_wrong": sum(1 for r in paired if not r["stale_correct"] and not r["refreshed_correct"]),
        },
        "headline_misestimate_pp": 100.0 * (stale_acc - refreshed_acc),
    }


def _misestimate_grouped(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get(key))].append(row)
    return {name: _misestimate_block(group) for name, group in sorted(groups.items())}


# ---------------------------------------------------------------------------
# Paper table


def refresh_table_rows(
    summaries: list[Mapping[str, Any]],
    *,
    timings: Mapping[str, Mapping[str, Any]] | None = None,
    allow_partial: bool = False,
) -> list[dict[str, Any]]:
    """One compact row per migration: % broken / silently changed / unchanged + refresh cost."""

    rows: list[dict[str, Any]] = []
    for summary in summaries:
        if summary.get("partial") and not allow_partial:
            raise ValueError(
                f"refusing partial audit summary for {summary.get('migration_id')}; "
                "rerun the full audit (no --limit) before tabulating"
            )
        overall = summary["overall"]
        rates = overall["rates"]
        plan = summary["incremental_plan"]
        timing = dict((timings or {}).get(str(summary["migration_id"]), {}))
        rows.append(
            {
                "migration_id": summary["migration_id"],
                "graph_profile": summary["graph_profile"],
                "n_items": overall["n_valid_original"],
                "pct_broken_schema": 100.0 * rates["broken_schema"],
                "pct_execution_error": 100.0 * rates["execution_error"],
                "pct_now_empty": 100.0 * rates["now_empty"],
                "pct_silently_changed": 100.0 * rates["silently_changed_answer"],
                "pct_unchanged": 100.0 * rates["unchanged_answer"],
                "pct_carried_forward": 100.0 * plan["carried_forward_fraction"],
                "pct_regenerate": 100.0 * plan["regenerate_fraction"],
                "static_recall": summary["static_impact"]["recall"],
                "full_refresh_gpu_hours": timing.get("full_refresh_gpu_hours"),
                "incremental_refresh_gpu_hours": timing.get("incremental_refresh_gpu_hours"),
                "audit_wall_minutes": timing.get("audit_wall_minutes"),
            }
        )
    return rows


def render_refresh_table_markdown(rows: list[Mapping[str, Any]]) -> str:
    header = (
        "| Migration | Graph | N | Broken schema % | Exec error % | Now empty % | "
        "Silently changed % | Unchanged % | Carried forward % | Static recall | "
        "Full refresh GPU-h | Incremental GPU-h |"
    )
    lines = [header, "|" + "---|" * 12]

    def fmt(value: Any, digits: int = 1) -> str:
        if value is None:
            return "n/a"
        if isinstance(value, float):
            return f"{value:.{digits}f}"
        return str(value)

    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["migration_id"]),
                    str(row["graph_profile"]),
                    str(row["n_items"]),
                    fmt(row["pct_broken_schema"]),
                    fmt(row["pct_execution_error"]),
                    fmt(row["pct_now_empty"]),
                    fmt(row["pct_silently_changed"]),
                    fmt(row["pct_unchanged"]),
                    fmt(row["pct_carried_forward"]),
                    fmt(row["static_recall"], 3),
                    fmt(row["full_refresh_gpu_hours"], 2),
                    fmt(row["incremental_refresh_gpu_hours"], 2),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"
