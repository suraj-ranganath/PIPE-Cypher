from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


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

    def format_examples(self, examples: list[dict[str, Any]]) -> str:
        if not examples:
            return "None"
        rows = []
        for idx, example in enumerate(examples, start=1):
            rows.append(
                f"{idx}. Question: {example.get('question', '')}\n"
                f"   Cypher: {example.get('cypher', example.get('query', ''))}"
            )
        return "\n".join(rows)

