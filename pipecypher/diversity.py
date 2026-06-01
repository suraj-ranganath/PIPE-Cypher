from __future__ import annotations

import re
from collections import Counter, defaultdict

from .retrieval import tokenize


class EntityDiversityTracker:
    """Caps repeated entity/value usage within each category."""

    def __init__(self, max_entity_pct: float = 0.15) -> None:
        self.max_entity_pct = max_entity_pct
        self.counts: dict[str, Counter[str]] = defaultdict(Counter)
        self.total_by_category: Counter[str] = Counter()

    def would_exceed(self, category: str, values: list[str], target_per_category: int) -> bool:
        cap = max(2, int(target_per_category * self.max_entity_pct))
        for value in values:
            if value and self.counts[category][value] + 1 > cap:
                return True
        return False

    def record(self, category: str, values: list[str]) -> None:
        for value in values:
            if value:
                self.counts[category][value] += 1
        self.total_by_category[category] += 1


def question_signature(question: str) -> str:
    text = re.sub(r"'[^']+'", "'<VALUE>'", question)
    text = re.sub(r"\b\d+(\.\d+)?\b", "<NUMBER>", text)
    return " ".join(tokenize(text))


class StructuralDiversityTracker:
    def __init__(self) -> None:
        self.signatures: set[tuple[str, str]] = set()

    def seen(self, category: str, question: str) -> bool:
        signature = (category, question_signature(question))
        if signature in self.signatures:
            return True
        self.signatures.add(signature)
        return False

