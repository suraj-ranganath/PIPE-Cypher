"""Schema diffs between two property-graph schema snapshots.

Used by the benchmark-refresh experiment: introspect a graph before and after a
schema migration or data drift, diff the two ``SchemaSummary`` JSON files, and
translate the diff into *schema atoms* that individual benchmark items touch.

Atom vocabulary (shared with :mod:`pipecypher.refresh_audit`)::

    label:Account
    rel:TRANSFER_TO
    pattern:(:Account)-[:TRANSFER_TO]->(:Account)
    prop:Account.isBlocked
    relprop:TRANSFER_TO.amount
    cat:Account.accountType

*Breaking* atoms are structures that disappeared or changed type (queries using
them can fail validation or silently return different rows). *Drift* atoms are
structures whose data volume or value vocabulary changed without a structural
break (queries using them stay valid but may return different answers).

Rename detection is heuristic and always reported with a confidence and the
evidence used, so downstream rewrites can be gated on a threshold and audited.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .models import SchemaSummary
from .schema import load_schema

RENAME_KINDS = (
    "relationship_type",
    "label",
    "label_split",
    "node_property",
    "relationship_property",
)

# Renames at or above this confidence may drive mechanical rewrites by default.
DEFAULT_REWRITE_CONFIDENCE = 0.75

_PATTERN_RE = re.compile(r"^\(:(?P<start>[^)]*)\)-\[:(?P<type>[^\]]*)\]->\(:(?P<end>[^)]*)\)$")


def label_atom(label: str) -> str:
    return f"label:{label}"


def rel_atom(rel_type: str) -> str:
    return f"rel:{rel_type}"


def pattern_text(start_label: str, rel_type: str, end_label: str) -> str:
    return f"(:{start_label})-[:{rel_type}]->(:{end_label})"


def pattern_atom(start_label: str, rel_type: str, end_label: str) -> str:
    return "pattern:" + pattern_text(start_label, rel_type, end_label)


def prop_atom(label: str, prop: str) -> str:
    return f"prop:{label}.{prop}"


def relprop_atom(rel_type: str, prop: str) -> str:
    return f"relprop:{rel_type}.{prop}"


def cat_atom(label: str, prop: str) -> str:
    return f"cat:{label}.{prop}"


def parse_pattern_text(text: str) -> tuple[str, str, str] | None:
    match = _PATTERN_RE.match(text.strip())
    if not match:
        return None
    return match.group("start"), match.group("type"), match.group("end")


@dataclass(frozen=True)
class RenameCandidate:
    """A heuristic rename (or label split) between two schema snapshots."""

    kind: str
    before: str
    after: str
    confidence: float
    scope: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["confidence"] = round(float(self.confidence), 4)
        return data


@dataclass
class SchemaDiff:
    before_graph: str = "unknown"
    after_graph: str = "unknown"
    added_labels: list[str] = field(default_factory=list)
    removed_labels: list[str] = field(default_factory=list)
    added_relationship_types: list[str] = field(default_factory=list)
    removed_relationship_types: list[str] = field(default_factory=list)
    added_relationship_patterns: list[str] = field(default_factory=list)
    removed_relationship_patterns: list[str] = field(default_factory=list)
    added_node_properties: list[str] = field(default_factory=list)
    removed_node_properties: list[str] = field(default_factory=list)
    node_property_type_changes: list[dict[str, Any]] = field(default_factory=list)
    added_relationship_properties: list[str] = field(default_factory=list)
    removed_relationship_properties: list[str] = field(default_factory=list)
    relationship_property_type_changes: list[dict[str, Any]] = field(default_factory=list)
    categorical_changes: list[dict[str, Any]] = field(default_factory=list)
    relationship_count_changes: list[dict[str, Any]] = field(default_factory=list)
    rename_candidates: list[RenameCandidate] = field(default_factory=list)
    pruned_ghost_entries: dict[str, list[str]] = field(default_factory=dict)

    # -- classification -------------------------------------------------

    def has_structural_changes(self) -> bool:
        return any(
            (
                self.added_labels,
                self.removed_labels,
                self.added_relationship_types,
                self.removed_relationship_types,
                self.added_relationship_patterns,
                self.removed_relationship_patterns,
                self.added_node_properties,
                self.removed_node_properties,
                self.node_property_type_changes,
                self.added_relationship_properties,
                self.removed_relationship_properties,
                self.relationship_property_type_changes,
            )
        )

    def is_empty(self) -> bool:
        return not (
            self.has_structural_changes()
            or self.categorical_changes
            or self.relationship_count_changes
        )

    def breaking_atoms(self) -> set[str]:
        atoms: set[str] = set()
        atoms.update(label_atom(label) for label in self.removed_labels)
        atoms.update(rel_atom(rel_type) for rel_type in self.removed_relationship_types)
        for text in self.removed_relationship_patterns:
            parsed = parse_pattern_text(text)
            if parsed:
                atoms.add(pattern_atom(*parsed))
        for key in self.removed_node_properties:
            atoms.add("prop:" + key)
        for key in self.removed_relationship_properties:
            atoms.add("relprop:" + key)
        for change in self.node_property_type_changes:
            atoms.add("prop:" + str(change["key"]))
        for change in self.relationship_property_type_changes:
            atoms.add("relprop:" + str(change["key"]))
        for change in self.categorical_changes:
            if change.get("change") == "values_changed" and change.get("removed_values"):
                atoms.add("cat:" + str(change["key"]))
        return atoms

    def drift_atoms(self) -> set[str]:
        atoms: set[str] = set()
        for change in self.relationship_count_changes:
            atoms.add(
                pattern_atom(change["start_label"], change["type"], change["end_label"])
            )
        for text in self.added_relationship_patterns:
            # A new pattern can change answers of queries that match the
            # relationship type with an unlabeled endpoint; item-side wildcard
            # matching decides relevance.
            parsed = parse_pattern_text(text)
            if parsed:
                atoms.add(pattern_atom(*parsed))
        for change in self.categorical_changes:
            if change.get("change") != "values_changed" or not change.get("removed_values"):
                atoms.add("cat:" + str(change["key"]))
        for candidate in self.rename_candidates:
            if candidate.kind == "label_split":
                atoms.add(label_atom(candidate.before))
        return atoms - self.breaking_atoms()

    def changed_atoms(self) -> set[str]:
        return self.breaking_atoms() | self.drift_atoms()

    def renames(
        self,
        kind: str,
        *,
        min_confidence: float = DEFAULT_REWRITE_CONFIDENCE,
    ) -> list[RenameCandidate]:
        if kind not in RENAME_KINDS:
            raise ValueError(f"unknown rename kind: {kind}")
        return [
            candidate
            for candidate in self.rename_candidates
            if candidate.kind == kind and candidate.confidence >= min_confidence
        ]

    def rename_map(
        self,
        kind: str,
        *,
        min_confidence: float = DEFAULT_REWRITE_CONFIDENCE,
    ) -> dict[str, str]:
        """Return ``before -> after`` for one rename kind.

        Property renames are keyed by ``OwnerBefore.property`` (the label or
        relationship type as written in pre-migration Cypher) and map to the new
        property name only.
        """

        mapping: dict[str, str] = {}
        for candidate in self.renames(kind, min_confidence=min_confidence):
            if kind in {"node_property", "relationship_property"}:
                mapping[f"{candidate.scope}.{candidate.before}"] = candidate.after
            else:
                mapping[candidate.before] = candidate.after
        return mapping

    def renamed_atoms(self, *, min_confidence: float = DEFAULT_REWRITE_CONFIDENCE) -> dict[str, str]:
        """Map breaking atoms to the atom that replaces them under confident renames."""

        mapping: dict[str, str] = {}
        for candidate in self.rename_candidates:
            if candidate.confidence < min_confidence:
                continue
            owner_after = str(candidate.evidence.get("owner_after") or candidate.scope or "")
            if candidate.kind == "relationship_type":
                mapping[rel_atom(candidate.before)] = rel_atom(candidate.after)
                for text in self.removed_relationship_patterns:
                    parsed = parse_pattern_text(text)
                    if parsed and parsed[1] == candidate.before:
                        mapping[pattern_atom(*parsed)] = pattern_atom(
                            parsed[0], candidate.after, parsed[2]
                        )
                for key in self.removed_relationship_properties:
                    owner, _, prop = key.partition(".")
                    if owner == candidate.before:
                        mapping[relprop_atom(owner, prop)] = relprop_atom(candidate.after, prop)
            elif candidate.kind == "label":
                mapping[label_atom(candidate.before)] = label_atom(candidate.after)
                for key in self.removed_node_properties:
                    owner, _, prop = key.partition(".")
                    if owner == candidate.before:
                        mapping[prop_atom(owner, prop)] = prop_atom(candidate.after, prop)
            elif candidate.kind == "node_property" and candidate.scope:
                mapping[prop_atom(candidate.scope, candidate.before)] = prop_atom(
                    owner_after, candidate.after
                )
            elif candidate.kind == "relationship_property" and candidate.scope:
                mapping[relprop_atom(candidate.scope, candidate.before)] = relprop_atom(
                    owner_after, candidate.after
                )
        return mapping

    def summary_counts(self) -> dict[str, int]:
        return {
            "added_labels": len(self.added_labels),
            "removed_labels": len(self.removed_labels),
            "added_relationship_types": len(self.added_relationship_types),
            "removed_relationship_types": len(self.removed_relationship_types),
            "added_relationship_patterns": len(self.added_relationship_patterns),
            "removed_relationship_patterns": len(self.removed_relationship_patterns),
            "added_node_properties": len(self.added_node_properties),
            "removed_node_properties": len(self.removed_node_properties),
            "node_property_type_changes": len(self.node_property_type_changes),
            "added_relationship_properties": len(self.added_relationship_properties),
            "removed_relationship_properties": len(self.removed_relationship_properties),
            "relationship_property_type_changes": len(self.relationship_property_type_changes),
            "categorical_changes": len(self.categorical_changes),
            "relationship_count_changes": len(self.relationship_count_changes),
            "rename_candidates": len(self.rename_candidates),
            "breaking_atoms": len(self.breaking_atoms()),
            "drift_atoms": len(self.drift_atoms()),
        }

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["rename_candidates"] = [candidate.to_dict() for candidate in self.rename_candidates]
        data["breaking_atoms"] = sorted(self.breaking_atoms())
        data["drift_atoms"] = sorted(self.drift_atoms())
        data["has_structural_changes"] = self.has_structural_changes()
        data["summary_counts"] = self.summary_counts()
        return data


# ---------------------------------------------------------------------------
# Snapshot helpers


def observed_relationship_types(schema: SchemaSummary) -> set[str]:
    """Relationship types backed by observed patterns.

    ``db.schema.relTypeProperties()`` may keep reporting a relationship type
    after all of its relationships were deleted. When pattern counts are
    available, they are the data-backed source of truth.
    """

    if schema.relationships:
        return {rel.type for rel in schema.relationships}
    return {prop.type for prop in schema.relationship_properties}


def prune_ghost_schema_entries(schema: SchemaSummary) -> tuple[SchemaSummary, list[str]]:
    """Drop relationship-property metadata for types with no observed pattern.

    Returns the pruned copy plus the ``relprop:`` atoms that were removed, so the
    caller can log them. Schemas without relationship patterns are returned
    unchanged (nothing to cross-check against).
    """

    if not schema.relationships:
        return schema, []
    observed = {rel.type for rel in schema.relationships}
    kept = []
    pruned: list[str] = []
    for prop in schema.relationship_properties:
        if prop.type in observed:
            kept.append(prop)
        else:
            pruned.append(relprop_atom(prop.type, prop.property))
    if not pruned:
        return schema, []
    return (
        SchemaSummary(
            node_properties=list(schema.node_properties),
            relationship_properties=kept,
            relationships=list(schema.relationships),
            categorical_properties=dict(schema.categorical_properties),
            graph_name=schema.graph_name,
            source=schema.source,
        ),
        sorted(pruned),
    )


def _label_props(schema: SchemaSummary) -> dict[str, dict[str, str]]:
    props: dict[str, dict[str, str]] = {}
    for prop in schema.node_properties:
        props.setdefault(prop.label, {})[prop.property] = prop.type
    return props


def _rel_props(schema: SchemaSummary) -> dict[str, dict[str, str]]:
    props: dict[str, dict[str, str]] = {}
    for prop in schema.relationship_properties:
        props.setdefault(prop.type, {})[prop.property] = prop.value_type
    return props


def _pattern_counts(schema: SchemaSummary) -> dict[tuple[str, str, str], int | None]:
    counts: dict[tuple[str, str, str], int | None] = {}
    for rel in schema.relationships:
        key = (rel.start_label, rel.type, rel.end_label)
        if rel.count is None:
            counts.setdefault(key, None)
        else:
            counts[key] = (counts.get(key) or 0) + int(rel.count)
    return counts


def _jaccard(left: Iterable[Any], right: Iterable[Any], *, empty: float = 1.0) -> float:
    a, b = set(left), set(right)
    if not a and not b:
        return empty
    return len(a & b) / len(a | b)


def _types_compatible(left: str, right: str) -> bool:
    left_n, right_n = left.strip().upper(), right.strip().upper()
    return left_n == right_n or "ANY" in {left_n, right_n}


def _name_similarity(left: str, right: str) -> float:
    return difflib.SequenceMatcher(None, left.lower(), right.lower()).ratio()


def _greedy_one_to_one(candidates: list[RenameCandidate]) -> list[RenameCandidate]:
    chosen: list[RenameCandidate] = []
    used_before: set[tuple[str | None, str]] = set()
    used_after: set[tuple[str | None, str]] = set()
    for candidate in sorted(
        candidates, key=lambda c: (-c.confidence, c.scope or "", c.before, c.after)
    ):
        before_key = (candidate.scope, candidate.before)
        after_key = (candidate.scope, candidate.after)
        if before_key in used_before or after_key in used_after:
            continue
        used_before.add(before_key)
        used_after.add(after_key)
        chosen.append(candidate)
    return chosen


# ---------------------------------------------------------------------------
# Rename heuristics


def _label_renames(
    before: SchemaSummary,
    after: SchemaSummary,
    removed_labels: list[str],
    added_labels: list[str],
    min_confidence: float,
) -> list[RenameCandidate]:
    before_props = _label_props(before)
    after_props = _label_props(after)
    before_patterns = set(_pattern_counts(before))
    after_patterns = set(_pattern_counts(after))
    candidates: list[RenameCandidate] = []
    for old in removed_labels:
        for new in added_labels:
            props_j = _jaccard(before_props.get(old, {}), after_props.get(new, {}))

            def sub(label: str, old: str = old, new: str = new) -> str:
                return new if label == old else label

            moved = {
                (sub(s), t, sub(e)) for s, t, e in before_patterns if old in {s, e}
            }
            current = {(s, t, e) for s, t, e in after_patterns if new in {s, e}}
            pattern_j = _jaccard(moved, current, empty=props_j)
            score = 0.5 * props_j + 0.5 * pattern_j
            if score >= min_confidence and (props_j > 0 or pattern_j > 0):
                candidates.append(
                    RenameCandidate(
                        kind="label",
                        before=old,
                        after=new,
                        confidence=score,
                        evidence={
                            "property_jaccard": round(props_j, 4),
                            "pattern_jaccard_after_substitution": round(pattern_j, 4),
                        },
                    )
                )
    return _greedy_one_to_one(candidates)


def _label_splits(
    before: SchemaSummary,
    after: SchemaSummary,
    unmatched_added_labels: list[str],
    min_confidence: float,
) -> list[RenameCandidate]:
    before_props = _label_props(before)
    after_props = _label_props(after)
    before_counts = _pattern_counts(before)
    after_counts = _pattern_counts(after)
    retained = sorted(before.labels & after.labels)
    candidates: list[RenameCandidate] = []
    for new in unmatched_added_labels:
        new_patterns = [(s, t, e) for s, t, e in after_counts if new in {s, e}]
        best: RenameCandidate | None = None
        for source in retained:
            props_j = _jaccard(after_props.get(new, {}), before_props.get(source, {}), empty=0.0)
            mapped = {
                (source if s == new else s, t, source if e == new else e)
                for s, t, e in new_patterns
            }
            source_patterns = {key for key in before_counts if source in {key[0], key[2]}}
            containment = (len(mapped & source_patterns) / len(mapped)) if mapped else props_j
            score = 0.6 * props_j + 0.4 * containment
            decreased = sorted(
                pattern_text(*key)
                for key in source_patterns
                if before_counts.get(key) is not None
                and after_counts.get(key) is not None
                and int(after_counts[key] or 0) < int(before_counts[key] or 0)
            )
            if score < min_confidence:
                continue
            candidate = RenameCandidate(
                kind="label_split",
                before=source,
                after=new,
                confidence=score,
                evidence={
                    "property_jaccard": round(props_j, 4),
                    "pattern_containment": round(containment, 4),
                    "source_patterns_with_decreased_counts": decreased,
                },
            )
            if best is None or candidate.confidence > best.confidence:
                best = candidate
        if best is not None:
            candidates.append(best)
    return candidates


def _relationship_type_renames(
    before: SchemaSummary,
    after: SchemaSummary,
    removed_types: list[str],
    added_types: list[str],
    label_map: Mapping[str, str],
    min_confidence: float,
) -> list[RenameCandidate]:
    before_counts = _pattern_counts(before)
    after_counts = _pattern_counts(after)
    before_props = _rel_props(before)
    after_props = _rel_props(after)
    candidates: list[RenameCandidate] = []
    for old in removed_types:
        old_endpoints = {
            (label_map.get(s, s), label_map.get(e, e)) for s, t, e in before_counts if t == old
        }
        old_total = sum(int(c or 0) for (s, t, e), c in before_counts.items() if t == old)
        for new in added_types:
            new_endpoints = {(s, e) for s, t, e in after_counts if t == new}
            new_total = sum(int(c or 0) for (s, t, e), c in after_counts.items() if t == new)
            endpoint_j = _jaccard(old_endpoints, new_endpoints, empty=0.0)
            if endpoint_j <= 0:
                continue
            props_j = _jaccard(before_props.get(old, {}), after_props.get(new, {}))
            if old_total > 0 and new_total > 0:
                count_sim = min(old_total, new_total) / max(old_total, new_total)
            else:
                count_sim = 0.5
            score = 0.6 * endpoint_j + 0.3 * props_j + 0.1 * count_sim
            if score < min_confidence:
                continue
            candidates.append(
                RenameCandidate(
                    kind="relationship_type",
                    before=old,
                    after=new,
                    confidence=score,
                    evidence={
                        "endpoint_jaccard": round(endpoint_j, 4),
                        "property_jaccard": round(props_j, 4),
                        "count_similarity": round(count_sim, 4),
                        "before_count": old_total,
                        "after_count": new_total,
                    },
                )
            )
    return _greedy_one_to_one(candidates)


def _property_renames(
    *,
    kind: str,
    before_props: Mapping[str, Mapping[str, str]],
    after_props: Mapping[str, Mapping[str, str]],
    owner_pairs: list[tuple[str, str]],
    before_categorical: Mapping[str, list[str]],
    after_categorical: Mapping[str, list[str]],
    min_confidence: float,
) -> list[RenameCandidate]:
    candidates: list[RenameCandidate] = []
    for old_owner, new_owner in owner_pairs:
        old_props = before_props.get(old_owner, {})
        new_props = after_props.get(new_owner, {})
        removed = {p: t for p, t in old_props.items() if p not in new_props}
        added = {p: t for p, t in new_props.items() if p not in old_props}
        if not removed or not added:
            continue
        for old_prop, old_type in removed.items():
            for new_prop, new_type in added.items():
                if not _types_compatible(old_type, new_type):
                    continue
                same_type_removed = sum(
                    1 for t in removed.values() if _types_compatible(t, old_type)
                )
                same_type_added = sum(1 for t in added.values() if _types_compatible(t, new_type))
                unique = same_type_removed == 1 and same_type_added == 1
                name_sim = _name_similarity(old_prop, new_prop)
                old_values = list(before_categorical.get(f"{old_owner}.{old_prop}", []) or [])
                new_values = list(after_categorical.get(f"{new_owner}.{new_prop}", []) or [])
                same_values = bool(old_values) and sorted(old_values) == sorted(new_values)
                score = 0.5 + (0.3 if unique else 0.0) + 0.1 * name_sim + (0.1 if same_values else 0.0)
                if score < min_confidence:
                    continue
                candidates.append(
                    RenameCandidate(
                        kind=kind,
                        before=old_prop,
                        after=new_prop,
                        confidence=min(score, 1.0),
                        scope=old_owner,
                        evidence={
                            "owner_before": old_owner,
                            "owner_after": new_owner,
                            "value_type": new_type,
                            "unique_type_compatible_pair": unique,
                            "name_similarity": round(name_sim, 4),
                            "identical_categorical_values": same_values,
                        },
                    )
                )
    return _greedy_one_to_one(candidates)


# ---------------------------------------------------------------------------
# Diff


def diff_schemas(
    before: SchemaSummary,
    after: SchemaSummary,
    *,
    count_change_threshold: float = 0.0,
    rename_min_confidence: float = 0.6,
    prune_ghosts: bool = True,
) -> SchemaDiff:
    """Diff two schema snapshots and propose renames.

    ``count_change_threshold`` is a relative threshold on relationship-pattern
    counts: changes with ``|after-before|/before`` at or below it are ignored.
    The default (0.0) reports every count change.
    """

    pruned_before: list[str] = []
    pruned_after: list[str] = []
    if prune_ghosts:
        before, pruned_before = prune_ghost_schema_entries(before)
        after, pruned_after = prune_ghost_schema_entries(after)

    before_labels, after_labels = before.labels, after.labels
    added_labels = sorted(after_labels - before_labels)
    removed_labels = sorted(before_labels - after_labels)

    before_types = observed_relationship_types(before)
    after_types = observed_relationship_types(after)
    added_types = sorted(after_types - before_types)
    removed_types = sorted(before_types - after_types)

    before_counts = _pattern_counts(before)
    after_counts = _pattern_counts(after)
    added_patterns = sorted(pattern_text(*key) for key in set(after_counts) - set(before_counts))
    removed_patterns = sorted(pattern_text(*key) for key in set(before_counts) - set(after_counts))

    count_changes: list[dict[str, Any]] = []
    for key in sorted(set(before_counts) & set(after_counts)):
        old_count, new_count = before_counts[key], after_counts[key]
        if old_count is None or new_count is None or old_count == new_count:
            continue
        relative = (new_count - old_count) / old_count if old_count else float("inf")
        if abs(relative) <= count_change_threshold:
            continue
        count_changes.append(
            {
                "pattern": pattern_text(*key),
                "start_label": key[0],
                "type": key[1],
                "end_label": key[2],
                "before": old_count,
                "after": new_count,
                "delta": new_count - old_count,
                "relative_change": round(relative, 6) if old_count else None,
            }
        )

    before_label_props, after_label_props = _label_props(before), _label_props(after)
    added_node_props: list[str] = []
    removed_node_props: list[str] = []
    node_type_changes: list[dict[str, Any]] = []
    for label in sorted(set(before_label_props) | set(after_label_props)):
        old = before_label_props.get(label, {})
        new = after_label_props.get(label, {})
        added_node_props.extend(f"{label}.{p}" for p in sorted(set(new) - set(old)))
        removed_node_props.extend(f"{label}.{p}" for p in sorted(set(old) - set(new)))
        for prop in sorted(set(old) & set(new)):
            if old[prop].strip().upper() != new[prop].strip().upper():
                node_type_changes.append(
                    {"key": f"{label}.{prop}", "before": old[prop], "after": new[prop]}
                )

    before_rel_props, after_rel_props = _rel_props(before), _rel_props(after)
    added_rel_props: list[str] = []
    removed_rel_props: list[str] = []
    rel_type_changes: list[dict[str, Any]] = []
    for rel_type in sorted(set(before_rel_props) | set(after_rel_props)):
        old = before_rel_props.get(rel_type, {})
        new = after_rel_props.get(rel_type, {})
        added_rel_props.extend(f"{rel_type}.{p}" for p in sorted(set(new) - set(old)))
        removed_rel_props.extend(f"{rel_type}.{p}" for p in sorted(set(old) - set(new)))
        for prop in sorted(set(old) & set(new)):
            if old[prop].strip().upper() != new[prop].strip().upper():
                rel_type_changes.append(
                    {"key": f"{rel_type}.{prop}", "before": old[prop], "after": new[prop]}
                )

    categorical_changes: list[dict[str, Any]] = []
    before_cat = before.categorical_properties or {}
    after_cat = after.categorical_properties or {}
    for key in sorted(set(before_cat) | set(after_cat)):
        old_values = {str(v) for v in before_cat.get(key, []) or []}
        new_values = {str(v) for v in after_cat.get(key, []) or []}
        if key not in before_cat:
            change = "added_property"
        elif key not in after_cat:
            change = "removed_property"
        elif old_values != new_values:
            change = "values_changed"
        else:
            continue
        categorical_changes.append(
            {
                "key": key,
                "change": change,
                "added_values": sorted(new_values - old_values),
                "removed_values": sorted(old_values - new_values),
            }
        )

    renames: list[RenameCandidate] = []
    label_renames = _label_renames(before, after, removed_labels, added_labels, rename_min_confidence)
    renames.extend(label_renames)
    label_map = {c.before: c.after for c in label_renames}
    renamed_new_labels = {c.after for c in label_renames}
    renames.extend(
        _label_splits(
            before,
            after,
            [label for label in added_labels if label not in renamed_new_labels],
            rename_min_confidence,
        )
    )
    rel_renames = _relationship_type_renames(
        before, after, removed_types, added_types, label_map, rename_min_confidence
    )
    renames.extend(rel_renames)

    shared_labels = sorted(before_labels & after_labels)
    label_pairs = [(label, label) for label in shared_labels] + sorted(label_map.items())
    renames.extend(
        _property_renames(
            kind="node_property",
            before_props=before_label_props,
            after_props=after_label_props,
            owner_pairs=label_pairs,
            before_categorical=before_cat,
            after_categorical=after_cat,
            min_confidence=rename_min_confidence,
        )
    )
    rel_map = {c.before: c.after for c in rel_renames}
    shared_types = sorted(before_types & after_types)
    type_pairs = [(t, t) for t in shared_types] + sorted(rel_map.items())
    renames.extend(
        _property_renames(
            kind="relationship_property",
            before_props=before_rel_props,
            after_props=after_rel_props,
            owner_pairs=type_pairs,
            before_categorical={},
            after_categorical={},
            min_confidence=rename_min_confidence,
        )
    )

    pruned: dict[str, list[str]] = {}
    if pruned_before:
        pruned["before"] = pruned_before
    if pruned_after:
        pruned["after"] = pruned_after

    return SchemaDiff(
        before_graph=before.graph_name,
        after_graph=after.graph_name,
        added_labels=added_labels,
        removed_labels=removed_labels,
        added_relationship_types=added_types,
        removed_relationship_types=removed_types,
        added_relationship_patterns=added_patterns,
        removed_relationship_patterns=removed_patterns,
        added_node_properties=added_node_props,
        removed_node_properties=removed_node_props,
        node_property_type_changes=node_type_changes,
        added_relationship_properties=added_rel_props,
        removed_relationship_properties=removed_rel_props,
        relationship_property_type_changes=rel_type_changes,
        categorical_changes=categorical_changes,
        relationship_count_changes=count_changes,
        rename_candidates=renames,
        pruned_ghost_entries=pruned,
    )


def diff_schema_files(
    before_path: str | Path,
    after_path: str | Path,
    **kwargs: Any,
) -> SchemaDiff:
    return diff_schemas(load_schema(before_path), load_schema(after_path), **kwargs)


# ---------------------------------------------------------------------------
# Expected-diff verification (used to confirm a migration did what its
# metadata claims before any benchmark numbers are computed).

_SUBSET_KEYS = (
    "added_labels",
    "removed_labels",
    "added_relationship_types",
    "removed_relationship_types",
    "added_relationship_patterns",
    "removed_relationship_patterns",
    "added_node_properties",
    "removed_node_properties",
    "added_relationship_properties",
    "removed_relationship_properties",
)
EXPECTED_DIFF_KEYS = frozenset(
    (
        *_SUBSET_KEYS,
        "retained_labels",
        "retained_relationship_types",
        "renames",
        "count_changes",
        "no_structural_changes",
    )
)


def check_expected_diff(diff: SchemaDiff, expected: Mapping[str, Any] | None) -> list[str]:
    """Return human-readable mismatches between a diff and migration metadata.

    Every listed item must be present in the diff (subset semantics, because
    data-dependent side effects such as extra patterns are allowed).
    """

    if not expected:
        return []
    problems: list[str] = []
    unknown = sorted(set(expected) - EXPECTED_DIFF_KEYS)
    if unknown:
        problems.append("unknown expected_schema_diff keys: " + ", ".join(unknown))
    for key in _SUBSET_KEYS:
        wanted = [str(item) for item in expected.get(key, []) or []]
        actual = set(getattr(diff, key))
        missing = [item for item in wanted if item not in actual]
        if missing:
            problems.append(f"{key} missing: {', '.join(missing)}")
    for label in expected.get("retained_labels", []) or []:
        if label in diff.removed_labels or label in diff.added_labels:
            problems.append(f"label {label} was expected to be retained")
    for rel_type in expected.get("retained_relationship_types", []) or []:
        if rel_type in diff.removed_relationship_types or rel_type in diff.added_relationship_types:
            problems.append(f"relationship type {rel_type} was expected to be retained")
    for rename in expected.get("renames", []) or []:
        kind = str(rename.get("kind"))
        found = any(
            c.kind == kind
            and c.before == str(rename.get("before"))
            and c.after == str(rename.get("after"))
            and (rename.get("scope") is None or c.scope == rename.get("scope"))
            for c in diff.rename_candidates
        )
        if not found:
            problems.append(
                f"expected {kind} rename {rename.get('before')} -> {rename.get('after')} not detected"
            )
    for change in expected.get("count_changes", []) or []:
        rel_type = str(change.get("type"))
        direction = str(change.get("direction", "any"))
        matches = [c for c in diff.relationship_count_changes if c["type"] == rel_type]
        if direction == "decrease":
            matches = [c for c in matches if c["delta"] < 0]
        elif direction == "increase":
            matches = [c for c in matches if c["delta"] > 0]
        if not matches:
            problems.append(f"expected {direction} count change for {rel_type} not observed")
    if expected.get("no_structural_changes") and diff.has_structural_changes():
        problems.append("expected no structural schema changes, but the diff has some")
    return problems
