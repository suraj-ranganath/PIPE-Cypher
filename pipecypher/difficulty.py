"""Structural difficulty score for Cypher references.

The score is a weighted sum of query-structure counts (hops, stages,
aggregation, grouping, negation, temporal predicates, answer arity, ...). The
integer weights and the easy/medium/hard thresholds are calibrated on how many
of 11 downstream models solved each v2 held-out item
(``scripts/calibrate_difficulty.py``) and stored in
``configs/difficulty_v3.json``. Pure Python; no model calls.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from .cypher_parser import _split_projection_items, analyze_cypher
from .refresh_audit import mask_string_literals

DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[1] / "configs" / "difficulty_v3.json"
TIERS = ("easy", "medium", "hard")

_AGGREGATES = ("count", "sum", "avg", "min", "max", "collect", "stdev", "stdevp", "percentilecont", "percentiledisc")
_AGG_RE = re.compile(r"\b(" + "|".join(_AGGREGATES) + r")\s*\(", re.IGNORECASE)
_TEMPORAL_FN_RE = re.compile(r"\b(date|datetime|localdatetime|localtime|time|duration|timestamp)\s*\(", re.IGNORECASE)
_TEMPORAL_PROP_RE = re.compile(
    r"\.\s*(\w*(?:date|time|timestamp|createtime|creation|year|month)\w*)\b\s*(?:<=|>=|<>|=|<|>|IN\b)",
    re.IGNORECASE,
)
_TEMPORAL_PROP_RHS_RE = re.compile(
    r"(?:<=|>=|<>|=|<|>)\s*\w+\s*\.\s*(\w*(?:date|time|timestamp|createtime|creation)\w*)\b",
    re.IGNORECASE,
)
_TEMPORAL_REF_RE = re.compile(
    r"\.\s*\w*(?:date|time|timestamp)\w*\b",
    re.IGNORECASE,
)
_REL_RE = re.compile(r"<?-\s*\[[^\]]*\]\s*->?|<--|-->|(?<![<\-])--(?![>\-])")
_VARLEN_RE = re.compile(r"\[[^\]]*\*[^\]]*\]")
_CLAUSE_RE = re.compile(
    r"\b(OPTIONAL\s+MATCH|MATCH|WHERE|WITH|RETURN|ORDER\s+BY|SKIP|LIMIT|UNWIND|CALL|UNION)\b",
    re.IGNORECASE,
)
_INLINE_MAP_RE = re.compile(r"[(\[][^()\[\]]*\{([^{}]*)\}[^()\[\]]*[)\]]")


def _with_clause_spans(masked: str) -> list[tuple[str, str]]:
    """Return (clause_name, content) pairs for top-level clauses, ignoring STARTS/ENDS WITH."""

    marks: list[tuple[int, int, str]] = []
    for match in _CLAUSE_RE.finditer(masked):
        name = re.sub(r"\s+", " ", match.group(1).upper())
        if name == "WITH":
            before = masked[: match.start()].rstrip().upper()
            if before.endswith("STARTS") or before.endswith("ENDS"):
                continue
        marks.append((match.start(), match.end(), name))
    spans = []
    for idx, (_, end, name) in enumerate(marks):
        stop = marks[idx + 1][0] if idx + 1 < len(marks) else len(masked)
        spans.append((name, masked[end:stop]))
    return spans


def _depth_split(text: str, separators: tuple[str, ...]) -> list[str]:
    """Split on whole-word separators at bracket depth 0."""

    parts: list[str] = []
    depth = 0
    start = 0
    upper = text.upper()
    i = 0
    while i < len(text):
        char = text[i]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        elif depth == 0:
            for sep in separators:
                n = len(sep)
                if (
                    upper[i : i + n] == sep
                    and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] == "_"))
                    and (i + n >= len(text) or not (text[i + n].isalnum() or text[i + n] == "_"))
                ):
                    parts.append(text[start:i])
                    start = i + n
                    i += n - 1
                    break
        i += 1
    parts.append(text[start:])
    return [part for part in (p.strip() for p in parts) if part]


def difficulty_features(cypher: str) -> dict[str, float]:
    """Count the structural features the difficulty score uses."""

    masked = mask_string_literals(cypher or "")
    spans = _with_clause_spans(masked)
    names = [name for name, _ in spans]

    hops = len(_REL_RE.findall(masked))
    var_length = len(_VARLEN_RE.findall(masked)) + len(re.findall(r"shortestpath\s*\(", masked, re.IGNORECASE))

    aggregations = len(_AGG_RE.findall(masked))
    grouping_keys = 0
    for name, content in spans:
        if name not in {"WITH", "RETURN"}:
            continue
        body = re.sub(r"^\s*DISTINCT\b", "", content, flags=re.IGNORECASE)
        items = _split_projection_items(body)
        if any(_AGG_RE.search(item) for item in items):
            grouping_keys += sum(1 for item in items if not _AGG_RE.search(item) and item.strip() != "*")

    predicates = 0
    for name, content in spans:
        if name == "WHERE":
            predicates += len(_depth_split(content, ("AND", "OR", "XOR")))
    for map_body in _INLINE_MAP_RE.findall(masked):
        predicates += len([entry for entry in map_body.split(",") if ":" in entry])

    upper = masked.upper()
    negation = (
        len(re.findall(r"\bNOT\b", upper))
        + upper.count("<>")
    )
    temporal = (
        len(_TEMPORAL_FN_RE.findall(masked))
        + len(_TEMPORAL_PROP_RE.findall(masked))
        + len(_TEMPORAL_PROP_RHS_RE.findall(masked))
    )

    temporal_refs = len(_TEMPORAL_REF_RE.findall(masked)) + len(_TEMPORAL_FN_RE.findall(masked))
    rel_vars = {
        match.group(1)
        for match in re.finditer(r"\[\s*([A-Za-z_]\w*)\s*(?::|\]|\*|\{)", masked)
    }
    rel_props = sum(len(re.findall(r"\b" + re.escape(var) + r"\s*\.\s*\w+", masked)) for var in rel_vars)
    rel_props += len(re.findall(r"\b(relationships|nodes|length)\s*\(", masked, re.IGNORECASE))
    labels = set(re.findall(r"\(\s*\w*\s*:\s*(\w+)", masked))

    analysis = analyze_cypher(cypher or "")
    return_arity = len(analysis.projection_items)
    tokens = len(re.findall(r"\w+|[^\w\s]", masked))

    return {
        "hops": float(hops),
        "var_length": float(var_length),
        "stages": float(names.count("WITH")),
        "match_clauses": float(names.count("MATCH") + names.count("OPTIONAL MATCH")),
        "optional_match": float(names.count("OPTIONAL MATCH")),
        "aggregations": float(aggregations),
        "grouping_keys": float(grouping_keys),
        "distinct_aggregate": float(len(re.findall(r"\(\s*DISTINCT\b", upper))),
        "negation": float(negation),
        "predicates": float(predicates),
        "temporal": float(temporal),
        "temporal_refs": float(temporal_refs),
        "rel_props": float(rel_props),
        "labels": float(len(labels)),
        "return_arity": float(return_arity),
        "order_by": float("ORDER BY" in names),
        "limit": float("LIMIT" in names),
        "unwind_collect": float(names.count("UNWIND") + len(re.findall(r"\bcollect\s*\(", masked, re.IGNORECASE))),
        "tokens": float(tokens),
        "tokens_10": tokens / 10.0,
    }


@dataclass(frozen=True)
class DifficultyModel:
    """Integer weights over capped feature counts, plus tier thresholds.

    ``score = sum(weight[f] * min(feature[f], cap[f]))``. A score below
    ``thresholds[0]`` is easy, below ``thresholds[1]`` medium, otherwise hard.
    """

    weights: dict[str, float]
    caps: dict[str, float] = field(default_factory=dict)
    thresholds: tuple[float, float] = (0.0, 0.0)
    quotas: dict[str, dict[str, float]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def score(self, features: dict[str, float]) -> float:
        total = 0.0
        for name, weight in self.weights.items():
            value = float(features.get(name, 0.0))
            cap = self.caps.get(name)
            if cap is not None:
                value = min(value, float(cap))
            total += weight * value
        return total

    def tier(self, score: float) -> str:
        low, high = self.thresholds
        if score < low:
            return "easy"
        if score < high:
            return "medium"
        return "hard"

    def to_dict(self) -> dict[str, Any]:
        return {
            "weights": self.weights,
            "caps": self.caps,
            "thresholds": list(self.thresholds),
            "quotas": self.quotas,
            "metadata": self.metadata,
        }


def load_difficulty_model(path: str | Path | None = None) -> DifficultyModel:
    data = json.loads(Path(path or DEFAULT_MODEL_PATH).read_text(encoding="utf-8"))
    return model_from_dict(data)


def model_from_dict(data: dict[str, Any]) -> DifficultyModel:
    thresholds = data.get("thresholds") or [0.0, 0.0]
    return DifficultyModel(
        weights={str(k): float(v) for k, v in (data.get("weights") or {}).items()},
        caps={str(k): float(v) for k, v in (data.get("caps") or {}).items()},
        thresholds=(float(thresholds[0]), float(thresholds[1])),
        quotas={
            str(cat): {str(t): float(s) for t, s in shares.items()}
            for cat, shares in (data.get("quotas") or {}).items()
        },
        metadata=dict(data.get("metadata") or {}),
    )


@lru_cache(maxsize=4)
def _default_model() -> DifficultyModel:
    return load_difficulty_model(DEFAULT_MODEL_PATH)


def difficulty_score(cypher: str, model: DifficultyModel | None = None) -> float:
    return (model or _default_model()).score(difficulty_features(cypher))


def difficulty_tier(cypher: str, model: DifficultyModel | None = None) -> str:
    resolved = model or _default_model()
    return resolved.tier(resolved.score(difficulty_features(cypher)))


def tier_quota_counts(category: str, target: int, model: DifficultyModel | None = None) -> dict[str, int]:
    """Split a per-category target into per-tier counts using the model's quota shares.

    Largest-remainder rounding, so the counts always sum to ``target``. A
    category without explicit shares uses the ``"_default"`` entry.
    """

    resolved = model or _default_model()
    shares = resolved.quotas.get(category) or resolved.quotas.get("_default") or {}
    total = sum(shares.get(tier, 0.0) for tier in TIERS)
    if target <= 0 or total <= 0:
        return {tier: 0 for tier in TIERS}
    raw = {tier: target * shares.get(tier, 0.0) / total for tier in TIERS}
    counts = {tier: int(raw[tier]) for tier in TIERS}
    remainder = target - sum(counts.values())
    for tier in sorted(TIERS, key=lambda t: (raw[t] - counts[t]), reverse=True)[:remainder]:
        counts[tier] += 1
    return counts
