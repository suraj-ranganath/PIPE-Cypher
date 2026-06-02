from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from typing import Any, Iterable

from .models import SchemaSummary

TOKEN_SPAN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.'&+-]*")
POSSESSIVE_RE = re.compile(r"\b([A-Za-z0-9_]+)'s\b", re.IGNORECASE)
PUNCT_RE = re.compile(r"[-,.+_/]+")
SPACE_RE = re.compile(r"\s+")

DEFAULT_OMIT_TERMS = {
    "a",
    "an",
    "and",
    "any",
    "are",
    "as",
    "by",
    "company",
    "companies",
    "for",
    "from",
    "graph",
    "has",
    "have",
    "in",
    "is",
    "list",
    "loan",
    "loans",
    "medium",
    "message",
    "messages",
    "of",
    "person",
    "persons",
    "show",
    "tag",
    "tags",
    "that",
    "the",
    "to",
    "what",
    "which",
    "who",
    "with",
}


@dataclass(frozen=True)
class ValueEntry:
    label: str
    property: str
    value: str
    aliases: tuple[str, ...] = ()

    @property
    def schema_path(self) -> str:
        return f"{self.label}.{self.property}" if self.property else self.label


@dataclass(frozen=True)
class GroundedMention:
    text: str
    canonical_value: str
    label: str
    property: str
    start: int
    end: int
    score: float
    match_type: str
    placeholder: str

    @property
    def schema_path(self) -> str:
        return f"{self.label}.{self.property}" if self.property else self.label

    def to_prompt_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["schema_path"] = self.schema_path
        return row


@dataclass(frozen=True)
class _Alias:
    normalized: str
    entry: ValueEntry
    source: str


def normalize_value_text(text: str) -> str:
    normalized = str(text).strip().replace("&", " and ")
    normalized = normalized.replace('"', "'")
    normalized = POSSESSIVE_RE.sub(r"\1", normalized)
    normalized = PUNCT_RE.sub(" ", normalized)
    normalized = re.sub(r"[^A-Za-z0-9' ]+", " ", normalized)
    normalized = SPACE_RE.sub(" ", normalized).strip().lower()
    return normalized


class ValueGrounder:
    """Dependency-light value grounding inspired by a cypher example reference annotation layer.

    The cypher example reference uses tenant dictionaries, typo correction, and
    entity-ruler patterns before prompting for Cypher. PIPE-Cypher keeps the same
    design principle but
    avoids spaCy/SymSpell dependencies so deterministic tests and CPU-only smoke
    runs remain runnable.
    """

    def __init__(
        self,
        entries: Iterable[ValueEntry],
        *,
        synonym_map: dict[str, str] | None = None,
        omit_terms: Iterable[str] = DEFAULT_OMIT_TERMS,
        fuzzy_threshold: float = 0.88,
        max_ngram_tokens: int = 5,
    ) -> None:
        self.entries = tuple(entry for entry in entries if str(entry.value).strip())
        self.omit_terms = {normalize_value_text(term) for term in omit_terms}
        self.fuzzy_threshold = fuzzy_threshold
        self.max_ngram_tokens = max_ngram_tokens
        self.aliases = self._build_aliases(synonym_map or {})

    @classmethod
    def from_schema_and_hints(
        cls,
        schema: SchemaSummary,
        entity_hints: dict[str, str] | None = None,
        *,
        synonym_map: dict[str, str] | None = None,
    ) -> "ValueGrounder":
        entries = list(schema_categorical_entries(schema))
        entries.extend(slot_hint_entries(entity_hints or {}))
        return cls(entries, synonym_map=synonym_map)

    def ground(self, text: str) -> list[GroundedMention]:
        candidates: list[GroundedMention] = []
        token_spans = _token_spans(text)
        if not token_spans:
            return []

        for start_idx in range(len(token_spans)):
            max_end = min(len(token_spans), start_idx + self.max_ngram_tokens)
            for end_idx in range(start_idx + 1, max_end + 1):
                start = token_spans[start_idx][0]
                end = token_spans[end_idx - 1][1]
                mention = text[start:end]
                mention_norm = normalize_value_text(mention)
                if not self._groundable_mention(mention_norm):
                    continue
                match = self._best_alias_match(mention_norm)
                if match is None:
                    continue
                alias, score, match_type = match
                candidates.append(
                    GroundedMention(
                        text=mention,
                        canonical_value=alias.entry.value,
                        label=alias.entry.label,
                        property=alias.entry.property,
                        start=start,
                        end=end,
                        score=round(score, 3),
                        match_type=match_type,
                        placeholder=_placeholder_for(alias.entry),
                    )
                )
        return _select_non_overlapping(candidates)

    def annotate_text(self, text: str, mentions: list[GroundedMention] | None = None) -> str:
        selected = mentions if mentions is not None else self.ground(text)
        annotated = text
        for mention in sorted(selected, key=lambda item: item.start, reverse=True):
            replacement = f"({mention.schema_path}: {mention.canonical_value})"
            annotated = annotated[: mention.start] + replacement + annotated[mention.end :]
        return annotated

    def _build_aliases(self, synonym_map: dict[str, str]) -> tuple[_Alias, ...]:
        by_canonical = {
            normalize_value_text(entry.value): entry
            for entry in self.entries
            if normalize_value_text(entry.value)
        }
        aliases: dict[tuple[str, str, str, str], _Alias] = {}
        for entry in self.entries:
            for normalized, source in _entry_aliases(entry):
                if self._groundable_alias(normalized):
                    aliases[(entry.schema_path, entry.value, normalized, source)] = _Alias(
                        normalized=normalized,
                        entry=entry,
                        source=source,
                    )
        for alias, canonical in synonym_map.items():
            entry = by_canonical.get(normalize_value_text(canonical))
            alias_norm = normalize_value_text(alias)
            if entry and self._groundable_alias(alias_norm):
                aliases[(entry.schema_path, entry.value, alias_norm, "synonym")] = _Alias(
                    normalized=alias_norm,
                    entry=entry,
                    source="synonym",
                )
        return tuple(
            sorted(
                aliases.values(),
                key=lambda item: (-len(item.normalized), item.normalized),
            )
        )

    def _best_alias_match(self, mention_norm: str) -> tuple[_Alias, float, str] | None:
        best: tuple[_Alias, float, str] | None = None
        for alias in self.aliases:
            if mention_norm == alias.normalized:
                match_type = "exact" if alias.source == "canonical" else alias.source
                score = 1.0
            elif _can_fuzzy_match(mention_norm, alias.normalized):
                score = SequenceMatcher(None, mention_norm, alias.normalized).ratio()
                match_type = "fuzzy"
            else:
                continue
            if score < self.fuzzy_threshold:
                continue
            if best is None or (score, len(alias.normalized)) > (best[1], len(best[0].normalized)):
                best = alias, score, match_type
        return best

    def _groundable_mention(self, mention_norm: str) -> bool:
        if not mention_norm or mention_norm in self.omit_terms:
            return False
        if len(mention_norm) < 3:
            return False
        return True

    def _groundable_alias(self, alias_norm: str) -> bool:
        return self._groundable_mention(alias_norm)


def schema_categorical_entries(schema: SchemaSummary) -> list[ValueEntry]:
    entries: list[ValueEntry] = []
    for key, values in sorted(schema.categorical_properties.items()):
        if "." not in key:
            continue
        label, prop = key.split(".", 1)
        entries.extend(ValueEntry(label=label, property=prop, value=str(value)) for value in values)
    return entries


def slot_hint_entries(entity_hints: dict[str, str]) -> list[ValueEntry]:
    entries: list[ValueEntry] = []
    for slot, hint in entity_hints.items():
        value, _, label_prop = str(hint).partition("|")
        value = value.strip()
        label_prop = label_prop.strip()
        if "." in label_prop:
            label, prop = label_prop.split(".", 1)
        else:
            label, prop = str(slot), ""
        entries.append(ValueEntry(label=label.strip(), property=prop.strip(), value=value))
    return entries


def _entry_aliases(entry: ValueEntry) -> set[tuple[str, str]]:
    aliases = {
        (normalize_value_text(entry.value), "canonical"),
        *((normalize_value_text(alias), "alias") for alias in entry.aliases),
    }
    tokens = normalize_value_text(entry.value).split()
    if len(tokens) == 1:
        token = tokens[0]
        if not token.endswith("s"):
            aliases.add((f"{token}s", "plural"))
    if _allows_name_partials(entry) and len(tokens) >= 2:
        first = tokens[0]
        last = tokens[-1]
        aliases.add((first, "partial"))
        aliases.add((last, "partial"))
        aliases.add((f"{first} {last[:1]}", "abbreviation"))
        aliases.add((f"{first[:1]} {last}", "abbreviation"))
    return {(alias, source) for alias, source in aliases if alias}


def _allows_name_partials(entry: ValueEntry) -> bool:
    prop = entry.property.lower()
    label = entry.label.lower()
    return "name" in prop and label in {"person", "employee", "user", "identity", "company"}


def _can_fuzzy_match(a: str, b: str) -> bool:
    if a == b:
        return True
    if len(a) < 4 or len(b) < 4:
        return False
    a_tokens = a.split()
    b_tokens = b.split()
    if len(a_tokens) != len(b_tokens):
        return False
    if abs(len(a) - len(b)) > max(2, int(0.2 * max(len(a), len(b)))):
        return False
    return True


def _token_spans(text: str) -> list[tuple[int, int, str]]:
    return [(match.start(), match.end(), match.group(0)) for match in TOKEN_SPAN_RE.finditer(text)]


def _select_non_overlapping(candidates: list[GroundedMention]) -> list[GroundedMention]:
    selected: list[GroundedMention] = []
    for candidate in sorted(
        candidates,
        key=lambda item: (
            -(item.end - item.start),
            -item.score,
            item.label,
            item.property,
            item.canonical_value,
        ),
    ):
        if any(_overlaps(candidate, accepted) for accepted in selected):
            continue
        selected.append(candidate)
    return sorted(selected, key=lambda item: item.start)


def _overlaps(left: GroundedMention, right: GroundedMention) -> bool:
    return left.start < right.end and right.start < left.end


def _placeholder_for(entry: ValueEntry) -> str:
    stem = re.sub(r"[^A-Za-z0-9]+", "_", entry.property or entry.label).strip("_").upper()
    return "{{" + f"{stem or 'VALUE'}_GROUNDING" + "}}"
