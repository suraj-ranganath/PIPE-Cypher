from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any


_CYPHER_STRING_RE = re.compile(r"'(?:''|\\'|[^'])*'")


@dataclass(frozen=True)
class PrivacyPolicy:
    """Controls redaction for benchmark examples shared outside the data boundary."""

    redact_questions: bool = True
    redact_cypher_literals: bool = True
    redact_reverse_cypher: bool = True
    redact_entity_values: bool = True
    redact_result_samples: bool = True
    redact_numeric_literals: bool = False
    hash_placeholders: bool = False
    placeholder_prefix: str = "VALUE"
    include_private_mapping: bool = False
    hash_salt: str = ""


@dataclass(frozen=True)
class ValueSamplingPolicy:
    """Controls whether graph-derived values are exposed in prompts/schema summaries."""

    mode: str = "bounded"
    max_values_per_property: int = 12
    omitted_properties: tuple[str, ...] = field(default_factory=tuple)
    hash_values: bool = False
    hash_salt: str = ""


@dataclass(frozen=True)
class RedactionReport:
    redacted: bool
    literal_count: int
    result_sample_values: int
    policy: dict[str, Any]


def redact_example(
    example: dict[str, Any],
    *,
    policy: PrivacyPolicy | None = None,
) -> dict[str, Any]:
    """Return a redacted copy of one benchmark example.

    The returned object intentionally omits the raw value mapping by default.
    This lets teams commit or share redacted artifacts without leaking the
    original tenant values through metadata.
    """

    active_policy = policy or PrivacyPolicy()
    redacted = copy.deepcopy(example)
    state = _RedactionState(active_policy)

    literal_values: list[str] = []
    for field_name in ("cypher", "normalized_cypher"):
        text = redacted.get(field_name)
        if isinstance(text, str) and active_policy.redact_cypher_literals:
            redacted[field_name], values = _redact_cypher_literals(text, state)
            literal_values.extend(values)

    if active_policy.redact_reverse_cypher and isinstance(redacted.get("reverse_cypher"), str):
        redacted["reverse_cypher"], values = _redact_cypher_literals(redacted["reverse_cypher"], state)
        literal_values.extend(values)

    entity_values = [str(value) for value in redacted.get("entity_values", [])]
    for value in entity_values:
        if value:
            state.placeholder_for(value)

    if active_policy.redact_questions and isinstance(redacted.get("question"), str):
        redacted["question"] = _redact_text_values(
            redacted["question"],
            values=sorted(set(entity_values + literal_values), key=len, reverse=True),
            state=state,
        )

    if active_policy.redact_entity_values:
        redacted["entity_values"] = [state.placeholder_for(str(value)) for value in entity_values]

    result_redactions = 0
    if active_policy.redact_result_samples and "result_rows_sample" in redacted:
        redacted["result_rows_sample"], result_redactions = _redact_result_value(
            redacted["result_rows_sample"],
            state,
            redact_numeric=active_policy.redact_numeric_literals,
        )

    private_mapping = state.private_mapping()
    redacted["privacy_redaction"] = asdict(
        RedactionReport(
            redacted=True,
            literal_count=len(private_mapping),
            result_sample_values=result_redactions,
            policy=_public_policy(active_policy),
        )
    )
    if active_policy.include_private_mapping:
        redacted["privacy_redaction"]["private_mapping"] = private_mapping
    return redacted


def redact_examples(
    examples: list[dict[str, Any]],
    *,
    policy: PrivacyPolicy | None = None,
) -> list[dict[str, Any]]:
    return [redact_example(example, policy=policy) for example in examples]


def sample_categorical_values(
    property_key: str,
    values: list[Any],
    *,
    policy: ValueSamplingPolicy | None = None,
) -> list[str]:
    """Apply an enterprise value-sampling policy to a property value list."""

    active_policy = policy or ValueSamplingPolicy()
    if property_key in active_policy.omitted_properties or active_policy.mode == "none":
        return []
    unique_values = sorted({str(value) for value in values if value is not None})
    if not unique_values:
        return []
    if active_policy.mode == "bounded" and len(unique_values) > active_policy.max_values_per_property:
        return []
    sampled = unique_values[: max(0, active_policy.max_values_per_property)]
    if active_policy.mode == "hash" or active_policy.hash_values:
        return [_hash_value(value, salt=active_policy.hash_salt) for value in sampled]
    if active_policy.mode != "bounded":
        raise ValueError(f"unsupported value sampling mode: {active_policy.mode}")
    return sampled


def _redact_cypher_literals(text: str, state: "_RedactionState") -> tuple[str, list[str]]:
    values: list[str] = []

    def replace(match: re.Match[str]) -> str:
        raw = match.group(0)
        value = _unquote_cypher_string(raw)
        values.append(value)
        return f"'{state.placeholder_for(value)}'"

    return _CYPHER_STRING_RE.sub(replace, text), values


def _redact_text_values(text: str, *, values: list[str], state: "_RedactionState") -> str:
    out = text
    for value in values:
        if not value:
            continue
        out = out.replace(value, state.placeholder_for(value))
    return out


def _redact_result_value(
    value: Any,
    state: "_RedactionState",
    *,
    redact_numeric: bool,
) -> tuple[Any, int]:
    if isinstance(value, dict):
        total = 0
        redacted: dict[str, Any] = {}
        for key, child in value.items():
            redacted_child, child_count = _redact_result_value(
                child,
                state,
                redact_numeric=redact_numeric,
            )
            redacted[key] = redacted_child
            total += child_count
        return redacted, total
    if isinstance(value, list):
        total = 0
        redacted_list = []
        for child in value:
            redacted_child, child_count = _redact_result_value(
                child,
                state,
                redact_numeric=redact_numeric,
            )
            redacted_list.append(redacted_child)
            total += child_count
        return redacted_list, total
    if isinstance(value, str):
        return state.placeholder_for(value), 1
    if redact_numeric and isinstance(value, (int, float)) and not isinstance(value, bool):
        return state.placeholder_for(str(value)), 1
    return value, 0


def _unquote_cypher_string(raw: str) -> str:
    inner = raw[1:-1]
    return inner.replace("''", "'").replace("\\'", "'")


def _hash_value(value: str, *, salt: str) -> str:
    payload = json.dumps({"salt": salt, "value": value}, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:12]


def _public_policy(policy: PrivacyPolicy) -> dict[str, Any]:
    public = asdict(policy)
    public.pop("hash_salt", None)
    public["include_private_mapping"] = False
    return public


class _RedactionState:
    def __init__(self, policy: PrivacyPolicy) -> None:
        self.policy = policy
        self._mapping: dict[str, str] = {}

    def placeholder_for(self, value: str) -> str:
        if value not in self._mapping:
            index = len(self._mapping) + 1
            if self.policy.hash_placeholders:
                suffix = _hash_value(value, salt=self.policy.hash_salt)
            else:
                suffix = f"{index:03d}"
            self._mapping[value] = f"__{self.policy.placeholder_prefix}_{suffix}__"
        return self._mapping[value]

    def private_mapping(self) -> dict[str, str]:
        return {placeholder: value for value, placeholder in self._mapping.items()}
