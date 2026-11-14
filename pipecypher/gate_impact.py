from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


ISSUE_TO_GATE = {
    "not_read_only": "read_only",
    "syntax_shape": "syntax",
    "unbalanced_parentheses": "syntax",
    "unbalanced_brackets": "syntax",
    "reserved_variable": "syntax",
    "antlr_parse": "syntax",
    "unknown_label": "schema",
    "unknown_property": "schema",
    "unknown_relationship": "schema",
    "unknown_relationship_property": "schema",
    "invalid_categorical_value": "value",
    "missing_relationship_type": "schema",
    "unseen_relationship_pattern": "direction",
    "wrong_direction": "direction",
    "undirected_relationship": "direction",
    "bidirectional_relationship": "direction",
}


def summarize_gate_impact(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize which quality gates prevent candidates from entering a benchmark."""

    blocked_by_gate: Counter[str] = Counter()
    issue_counts: Counter[str] = Counter()
    by_graph_category: dict[str, Counter[str]] = defaultdict(Counter)
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    accepted = 0

    for record in records:
        gate = first_blocking_gate(record)
        accepted += int(gate == "accepted")
        blocked_by_gate[gate] += 1
        key = f"{record.get('graph_profile', 'unknown')}::{record.get('category', 'unknown')}"
        by_graph_category[key][gate] += 1
        for issue in _issue_codes(record):
            issue_counts[issue] += 1
        if gate != "accepted" and len(examples[gate]) < 4:
            examples[gate].append(_example(record, gate))

    return {
        "records": len(records),
        "accepted": accepted,
        "blocked": len(records) - accepted,
        "blocked_by_gate": dict(sorted(blocked_by_gate.items())),
        "issue_counts": dict(sorted(issue_counts.items())),
        "by_graph_category": {
            key: dict(sorted(counter.items())) for key, counter in sorted(by_graph_category.items())
        },
        "examples": dict(sorted(examples.items())),
    }


def first_blocking_gate(record: dict[str, Any]) -> str:
    validation = record.get("validation", {}) if isinstance(record.get("validation"), dict) else {}
    execution = record.get("execution", {}) if isinstance(record.get("execution"), dict) else {}
    judge = record.get("judge", {}) if isinstance(record.get("judge"), dict) else {}

    issue_gates = [ISSUE_TO_GATE.get(issue, "validation") for issue in _issue_codes(record)]
    for gate in ("read_only", "syntax", "schema", "direction", "value", "validation"):
        if gate in issue_gates:
            return gate
    if validation.get("read_only") is False:
        return "read_only"
    if validation.get("syntax_valid") is False:
        return "syntax"
    if validation.get("schema_valid") is False:
        return "schema"
    if execution.get("success") is False:
        return "execution"
    if execution.get("success") is True and not execution.get("rows"):
        return "empty_result"
    if judge.get("passed") is False:
        reason = str(judge.get("failure_reason", "")).casefold()
        if "duplicate" in reason or "diversity" in reason:
            return "duplicate_or_diversity"
        return "judge"
    if record.get("accepted"):
        return "accepted"
    return "other_reject"


def _issue_codes(record: dict[str, Any]) -> list[str]:
    validation = record.get("validation", {}) if isinstance(record.get("validation"), dict) else {}
    codes: list[str] = []
    for issue in validation.get("issues", []) or []:
        if not isinstance(issue, dict) or not issue.get("code"):
            continue
        if str(issue.get("level", "error")).casefold() == "warning":
            continue
        if issue.get("code"):
            codes.append(str(issue["code"]))
    return codes


def _example(record: dict[str, Any], gate: str) -> dict[str, Any]:
    return {
        "gate": gate,
        "graph_profile": record.get("graph_profile", ""),
        "category": record.get("category", ""),
        "question": record.get("question", ""),
        "cypher": record.get("cypher", ""),
        "issues": _issue_codes(record),
        "judge_failure_reason": (record.get("judge") or {}).get("failure_reason", ""),
    }
