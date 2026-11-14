"""Deterministic check for ties at an ``ORDER BY ... LIMIT n`` boundary.

A reference such as ``... ORDER BY cnt DESC LIMIT 1`` has an arbitrary answer
when two candidates share the top ``cnt``: Neo4j returns one of them, and an
exact-set scorer then rewards whichever tie-break the reference happened to get.
LLM judges flagged this as the most frequent problem in accepted v2 items.

The check re-runs the query with ``LIMIT n+1`` and compares the order keys of
the n-th and (n+1)-th best rows. It is conservative: it only rewrites the
single ``LIMIT`` literal that follows the only ``ORDER BY`` in the query
(string literals are masked, never edited), and it reports ``unsupported`` or
``unresolved`` instead of guessing when the query shape or the order keys
cannot be checked from the projected columns.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from .cypher_parser import _split_projection_items, analyze_cypher
from .models import ExecutionResult
from .refresh_audit import mask_string_literals

TIE = "tie"
NO_TIE = "no_tie"
NOT_APPLICABLE = "not_applicable"
UNSUPPORTED = "unsupported"
UNRESOLVED = "unresolved"
ERROR = "error"

_ORDER_LIMIT = re.compile(
    r"(?is)\bORDER\s+BY\s+(?P<keys>.+?)\s+LIMIT\s+(?P<n>\d+)\b"
)
_DIRECTION = re.compile(r"(?is)^(?P<expr>.+?)\s+(?P<dir>ASC|ASCENDING|DESC|DESCENDING)$")
_UNSUPPORTED_FEATURES = re.compile(r"(?i)\b(UNION|CALL|SKIP)\b")
_CONTINUATION = re.compile(r"(?i)\b(MATCH|WITH|UNWIND|CALL|ORDER\s+BY|LIMIT)\b")


@dataclass(frozen=True)
class TieCheck:
    status: str
    detail: str = ""
    limit: int | None = None
    order_columns: tuple[str, ...] = ()
    order_descending: tuple[bool, ...] = ()
    boundary_keys: tuple[Any, ...] = field(default=())

    @property
    def has_tie(self) -> bool:
        return self.status == TIE

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "detail": self.detail,
            "limit": self.limit,
            "order_columns": list(self.order_columns),
            "order_descending": list(self.order_descending),
        }


def _norm(expr: str) -> str:
    return re.sub(r"\s+", "", expr).lower()


def plan_tie_check(cypher: str) -> tuple[str | None, TieCheck]:
    """Return ``(rewritten_query, plan)``; the query is None when no run is needed."""

    masked = mask_string_literals(cypher)
    matches = list(_ORDER_LIMIT.finditer(masked))
    if not matches:
        if re.search(r"(?i)\bORDER\s+BY\b", masked) and re.search(r"(?i)\bLIMIT\b", masked):
            return None, TieCheck(UNSUPPORTED, "LIMIT is not an integer literal after ORDER BY")
        return None, TieCheck(NOT_APPLICABLE, "no ORDER BY ... LIMIT")
    if len(matches) > 1 or len(re.findall(r"(?i)\bORDER\s+BY\b", masked)) > 1:
        return None, TieCheck(UNSUPPORTED, "multiple ORDER BY clauses")
    if _UNSUPPORTED_FEATURES.search(masked):
        return None, TieCheck(UNSUPPORTED, "UNION/CALL/SKIP present")
    match = matches[0]
    if re.search(r"(?i)\b(RETURN|WITH|MATCH|WHERE|UNWIND)\b", match.group("keys")):
        return None, TieCheck(UNSUPPORTED, "LIMIT does not directly follow the ORDER BY")
    limit = int(match.group("n"))
    remainder = masked[match.end():].strip().rstrip(";").strip()
    if remainder:
        # ORDER BY ... LIMIT inside a WITH: only a final RETURN may follow, so
        # each limited row maps to one output row.
        if not re.match(r"(?i)^RETURN\b", remainder) or _CONTINUATION.search(remainder):
            return None, TieCheck(UNSUPPORTED, "rows are expanded after the limited WITH", limit)

    projection = analyze_cypher(cypher).projection_items
    columns: list[str] = []
    descending: list[bool] = []
    key_text = cypher[match.start("keys"):match.end("keys")]
    for raw in _split_projection_items(key_text):
        direction = _DIRECTION.match(raw.strip())
        expr = direction.group("expr").strip() if direction else raw.strip()
        desc = bool(direction and direction.group("dir").upper().startswith("DESC"))
        column = None
        for item in projection:
            if item.alias and _norm(item.alias) == _norm(expr):
                column = item.alias
                break
            if _norm(item.expression) == _norm(expr):
                column = item.alias or item.expression
                break
        if column is None:
            return None, TieCheck(UNRESOLVED, f"order key `{expr}` is not a returned column", limit)
        columns.append(column)
        descending.append(desc)

    start, end = match.span("n")
    rewritten = cypher[:start] + str(limit + 1) + cypher[end:]
    return rewritten, TieCheck(
        NO_TIE, "", limit, tuple(columns), tuple(descending)
    )


def _compare(a: Any, b: Any) -> int:
    # Neo4j orders null last in ascending order; mixed types fall back to text.
    if a is None or b is None:
        return (a is None) - (b is None)
    try:
        return (a > b) - (a < b)
    except TypeError:
        return (str(a) > str(b)) - (str(a) < str(b))


def tie_from_rows(plan: TieCheck, rows: list[dict[str, Any]]) -> TieCheck:
    limit = plan.limit or 0
    if len(rows) <= limit:
        return TieCheck(NO_TIE, "all candidates fit under LIMIT", limit, plan.order_columns, plan.order_descending)
    try:
        keys = [tuple(row[column] for column in plan.order_columns) for row in rows]
    except KeyError as exc:
        return TieCheck(UNRESOLVED, f"column {exc} missing from result", limit, plan.order_columns, plan.order_descending)

    def cmp(left: tuple[Any, ...], right: tuple[Any, ...]) -> int:
        for value_l, value_r, desc in zip(left, right, plan.order_descending):
            outcome = _compare(value_l, value_r)
            if outcome:
                return -outcome if desc else outcome
        return 0

    ordered = sorted(keys, key=functools.cmp_to_key(cmp))
    boundary = ordered[limit - 1] if limit >= 1 else None
    if limit >= 1 and cmp(ordered[limit - 1], ordered[limit]) == 0:
        return TieCheck(
            TIE,
            f"rank {limit} and rank {limit + 1} share the order key",
            limit,
            plan.order_columns,
            plan.order_descending,
            tuple(boundary or ()),
        )
    return TieCheck(NO_TIE, "", limit, plan.order_columns, plan.order_descending)


def check_limit_tie(cypher: str, run: Callable[[str], ExecutionResult]) -> TieCheck:
    """Check one read-only query; ``run`` executes Cypher and returns all rows."""

    rewritten, plan = plan_tie_check(cypher)
    if rewritten is None:
        return plan
    result = run(rewritten)
    if not result.success:
        return TieCheck(ERROR, result.error or "execution failed", plan.limit, plan.order_columns, plan.order_descending)
    return tie_from_rows(plan, result.rows)
