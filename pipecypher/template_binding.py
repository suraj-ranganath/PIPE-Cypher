"""Outcome-aware slot binding from a template's own parameterized Cypher.

v2 bound LLM-template slots with an LLM-written reverse query or, failing that,
a generic ``MATCH (x:Label) WHERE x.prop IS NOT NULL`` lookup. Neither knew the
template's relationship pattern, so about a quarter of candidates returned no
rows. v3 templates carry a parameterized Cypher query (``$slot`` parameters).
This module turns that query into candidate binding queries and verifies each
binding by executing the parameterized query itself:

1. ``derived_return``: the full query with every ``var.prop = $slot`` predicate
   replaced by ``true`` (and inline ``{prop: $slot}`` map entries removed), and
   the final RETURN clause replaced by a projection of the slot properties. It
   keeps every other predicate, so candidates satisfy the template's pattern
   and fixed filters.
2. ``derived_prefix``: the same rewrite truncated at the first top-level WITH or
   RETURN, for queries whose slot variables are out of scope at the end.

Rewrites operate on masked text (string literals blanked with offsets kept),
skip UNION/CALL, and fail closed (``None`` plus a reason) whenever a slot
parameter appears outside a simple equality. Verification is the arbiter: a
binding is accepted only when the parameterized query returns at least one
non-degenerate row for it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from .models import ExecutionResult
from .refresh_audit import mask_string_literals

_PARAM_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")
_UNSUPPORTED_RE = re.compile(r"(?i)\bUNION\b|\bCALL\s*\{")
_CLAUSE_RE = re.compile(r"(?i)\b(WITH|RETURN)\b")


def _top_level_clauses(masked: str) -> list[re.Match[str]]:
    """WITH/RETURN keywords outside brackets, excluding ``STARTS WITH`` / ``ENDS WITH``."""

    depth_at: list[int] = []
    depth = 0
    for char in masked:
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        depth_at.append(depth)
    matches = []
    for match in _CLAUSE_RE.finditer(masked):
        if depth_at[match.start()] != 0:
            continue
        before = masked[: match.start()].rstrip().split()
        if match.group(1).upper() == "WITH" and before and before[-1].upper() in {"STARTS", "ENDS"}:
            continue
        matches.append(match)
    return matches


@dataclass(frozen=True)
class SlotRef:
    slot: str
    variable: str
    prop: str


@dataclass(frozen=True)
class BindingQuery:
    strategy: str
    cypher: str


def parameter_names(cypher: str) -> set[str]:
    """Parameter names used outside string literals."""

    return set(_PARAM_RE.findall(mask_string_literals(cypher)))


def check_template_cypher(cypher: str, slots: list[str] | set[str]) -> str | None:
    """Return a problem description, or None when every slot is a parameter and vice versa."""

    if not cypher or not cypher.strip():
        return "template has no parameterized Cypher"
    params = parameter_names(cypher)
    missing = sorted(set(slots) - params)
    extra = sorted(params - set(slots))
    if missing:
        return f"template Cypher does not use slot parameter(s): {', '.join('$' + s for s in missing)}"
    if extra:
        return f"template Cypher uses unknown parameter(s): {', '.join('$' + s for s in extra)}"
    return None


def _equality_patterns(slot: str) -> list[re.Pattern[str]]:
    name = re.escape(slot)
    return [
        re.compile(r"(?P<var>[A-Za-z_][A-Za-z0-9_]*)\s*\.\s*(?P<prop>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*\$" + name + r"\b"),
        re.compile(r"\$" + name + r"\s*=\s*(?P<var>[A-Za-z_][A-Za-z0-9_]*)\s*\.\s*(?P<prop>[A-Za-z_][A-Za-z0-9_]*)\b"),
    ]


def _inline_pattern(slot: str) -> re.Pattern[str]:
    # One map entry `prop: $slot`, with an optional leading or trailing comma.
    return re.compile(r"(?P<prop>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*\$" + re.escape(slot) + r"\b")


def _enclosing_node_variable(masked: str, position: int) -> str | None:
    open_paren = masked.rfind("(", 0, position)
    open_brace = masked.rfind("{", 0, position)
    if open_paren < 0 or open_brace < open_paren:
        return None
    match = re.match(r"\(\s*([A-Za-z_][A-Za-z0-9_]*)", masked[open_paren:])
    return match.group(1) if match else None


def _remove_inline_entry(text: str, start: int, end: int) -> tuple[str, int]:
    """Remove a ``prop: $slot`` map entry and one adjacent comma; returns (text, removed_chars_before_end)."""

    left = start
    right = end
    # Prefer removing a trailing comma; otherwise a leading one.
    trailing = re.match(r"\s*,\s*", text[right:])
    if trailing:
        right += trailing.end()
    else:
        leading = re.search(r",\s*$", text[:left])
        if leading:
            left = leading.start()
    text = text[:left] + text[right:]
    # Drop maps left empty: `{ }` -> ``.
    text = re.sub(r"\{\s*\}", "", text)
    return text, right - left


def slot_references(cypher: str, slots: list[str]) -> tuple[list[SlotRef], str | None, str]:
    """Rewrite slot predicates away; return (slot refs, problem, rewritten cypher)."""

    text = cypher
    refs: list[SlotRef] = []
    for slot in slots:
        masked = mask_string_literals(text)
        found = False
        for pattern in _equality_patterns(slot):
            match = pattern.search(masked)
            if match:
                refs.append(SlotRef(slot, match.group("var"), match.group("prop")))
                text = text[: match.start()] + "true" + text[match.end():]
                found = True
                break
        if not found:
            masked = mask_string_literals(text)
            match = _inline_pattern(slot).search(masked)
            if match:
                variable = _enclosing_node_variable(masked, match.start())
                if not variable:
                    return [], f"inline ${slot} has no node variable", cypher
                refs.append(SlotRef(slot, variable, match.group("prop")))
                text, _ = _remove_inline_entry(text, match.start(), match.end())
                found = True
        if not found:
            return [], f"${slot} is not used in a simple equality", cypher
        if f"${slot}" in mask_string_literals(text):
            return [], f"${slot} is used more than once", cypher
    return refs, None, text


def derive_binding_queries(cypher: str, slots: list[str], *, limit: int) -> tuple[list[BindingQuery], str | None]:
    """Candidate binding queries for a template's parameterized Cypher, most specific first."""

    if not slots:
        return [], "template has no slots"
    problem = check_template_cypher(cypher, slots)
    if problem:
        return [], problem
    masked = mask_string_literals(cypher)
    if _UNSUPPORTED_RE.search(masked):
        return [], "UNION/CALL subqueries are not rewritten"
    refs, problem, rewritten = slot_references(cypher, slots)
    if problem:
        return [], problem
    projection = ", ".join(f"{ref.variable}.{ref.prop} AS {ref.slot}" for ref in refs)
    tail = f" RETURN DISTINCT {projection} LIMIT {int(limit)}"
    queries: list[BindingQuery] = []
    clauses = _top_level_clauses(mask_string_literals(rewritten))
    returns = [match for match in clauses if match.group(1).upper() == "RETURN"]
    if returns:
        last = returns[-1]
        queries.append(BindingQuery("derived_return", rewritten[: last.start()].rstrip() + tail))
    if clauses:
        head = rewritten[: clauses[0].start()].rstrip()
        prefix = head + tail
        if re.search(r"(?i)\bMATCH\b", head) and (not queries or prefix != queries[0].cypher):
            queries.append(BindingQuery("derived_prefix", prefix))
    if not queries:
        return [], "no RETURN clause"
    return queries, None


def is_degenerate(execution: ExecutionResult) -> bool:
    """No rows, or every value null / numeric zero (e.g., ``count(...) = 0``)."""

    if not execution.success or not execution.rows:
        return True
    for row in execution.rows:
        for value in row.values():
            if value is None:
                continue
            if isinstance(value, bool):
                return False
            if isinstance(value, int | float) and value == 0:
                continue
            if isinstance(value, list | str) and len(value) == 0:
                continue
            return False
    return True


def verify_binding(
    cypher: str,
    binding: dict[str, Any],
    run: Callable[[str, dict[str, Any]], ExecutionResult],
) -> tuple[bool, ExecutionResult]:
    execution = run(cypher, binding)
    return (not is_degenerate(execution)), execution


def cypher_literal(value: Any) -> str | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
    return None


def render_with_literals(cypher: str, binding: dict[str, Any]) -> str | None:
    """Substitute ``$slot`` parameters (outside string literals) with Cypher literals."""

    masked = mask_string_literals(cypher)
    pieces: list[str] = []
    last = 0
    for match in _PARAM_RE.finditer(masked):
        name = match.group(1)
        if name not in binding:
            return None
        literal = cypher_literal(binding[name])
        if literal is None:
            return None
        pieces.append(cypher[last: match.start()])
        pieces.append(literal)
        last = match.end()
    pieces.append(cypher[last:])
    return "".join(pieces)
