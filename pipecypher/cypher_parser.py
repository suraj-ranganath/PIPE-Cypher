from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_BALKANID_ROOT = (
    "/Users/suraj/Documents/Archive/BalkanID/Dev/copilot-api"
)

RISKY_REWRITE_FEATURES = (
    "CASE",
    "UNION",
    "CALL",
    "WHERE EXISTS",
    "WHERE NOT EXISTS",
    "UNWIND",
)


@dataclass(frozen=True)
class ProjectionItem:
    expression: str
    alias: str | None = None


@dataclass(frozen=True)
class RelationshipObservation:
    start_label: str | None
    rel_type: str | None
    end_label: str | None
    direction: str

    def to_dict(self) -> dict[str, str | None]:
        return {
            "start_label": self.start_label,
            "relationship_type": self.rel_type,
            "end_label": self.end_label,
            "direction": self.direction,
        }


@dataclass(frozen=True)
class CypherAnalysis:
    cleaned_cypher: str
    projection_items: tuple[ProjectionItem, ...] = ()
    variable_labels: dict[str, str] = field(default_factory=dict)
    relationships: tuple[RelationshipObservation, ...] = ()
    risky_features: tuple[str, ...] = ()
    rewrite_skip_reasons: tuple[str, ...] = ()
    where_count: int = 0
    has_return: bool = False
    has_return_distinct: bool = False

    @property
    def rewrite_safe(self) -> bool:
        return not self.rewrite_skip_reasons

    def to_feature_dict(self) -> dict[str, Any]:
        return {
            "return_items": [item.expression for item in self.projection_items],
            "return_aliases": [item.alias for item in self.projection_items if item.alias],
            "variable_labels": dict(self.variable_labels),
            "relationship_observations": [rel.to_dict() for rel in self.relationships],
            "risky_features": list(self.risky_features),
            "rewrite_safe": self.rewrite_safe,
            "rewrite_skip_reasons": list(self.rewrite_skip_reasons),
            "where_clause_count": self.where_count,
            "has_return_distinct": self.has_return_distinct,
        }


def _split_projection_items(projection: str) -> list[str]:
    items: list[str] = []
    current: list[str] = []
    depth = 0
    quote: str | None = None
    escape = False
    for char in projection:
        if quote:
            current.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
            current.append(char)
            continue
        if char in "([{":
            depth += 1
        elif char in ")]}" and depth > 0:
            depth -= 1
        if char == "," and depth == 0:
            item = "".join(current).strip()
            if item:
                items.append(item)
            current = []
        else:
            current.append(char)
    item = "".join(current).strip()
    if item:
        items.append(item)
    return items


def _return_projection(query: str) -> str:
    match = re.search(
        r"(?i)\bRETURN\s+(?:DISTINCT\s+)?(.+?)(?:\bORDER\s+BY\b|\bSKIP\b|\bLIMIT\b|$)",
        query,
    )
    return match.group(1).strip() if match else ""


def _projection_items(query: str) -> tuple[ProjectionItem, ...]:
    projection = _return_projection(query)
    items: list[ProjectionItem] = []
    for item in _split_projection_items(projection):
        alias_match = re.match(r"(?is)^(.+?)\s+AS\s+([A-Za-z_][A-Za-z0-9_]*)$", item)
        if alias_match:
            items.append(ProjectionItem(alias_match.group(1).strip(), alias_match.group(2)))
        else:
            items.append(ProjectionItem(item))
    return tuple(items)


def _variable_labels(query: str) -> dict[str, str]:
    pattern = re.compile(
        r"\(\s*(?P<var>[A-Za-z_][A-Za-z0-9_]*)?\s*"
        r"(?::(?P<label>[A-Za-z_][A-Za-z0-9_]*))?(?:\s*\{[^}]*\})?\s*\)"
    )
    mapping: dict[str, str] = {}
    for match in pattern.finditer(query):
        var = match.group("var")
        label = match.group("label")
        if var and label:
            mapping[var] = label
    return mapping


def _relationship_observations(query: str) -> tuple[RelationshipObservation, ...]:
    pattern = re.compile(
        r"\(\s*(?:[A-Za-z_][A-Za-z0-9_]*\s*)?"
        r"(?::(?P<left_label>[A-Za-z_][A-Za-z0-9_]*))?[^)]*\)"
        r"\s*(?P<left_arrow><)?-\[\s*(?:[A-Za-z_][A-Za-z0-9_]*\s*)?"
        r"(?::(?P<rel>[A-Za-z_][A-Za-z0-9_]*))?[^]]*\]-(?P<right_arrow>>)?\s*"
        r"\(\s*(?:[A-Za-z_][A-Za-z0-9_]*\s*)?"
        r"(?::(?P<right_label>[A-Za-z_][A-Za-z0-9_]*))?[^)]*\)"
    )
    observations: list[RelationshipObservation] = []
    for match in pattern.finditer(query):
        left_label = match.group("left_label")
        right_label = match.group("right_label")
        rel_type = match.group("rel")
        left_arrow = bool(match.group("left_arrow"))
        right_arrow = bool(match.group("right_arrow"))
        if left_arrow and right_arrow:
            observations.append(
                RelationshipObservation(left_label, rel_type, right_label, "bidirectional")
            )
        elif left_arrow:
            observations.append(
                RelationshipObservation(right_label, rel_type, left_label, "incoming")
            )
        elif right_arrow:
            observations.append(
                RelationshipObservation(left_label, rel_type, right_label, "outgoing")
            )
        else:
            observations.append(
                RelationshipObservation(left_label, rel_type, right_label, "undirected")
            )
    return tuple(observations)


def _risky_features(query: str) -> tuple[str, ...]:
    upper = query.upper()
    found: list[str] = []
    for feature in RISKY_REWRITE_FEATURES:
        if " " in feature:
            if re.search(r"\b" + r"\s+".join(map(re.escape, feature.split())) + r"\b", upper):
                found.append(feature)
        elif re.search(rf"\b{re.escape(feature)}\b", upper):
            found.append(feature)
    return tuple(found)


def _reserved_variable_skip_reasons(query: str) -> list[str]:
    reserved = {"index", "constraint", "create", "drop", "exists", "remove"}
    reasons: list[str] = []
    for var, _label in _variable_labels(query).items():
        if var.lower() in reserved:
            reasons.append(f"reserved variable `{var}`")
    rel_var_pattern = re.compile(
        r"-\[\s*(?P<var>[A-Za-z_][A-Za-z0-9_]*)\s*(?::[A-Za-z_][A-Za-z0-9_]*)?"
    )
    for match in rel_var_pattern.finditer(query):
        var = match.group("var")
        if var.lower() in reserved:
            reasons.append(f"reserved relationship variable `{var}`")
    return reasons


def analyze_cypher(query: str) -> CypherAnalysis:
    """Extract a conservative, JSON-friendly Cypher structure summary.

    This is intentionally dependency-free. When the optional BalkanID ANTLR grammar is
    available, `OptionalCypherParser` still provides parse errors; this analyzer provides
    stable offline structure and rewrite-safety metadata for tests, logs, and paper tables.
    """

    cleaned = re.sub(r"\s+", " ", query).strip()
    where_count = len(re.findall(r"(?i)\bWHERE\b", cleaned))
    risky_features = _risky_features(cleaned)
    skip_reasons = [f"risky construct `{feature}`" for feature in risky_features]
    if where_count > 1:
        skip_reasons.append("multiple WHERE clauses")
    skip_reasons.extend(_reserved_variable_skip_reasons(cleaned))
    return CypherAnalysis(
        cleaned_cypher=cleaned,
        projection_items=_projection_items(cleaned),
        variable_labels=_variable_labels(cleaned),
        relationships=_relationship_observations(cleaned),
        risky_features=risky_features,
        rewrite_skip_reasons=tuple(dict.fromkeys(skip_reasons)),
        where_count=where_count,
        has_return=bool(re.search(r"(?i)\bRETURN\b", cleaned)),
        has_return_distinct=bool(re.search(r"(?i)\bRETURN\s+DISTINCT\b", cleaned)),
    )


class OptionalCypherParser:
    """Optional adapter around the BalkanID ANTLR Cypher grammar.

    The parser is treated as an enhancement, not a hard dependency, so deterministic tests
    and docs can run without antlr4 or the archived BalkanID project on the import path.
    """

    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root or os.environ.get("PIPE_CYPHER_BALKANID_ROOT", DEFAULT_BALKANID_ROOT))
        self.available = False
        self._lexer = None
        self._parser = None
        self._input_stream = None
        self._token_stream = None
        self._load_error: str | None = None
        self._load()

    @property
    def load_error(self) -> str | None:
        return self._load_error

    def _load(self) -> None:
        if not self.root.exists():
            self._load_error = f"BalkanID root not found: {self.root}"
            return
        if str(self.root) not in sys.path:
            sys.path.append(str(self.root))
        try:
            from antlr4 import CommonTokenStream, InputStream
            from modules.llm_manager.cypher_parser.CypherLexer import CypherLexer
            from modules.llm_manager.cypher_parser.CypherParser import CypherParser

            self._input_stream = InputStream
            self._token_stream = CommonTokenStream
            self._lexer = CypherLexer
            self._parser = CypherParser
            self.available = True
        except Exception as exc:  # pragma: no cover - depends on local archive deps
            self._load_error = str(exc)

    def parse_error(self, query: str) -> str | None:
        if not self.available:
            return None
        try:
            stream = self._input_stream(query)
            lexer = self._lexer(stream)
            tokens = self._token_stream(lexer)
            parser = self._parser(tokens)
            parser.oC_Cypher()
            if parser.getNumberOfSyntaxErrors() > 0:
                return f"ANTLR parser reported {parser.getNumberOfSyntaxErrors()} syntax error(s)"
            return None
        except Exception as exc:  # pragma: no cover - depends on parser runtime
            return str(exc)
