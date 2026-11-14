from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

from .privacy import PrivacyPolicy, redact_example


_CYPHER_STRING_RE = re.compile(r"'(?:''|\\'|[^'])*'")
_PLACEHOLDER_RE = re.compile(r"__[A-Z][A-Z0-9_]*_[A-Za-z0-9]+__")


@dataclass(frozen=True)
class RedactionAuditConfig:
    min_sensitive_chars: int = 3
    include_numeric_literals: bool = False


def audit_redaction(
    examples: list[dict[str, Any]],
    *,
    policy: PrivacyPolicy | None = None,
    config: RedactionAuditConfig | None = None,
) -> dict[str, Any]:
    """Audit whether a redacted export retains raw value-bearing strings.

    The audit is intentionally exact-match and conservative: it uses values that
    PIPE-Cypher explicitly knows it may leak, namely entity bindings, quoted
    Cypher literals, and string-valued execution samples. It does not claim to
    detect semantic paraphrases or infer all personally identifying strings.
    """

    active_policy = policy or PrivacyPolicy(hash_placeholders=True)
    active_config = config or RedactionAuditConfig()
    totals = Counter()
    residual_by_field: Counter[str] = Counter()
    placeholder_counts: Counter[str] = Counter()
    examples_with_residuals: list[dict[str, Any]] = []

    for example in examples:
        sensitive = sensitive_values_for_example(
            example,
            min_chars=active_config.min_sensitive_chars,
            include_numeric_literals=active_config.include_numeric_literals,
        )
        redacted = redact_example(example, policy=active_policy)
        field_text = _redacted_field_text(redacted)
        residuals: list[dict[str, str]] = []
        for value in sensitive:
            for field, text in field_text.items():
                if _has_residual_value(text, value):
                    residual_by_field[field] += 1
                    residuals.append({"field": field, "value_preview": _preview(value)})

        totals["examples"] += 1
        totals["sensitive_values"] += len(sensitive)
        totals["examples_with_sensitive_values"] += int(bool(sensitive))
        totals["examples_with_residuals"] += int(bool(residuals))
        totals["residual_values"] += len(residuals)
        placeholder_counts.update(_PLACEHOLDER_RE.findall(json.dumps(redacted, sort_keys=True)))
        if residuals and len(examples_with_residuals) < 20:
            examples_with_residuals.append(
                {
                    "id": example.get("id", ""),
                    "graph_profile": example.get("graph_profile", ""),
                    "category": example.get("category", ""),
                    "residuals": residuals[:10],
                }
            )

    return {
        "config": asdict(active_config),
        "policy": _policy_summary(active_policy),
        "examples": totals["examples"],
        "sensitive_values": totals["sensitive_values"],
        "examples_with_sensitive_values": totals["examples_with_sensitive_values"],
        "examples_with_residuals": totals["examples_with_residuals"],
        "residual_values": totals["residual_values"],
        "residual_rate_per_value": (
            totals["residual_values"] / totals["sensitive_values"]
            if totals["sensitive_values"]
            else 0.0
        ),
        "residuals_by_field": dict(sorted(residual_by_field.items())),
        "placeholder_linkability": {
            "unique_placeholders": len(placeholder_counts),
            "reused_placeholders": sum(1 for count in placeholder_counts.values() if count > 1),
            "max_placeholder_frequency": max(placeholder_counts.values(), default=0),
        },
        "examples_with_residuals_sample": examples_with_residuals,
        "threat_model": {
            "audited_surfaces": sorted(_redacted_field_text({}).keys()),
            "sensitive_sources": [
                "entity_values",
                "quoted Cypher literals",
                "reverse Cypher literals",
                "string-valued result samples",
            ],
            "not_claimed": [
                "semantic paraphrase detection",
                "full PII classification",
                "schema-name confidentiality",
            ],
        },
    }


def sensitive_values_for_example(
    example: dict[str, Any],
    *,
    min_chars: int = 3,
    include_numeric_literals: bool = False,
) -> list[str]:
    values: set[str] = set()
    for value in example.get("entity_values", []) or []:
        _add_value(values, value, min_chars=min_chars)
    for field in ("cypher", "normalized_cypher", "reverse_cypher"):
        text = example.get(field)
        if isinstance(text, str):
            for literal in _CYPHER_STRING_RE.findall(text):
                _add_value(values, _unquote(literal), min_chars=min_chars)
            if include_numeric_literals:
                for number in re.findall(r"\b\d+(?:\.\d+)?\b", text):
                    _add_value(values, number, min_chars=min_chars)
    for value in _string_leaves(example.get("result_rows_sample")):
        _add_value(values, value, min_chars=min_chars)
    return sorted(values, key=lambda item: (len(item), item))


def _redacted_field_text(example: dict[str, Any]) -> dict[str, str]:
    return {
        "question": str(example.get("question", "")),
        "cypher": str(example.get("cypher", "")),
        "normalized_cypher": str(example.get("normalized_cypher", "")),
        "reverse_cypher": str(example.get("reverse_cypher", "")),
        "entity_values": json.dumps(example.get("entity_values", []), sort_keys=True),
        "result_rows_sample": json.dumps(
            example.get("result_rows_sample", []), ensure_ascii=False, sort_keys=True
        ),
    }


def _string_leaves(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        out: list[str] = []
        for child in value.values():
            out.extend(_string_leaves(child))
        return out
    if isinstance(value, list):
        out = []
        for child in value:
            out.extend(_string_leaves(child))
        return out
    return []


def _add_value(values: set[str], value: Any, *, min_chars: int) -> None:
    text = str(value).strip()
    if len(text) >= min_chars:
        values.add(text)


def _unquote(raw: str) -> str:
    return raw[1:-1].replace("''", "'").replace("\\'", "'")


def _preview(value: str) -> str:
    return value if len(value) <= 24 else value[:21] + "..."


def _has_residual_value(text: str, value: str) -> bool:
    if not value:
        return False
    if re.fullmatch(r"[A-Za-z0-9_.:-]+", value):
        return bool(re.search(rf"(?<![A-Za-z0-9_]){re.escape(value)}(?![A-Za-z0-9_])", text))
    return value in text


def _policy_summary(policy: PrivacyPolicy) -> dict[str, Any]:
    summary = asdict(policy)
    summary.pop("hash_salt", None)
    summary["include_private_mapping"] = False
    return summary
