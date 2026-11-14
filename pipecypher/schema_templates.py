from __future__ import annotations

import re
from typing import Any

from .models import RelationshipPattern, SchemaSummary, TemplateCandidate


SAFE_SLOT_PROPERTY_NAMES = (
    "jurisdiction",
    "jurisdiction_description",
    "sourceID",
    "status",
    "type",
    "company_type",
    "service_provider",
    "countries",
    "country",
    "country_codes",
    "valid_until",
)
UNSAFE_SLOT_PROPERTY_PARTS = (
    "address",
    "comment",
    "note",
    "original",
    "description_text",
)
IDENTITY_PROPERTY_PREFERENCES = (
    "node_id",
    "id",
    "name",
    "title",
    "accountId",
    "caseId",
    "customerId",
    "personId",
    "companyId",
    "entity_number",
    "company_number",
)
SCHEMA_TEMPLATE_KIND = "schema_template_kind"


def schema_derived_templates(
    schema: SchemaSummary,
    category: str,
    *,
    max_templates: int = 48,
) -> list[TemplateCandidate]:
    """Create deterministic templates from the observed property-graph schema.

    These templates are intentionally plain and audit-friendly. They are a
    backstop for arbitrary enterprise onboarding when seed or LLM-generated
    templates do not provide enough productive, non-duplicate question families
    for categories such as top-k and anti-join.
    """

    if category not in {"complex_aggregation", "ranking_topk", "negation_difference"}:
        return []

    rels = _rank_relationships(schema.relationships)
    templates: list[TemplateCandidate] = []
    for rel in rels:
        if category == "complex_aggregation":
            templates.extend(_aggregation_templates_for_relationship(schema, rel))
        elif category == "ranking_topk":
            templates.extend(_ranking_templates_for_relationship(schema, rel))
        else:
            templates.extend(_negation_templates_for_relationship(schema, rel))
        if len(templates) >= max_templates:
            break
    return _dedupe_templates(templates)[:max_templates]


def reverse_cypher_for_schema_template(template: TemplateCandidate, limit: int = 50) -> str | None:
    meta = template.metadata
    kind = meta.get(SCHEMA_TEMPLATE_KIND)
    if not kind or not template.slots:
        return None

    start = str(meta["start_label"])
    end = str(meta["end_label"])
    rel_type = str(meta["relationship_type"])
    prop = str(meta["slot_property"])
    slot = str(meta["slot"])

    if kind == "negation_context_outgoing_scoped":
        missing_rel = str(meta["missing_relationship_type"])
        missing_end = str(meta["missing_end_label"])
        return (
            f"MATCH (a:{start})-[:{rel_type}]->(b:{end}) "
            f"WHERE a.{prop} IS NOT NULL AND NOT (b)-[:{missing_rel}]->(:{missing_end}) "
            f"RETURN DISTINCT a.{prop} AS {slot} LIMIT {limit}"
        )
    if kind == "negation_context_incoming_scoped":
        missing_rel = str(meta["missing_relationship_type"])
        missing_start = str(meta["missing_start_label"])
        return (
            f"MATCH (a:{start})-[:{rel_type}]->(b:{end}) "
            f"WHERE a.{prop} IS NOT NULL AND NOT (:{missing_start})-[:{missing_rel}]->(b) "
            f"RETURN DISTINCT a.{prop} AS {slot} LIMIT {limit}"
        )
    if kind == "topk_outgoing_scoped":
        return (
            f"MATCH (s:{start})-[:{rel_type}]->(:{end}) "
            f"WHERE s.{prop} IS NOT NULL "
            f"WITH s.{prop} AS {slot}, COUNT(*) AS support "
            "WHERE support > 0 "
            f"RETURN DISTINCT {slot} LIMIT {limit}"
        )
    if kind == "topk_incoming_scoped":
        return (
            f"MATCH (:{start})-[:{rel_type}]->(e:{end}) "
            f"WHERE e.{prop} IS NOT NULL "
            f"WITH e.{prop} AS {slot}, COUNT(*) AS support "
            "WHERE support > 0 "
            f"RETURN DISTINCT {slot} LIMIT {limit}"
        )
    if kind == "negation_outgoing_scoped":
        return (
            f"MATCH (s:{start}) "
            f"WHERE s.{prop} IS NOT NULL AND NOT (s)-[:{rel_type}]->(:{end}) "
            f"RETURN DISTINCT s.{prop} AS {slot} LIMIT {limit}"
        )
    if kind == "negation_incoming_scoped":
        return (
            f"MATCH (e:{end}) "
            f"WHERE e.{prop} IS NOT NULL AND NOT (:{start})-[:{rel_type}]->(e) "
            f"RETURN DISTINCT e.{prop} AS {slot} LIMIT {limit}"
        )
    if kind == "count_outgoing_scoped":
        return (
            f"MATCH (s:{start})-[:{rel_type}]->(e:{end}) "
            f"WHERE s.{prop} IS NOT NULL "
            f"WITH s.{prop} AS {slot}, COUNT(DISTINCT e) AS support "
            "WHERE support > 0 "
            f"RETURN DISTINCT {slot} LIMIT {limit}"
        )
    if kind == "count_incoming_scoped":
        return (
            f"MATCH (s:{start})-[:{rel_type}]->(e:{end}) "
            f"WHERE e.{prop} IS NOT NULL "
            f"WITH e.{prop} AS {slot}, COUNT(DISTINCT s) AS support "
            "WHERE support > 0 "
            f"RETURN DISTINCT {slot} LIMIT {limit}"
        )
    return None


def cypher_for_schema_template(
    template: TemplateCandidate,
    schema: SchemaSummary,
    *,
    limit: int = 50,
    bindings: dict[str, object] | None = None,
) -> str | None:
    meta = template.metadata
    kind = meta.get(SCHEMA_TEMPLATE_KIND)
    if not kind:
        return None

    start = str(meta["start_label"])
    end = str(meta["end_label"])
    rel_type = str(meta["relationship_type"])
    slot = str(meta.get("slot") or "value")
    prop = str(meta.get("slot_property") or "")
    value = _cypher_literal((bindings or {}).get(slot, slot))

    if kind == "topk_outgoing":
        return (
            f"MATCH (s:{start})-[:{rel_type}]->(e:{end}) "
            "WITH s, COUNT(DISTINCT e) AS relatedCount "
            f"RETURN DISTINCT {_projection(schema, start, 's', 'Source')}, relatedCount "
            "ORDER BY relatedCount DESC LIMIT 10"
        )
    if kind == "topk_incoming":
        return (
            f"MATCH (s:{start})-[:{rel_type}]->(e:{end}) "
            "WITH e, COUNT(DISTINCT s) AS relatedCount "
            f"RETURN DISTINCT {_projection(schema, end, 'e', 'Target')}, relatedCount "
            "ORDER BY relatedCount DESC LIMIT 10"
        )
    if kind == "topk_outgoing_scoped":
        return (
            f"MATCH (s:{start} {{{prop}: {value}}})-[:{rel_type}]->(e:{end}) "
            "WITH s, COUNT(DISTINCT e) AS relatedCount "
            f"RETURN DISTINCT {_projection(schema, start, 's', 'Source')}, relatedCount "
            "ORDER BY relatedCount DESC LIMIT 10"
        )
    if kind == "topk_incoming_scoped":
        return (
            f"MATCH (s:{start})-[:{rel_type}]->(e:{end} {{{prop}: {value}}}) "
            "WITH e, COUNT(DISTINCT s) AS relatedCount "
            f"RETURN DISTINCT {_projection(schema, end, 'e', 'Target')}, relatedCount "
            "ORDER BY relatedCount DESC LIMIT 10"
        )
    if kind == "negation_outgoing":
        return (
            f"MATCH (s:{start}) "
            f"WHERE NOT (s)-[:{rel_type}]->(:{end}) "
            f"RETURN DISTINCT {_projection(schema, start, 's', 'Source')} LIMIT {limit}"
        )
    if kind == "negation_incoming":
        return (
            f"MATCH (e:{end}) "
            f"WHERE NOT (:{start})-[:{rel_type}]->(e) "
            f"RETURN DISTINCT {_projection(schema, end, 'e', 'Target')} LIMIT {limit}"
        )
    if kind == "negation_outgoing_scoped":
        return (
            f"MATCH (s:{start} {{{prop}: {value}}}) "
            f"WHERE NOT (s)-[:{rel_type}]->(:{end}) "
            f"RETURN DISTINCT {_projection(schema, start, 's', 'Source')} LIMIT {limit}"
        )
    if kind == "negation_incoming_scoped":
        return (
            f"MATCH (e:{end} {{{prop}: {value}}}) "
            f"WHERE NOT (:{start})-[:{rel_type}]->(e) "
            f"RETURN DISTINCT {_projection(schema, end, 'e', 'Target')} LIMIT {limit}"
        )
    if kind == "negation_context_outgoing_scoped":
        missing_rel = str(meta["missing_relationship_type"])
        missing_end = str(meta["missing_end_label"])
        return (
            f"MATCH (a:{start} {{{prop}: {value}}})-[:{rel_type}]->(b:{end}) "
            f"WHERE NOT (b)-[:{missing_rel}]->(:{missing_end}) "
            f"RETURN DISTINCT {_projection(schema, end, 'b', 'Target')} LIMIT {limit}"
        )
    if kind == "negation_context_incoming_scoped":
        missing_rel = str(meta["missing_relationship_type"])
        missing_start = str(meta["missing_start_label"])
        return (
            f"MATCH (a:{start} {{{prop}: {value}}})-[:{rel_type}]->(b:{end}) "
            f"WHERE NOT (:{missing_start})-[:{missing_rel}]->(b) "
            f"RETURN DISTINCT {_projection(schema, end, 'b', 'Target')} LIMIT {limit}"
        )
    if kind == "count_outgoing":
        return (
            f"MATCH (s:{start})-[:{rel_type}]->(e:{end}) "
            f"RETURN DISTINCT COUNT(DISTINCT e) AS {_alias_part(end)}Count"
        )
    if kind == "count_incoming":
        return (
            f"MATCH (s:{start})-[:{rel_type}]->(e:{end}) "
            f"RETURN DISTINCT COUNT(DISTINCT s) AS {_alias_part(start)}Count"
        )
    if kind == "count_outgoing_scoped":
        return (
            f"MATCH (s:{start} {{{prop}: {value}}})-[:{rel_type}]->(e:{end}) "
            f"RETURN DISTINCT COUNT(DISTINCT e) AS {_alias_part(end)}Count"
        )
    if kind == "count_incoming_scoped":
        return (
            f"MATCH (s:{start})-[:{rel_type}]->(e:{end} {{{prop}: {value}}}) "
            f"RETURN DISTINCT COUNT(DISTINCT s) AS {_alias_part(start)}Count"
        )
    return None


def _aggregation_templates_for_relationship(
    schema: SchemaSummary,
    rel: RelationshipPattern,
) -> list[TemplateCandidate]:
    start_text = _label_phrase(rel.start_label)
    end_text = _label_phrase(rel.end_label)
    rel_text = rel.type
    templates = [
        TemplateCandidate(
            category="complex_aggregation",
            template=(
                f"How many distinct {end_text} records are linked from {start_text} "
                f"records through :{rel_text}?"
            ),
            rationale="Schema-derived relationship-count aggregation.",
            metadata=_metadata("count_outgoing", rel),
        ),
        TemplateCandidate(
            category="complex_aggregation",
            template=(
                f"How many distinct {start_text} records link to {end_text} "
                f"records through :{rel_text}?"
            ),
            rationale="Schema-derived inverse relationship-count aggregation.",
            metadata=_metadata("count_incoming", rel),
        ),
    ]
    for prop in _slot_properties(schema, rel.start_label)[:3]:
        templates.append(
            TemplateCandidate(
                category="complex_aggregation",
                template=(
                    f"How many distinct {end_text} records are linked from {start_text} "
                    f"records with {prop} '{{startValue}}' through :{rel_text}?"
                ),
                slots={"startValue": f"{rel.start_label}.{prop}"},
                rationale="Schema-derived scoped relationship-count aggregation.",
                metadata=_metadata(
                    "count_outgoing_scoped",
                    rel,
                    slot="startValue",
                    slot_property=prop,
                ),
            )
        )
    for prop in _slot_properties(schema, rel.end_label)[:2]:
        templates.append(
            TemplateCandidate(
                category="complex_aggregation",
                template=(
                    f"How many distinct {start_text} records link to {end_text} "
                    f"records with {prop} '{{targetValue}}' through :{rel_text}?"
                ),
                slots={"targetValue": f"{rel.end_label}.{prop}"},
                rationale="Schema-derived scoped inverse relationship-count aggregation.",
                metadata=_metadata(
                    "count_incoming_scoped",
                    rel,
                    slot="targetValue",
                    slot_property=prop,
                ),
            )
        )
    return templates


def _ranking_templates_for_relationship(
    schema: SchemaSummary,
    rel: RelationshipPattern,
) -> list[TemplateCandidate]:
    start_text = _label_phrase(rel.start_label)
    end_text = _label_phrase(rel.end_label)
    rel_text = rel.type
    templates = [
        TemplateCandidate(
            category="ranking_topk",
            template=(
                f"Which {start_text} records are linked to the most {end_text} "
                f"records through :{rel_text}?"
            ),
            rationale="Schema-derived ranking over outgoing relationship counts.",
            metadata=_metadata("topk_outgoing", rel),
        ),
        TemplateCandidate(
            category="ranking_topk",
            template=(
                f"Which {end_text} records are linked from the most {start_text} "
                f"records through :{rel_text}?"
            ),
            rationale="Schema-derived ranking over incoming relationship counts.",
            metadata=_metadata("topk_incoming", rel),
        ),
    ]
    for prop in _slot_properties(schema, rel.start_label)[:3]:
        templates.append(
            TemplateCandidate(
                category="ranking_topk",
                template=(
                    f"Among {start_text} records with {prop} '{{startValue}}', "
                    f"which records are linked to the most {end_text} records through :{rel_text}?"
                ),
                slots={"startValue": f"{rel.start_label}.{prop}"},
                rationale="Schema-derived scoped top-k query with outcome-aware slot grounding.",
                metadata=_metadata(
                    "topk_outgoing_scoped",
                    rel,
                    slot="startValue",
                    slot_property=prop,
                ),
            )
        )
    for prop in _slot_properties(schema, rel.end_label)[:2]:
        templates.append(
            TemplateCandidate(
                category="ranking_topk",
                template=(
                    f"Among {end_text} records with {prop} '{{targetValue}}', "
                    f"which records are linked from the most {start_text} records through :{rel_text}?"
                ),
                slots={"targetValue": f"{rel.end_label}.{prop}"},
                rationale="Schema-derived scoped top-k query with outcome-aware slot grounding.",
                metadata=_metadata(
                    "topk_incoming_scoped",
                    rel,
                    slot="targetValue",
                    slot_property=prop,
                ),
            )
        )
    return templates


def _negation_templates_for_relationship(
    schema: SchemaSummary,
    rel: RelationshipPattern,
) -> list[TemplateCandidate]:
    start_text = _label_phrase(rel.start_label)
    end_text = _label_phrase(rel.end_label)
    rel_text = rel.type
    templates = [
        TemplateCandidate(
            category="negation_difference",
            template=(
                f"Which {start_text} records have no outgoing :{rel_text} "
                f"relationship to {end_text} records?"
            ),
            rationale="Schema-derived anti-join over a missing outgoing relationship.",
            metadata=_metadata("negation_outgoing", rel),
        ),
        TemplateCandidate(
            category="negation_difference",
            template=(
                f"Which {end_text} records are not linked from any {start_text} "
                f"record through :{rel_text}?"
            ),
            rationale="Schema-derived anti-join over a missing incoming relationship.",
            metadata=_metadata("negation_incoming", rel),
        ),
    ]
    for prop in _slot_properties(schema, rel.start_label)[:3]:
        templates.append(
            TemplateCandidate(
                category="negation_difference",
                template=(
                    f"Which {start_text} records with {prop} '{{startValue}}' "
                    f"have no outgoing :{rel_text} relationship to {end_text} records?"
                ),
                slots={"startValue": f"{rel.start_label}.{prop}"},
                rationale="Schema-derived scoped anti-join with outcome-aware slot grounding.",
                metadata=_metadata(
                    "negation_outgoing_scoped",
                    rel,
                    slot="startValue",
                    slot_property=prop,
                ),
            )
        )
    for prop in _slot_properties(schema, rel.end_label)[:2]:
        templates.append(
            TemplateCandidate(
                category="negation_difference",
                template=(
                    f"Which {end_text} records with {prop} '{{targetValue}}' "
                    f"are not linked from any {start_text} record through :{rel_text}?"
                ),
                slots={"targetValue": f"{rel.end_label}.{prop}"},
                rationale="Schema-derived scoped anti-join with outcome-aware slot grounding.",
                metadata=_metadata(
                    "negation_incoming_scoped",
                    rel,
                    slot="targetValue",
                    slot_property=prop,
                ),
            )
        )
    for prop in _slot_properties(schema, rel.start_label)[:2]:
        templates.extend(_contextual_negation_templates(schema, rel, prop))
    return templates


def _contextual_negation_templates(
    schema: SchemaSummary,
    context_rel: RelationshipPattern,
    slot_property: str,
) -> list[TemplateCandidate]:
    """Create two-hop anti-joins scoped by an anchor value.

    These templates are useful for sparse enterprise schemas where many
    unscoped anti-joins are either empty or duplicate. The reverse query uses
    the same anti-join predicate as the final query, so sampled slot values are
    outcome-aware rather than broad label/property lookups.
    """

    if not _safe_identifier(slot_property):
        return []
    anchor_text = _label_phrase(context_rel.start_label)
    target_text = _label_phrase(context_rel.end_label)
    templates: list[TemplateCandidate] = []
    outgoing_missing = [
        rel
        for rel in _rank_relationships(schema.relationships)
        if rel.start_label == context_rel.end_label
        and (rel.type, rel.end_label) != (context_rel.type, context_rel.start_label)
    ][:2]
    incoming_missing = [
        rel
        for rel in _rank_relationships(schema.relationships)
        if rel.end_label == context_rel.end_label
        and (rel.type, rel.start_label) != (context_rel.type, context_rel.start_label)
    ][:2]
    for missing in outgoing_missing:
        missing_text = _label_phrase(missing.end_label)
        templates.append(
            TemplateCandidate(
                category="negation_difference",
                template=(
                    f"Which {target_text} records linked from {anchor_text} records with "
                    f"{slot_property} '{{anchorValue}}' through :{context_rel.type} have no "
                    f"outgoing :{missing.type} relationship to {missing_text} records?"
                ),
                slots={"anchorValue": f"{context_rel.start_label}.{slot_property}"},
                rationale="Schema-derived context-scoped anti-join with outcome-aware grounding.",
                metadata=_metadata(
                    "negation_context_outgoing_scoped",
                    context_rel,
                    slot="anchorValue",
                    slot_property=slot_property,
                    missing_relationship_type=missing.type,
                    missing_end_label=missing.end_label,
                ),
            )
        )
    for missing in incoming_missing:
        missing_text = _label_phrase(missing.start_label)
        templates.append(
            TemplateCandidate(
                category="negation_difference",
                template=(
                    f"Which {target_text} records linked from {anchor_text} records with "
                    f"{slot_property} '{{anchorValue}}' through :{context_rel.type} are not "
                    f"linked from any {missing_text} record through :{missing.type}?"
                ),
                slots={"anchorValue": f"{context_rel.start_label}.{slot_property}"},
                rationale="Schema-derived context-scoped inverse anti-join with outcome-aware grounding.",
                metadata=_metadata(
                    "negation_context_incoming_scoped",
                    context_rel,
                    slot="anchorValue",
                    slot_property=slot_property,
                    missing_relationship_type=missing.type,
                    missing_start_label=missing.start_label,
                ),
            )
        )
    return templates


def _rank_relationships(relationships: list[RelationshipPattern]) -> list[RelationshipPattern]:
    deduped: dict[tuple[str, str, str], RelationshipPattern] = {}
    for rel in relationships:
        if not (_safe_identifier(rel.start_label) and _safe_identifier(rel.type) and _safe_identifier(rel.end_label)):
            continue
        key = (rel.start_label, rel.type, rel.end_label)
        if key not in deduped or (rel.count or 0) > (deduped[key].count or 0):
            deduped[key] = rel
    return sorted(deduped.values(), key=lambda rel: (-(rel.count or 0), rel.start_label, rel.type, rel.end_label))


def _slot_properties(schema: SchemaSummary, label: str) -> list[str]:
    available = schema.properties_for_label(label)
    categorical = [
        key.split(".", 1)[1]
        for key, values in schema.categorical_properties.items()
        if key.startswith(f"{label}.") and values
    ]
    preferred = [prop for prop in SAFE_SLOT_PROPERTY_NAMES if prop in available]
    identity = [prop for prop in IDENTITY_PROPERTY_PREFERENCES if prop in available]
    candidates = [*categorical, *preferred, *identity]
    selected: list[str] = []
    for prop in candidates:
        if prop in selected or prop not in available or not _safe_identifier(prop):
            continue
        prop_lower = prop.lower()
        if any(part in prop_lower for part in UNSAFE_SLOT_PROPERTY_PARTS):
            continue
        selected.append(prop)
    return selected


def _projection(schema: SchemaSummary, label: str, var: str, prefix: str) -> str:
    props = _identity_properties(schema, label)
    if not props:
        return f"{var} AS {prefix}Record"
    return ", ".join(f"{var}.{prop} AS {prefix}{_alias_part(prop)}" for prop in props)


def _identity_properties(schema: SchemaSummary, label: str) -> list[str]:
    available = schema.properties_for_label(label)
    selected = [prop for prop in IDENTITY_PROPERTY_PREFERENCES if prop in available and _safe_identifier(prop)]
    if selected:
        return selected[:3]
    return sorted(prop for prop in available if _safe_identifier(prop))[:2]


def _metadata(kind: str, rel: RelationshipPattern, **extra: Any) -> dict[str, Any]:
    metadata = {
        SCHEMA_TEMPLATE_KIND: kind,
        "start_label": rel.start_label,
        "end_label": rel.end_label,
        "relationship_type": rel.type,
    }
    metadata.update(extra)
    return metadata


def _label_phrase(label: str) -> str:
    words = re.sub(r"(?<!^)([A-Z])", r" \1", label).replace("_", " ").strip().lower()
    return words or label.lower()


def _alias_part(prop: str) -> str:
    parts = re.split(r"[^A-Za-z0-9]+", prop)
    alias = "".join(part[:1].upper() + part[1:] for part in parts if part)
    return alias or "Value"


def _safe_identifier(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value))


def _dedupe_templates(templates: list[TemplateCandidate]) -> list[TemplateCandidate]:
    seen: set[str] = set()
    deduped: list[TemplateCandidate] = []
    for template in templates:
        key = template.template.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(template)
    return deduped


def _cypher_literal(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    escaped = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"
