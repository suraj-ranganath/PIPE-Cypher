from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
STRING_LITERAL_RE = re.compile(r"'((?:\\'|[^'])*)'|\"((?:\\\"|[^\"])*)\"")


def tokenize(text: str) -> list[str]:
    return [x.lower() for x in TOKEN_RE.findall(text)]


def cosine_counts(a: list[str], b: list[str]) -> float:
    if not a or not b:
        return 0.0
    ca = {tok: a.count(tok) for tok in set(a)}
    cb = {tok: b.count(tok) for tok in set(b)}
    dot = sum(ca[tok] * cb.get(tok, 0) for tok in ca)
    norm_a = math.sqrt(sum(v * v for v in ca.values()))
    norm_b = math.sqrt(sum(v * v for v in cb.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _string_literals(text: str) -> list[str]:
    literals: list[str] = []
    for single, double in STRING_LITERAL_RE.findall(text):
        literals.append(single if single else double)
    return literals


def _safe_values(values: list[Any]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if len(text) < 2 or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    cleaned.sort(key=len, reverse=True)
    return cleaned


def _placeholder_stem(value: str, cypher: str) -> str:
    escaped = re.escape(value)
    patterns = [
        rf"\b(?P<prop>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*['\"]{escaped}['\"]",
        rf"\.[ ]*(?P<prop>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*['\"]{escaped}['\"]",
    ]
    for pattern in patterns:
        match = re.search(pattern, cypher)
        if match:
            stem = re.sub(r"[^A-Za-z0-9]+", "_", match.group("prop")).strip("_")
            if stem:
                return stem.upper()
    return "VALUE"


def _replace_values(text: str, mapping: dict[str, str]) -> str:
    replaced = text
    for value, placeholder in sorted(mapping.items(), key=lambda item: len(item[0]), reverse=True):
        replaced = re.sub(re.escape(value), placeholder, replaced)
    return replaced


def placeholderize_example(example: dict[str, Any]) -> dict[str, Any]:
    """Return a retrieval-safe example with graph-specific values replaced.

    This mirrors the BalkanID pattern of adding examples with tenant-specific
    values replaced by typed placeholders. The goal is to preserve query shape
    while reducing value leakage and memorized entity reuse in few-shot prompts.
    """

    question = str(example.get("question", ""))
    cypher = str(example.get("cypher", example.get("query", "")))
    raw_entity_values = example.get("entity_values", [])
    if not isinstance(raw_entity_values, list):
        raw_entity_values = [raw_entity_values]
    values = _safe_values(
        [
            *raw_entity_values,
            *_string_literals(question),
        ]
    )
    mapping: dict[str, str] = {}
    stem_counts: dict[str, int] = {}
    for value in values:
        stem = _placeholder_stem(value, cypher)
        stem_counts[stem] = stem_counts.get(stem, 0) + 1
        mapping[value] = "{{" + f"{stem}_{stem_counts[stem]}" + "}}"

    if not mapping:
        return {
            **example,
            "placeholder_map": {},
            "question": question,
            "cypher": cypher,
        }
    return {
        **example,
        "placeholder_map": mapping,
        "question": _replace_values(question, mapping),
        "cypher": _replace_values(cypher, mapping),
    }


@dataclass
class ExampleStore:
    examples: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_jsonl(cls, path: str | Path) -> "ExampleStore":
        examples = []
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                examples.append(json.loads(line))
        return cls(examples)

    def add(self, question: str, cypher: str, category: str, **extra: Any) -> None:
        self.examples.append({"question": question, "cypher": cypher, "category": category, **extra})

    def top_k(
        self,
        query: str,
        *,
        k: int = 3,
        category: str | None = None,
        leakage_threshold: float = 0.995,
    ) -> list[dict[str, Any]]:
        query_tokens = tokenize(query)
        scored = []
        for example in self.examples:
            if category and example.get("category") != category:
                continue
            score = cosine_counts(query_tokens, tokenize(str(example.get("question", ""))))
            if score >= leakage_threshold:
                continue
            scored.append((score, example))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [{**example, "score": score} for score, example in scored[:k]]

    def format_examples(self, examples: list[dict[str, Any]], *, anonymize: bool = True) -> str:
        if not examples:
            return "None"
        rows = []
        for idx, example in enumerate(examples, start=1):
            display = placeholderize_example(example) if anonymize else example
            rows.append(
                f"{idx}. Question: {display.get('question', '')}\n"
                f"   Cypher: {display.get('cypher', display.get('query', ''))}"
            )
        return "\n".join(rows)
