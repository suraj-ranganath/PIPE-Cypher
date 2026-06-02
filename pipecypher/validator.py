from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from typing import Any

from .cypher_parser import OptionalCypherParser, analyze_cypher
from .models import SchemaSummary, ValidationIssue, ValidationResult
from .strategy import primary_strategy, strategy_tags


WRITE_TOKENS = (
    "CREATE",
    "MERGE",
    "DELETE",
    "DETACH",
    "SET",
    "REMOVE",
    "DROP",
    "LOAD CSV",
    "CALL DBMS",
    "CALL APOC.CREATE",
    "CALL APOC.LOAD",
    "CALL APOC.PERIODIC",
    "CALL APOC.TRIGGER",
)

RESERVED_VARIABLES = {"index", "constraint", "create", "drop", "exists", "remove"}
AGGREGATES = ("COUNT(", "SUM(", "AVG(", "MIN(", "MAX(", "COLLECT(")
CONTEXTUAL_RETURN_PROPERTIES = {
    "Person": {"personName": ("personId",)},
    "Company": {"companyName": ("companyId", "business")},
    "Account": {"accountId": ("accountType", "isBlocked")},
    "Loan": {"loanId": ("loanAmount", "balance")},
    "Medium": {"mediumId": ("mediumType", "riskLevel")},
}


def strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    if "```" not in cleaned:
        return cleaned
    parts = cleaned.split("```")
    if len(parts) >= 3:
        cleaned = parts[1]
    else:
        cleaned = parts[-1]
    if cleaned.lower().startswith("cypher"):
        cleaned = cleaned[6:]
    return cleaned.strip()


def normalize_cypher(query: str) -> str:
    query = clean_cypher(query)
    analysis = analyze_cypher(query)
    if not analysis.rewrite_safe:
        return query
    query = re.sub(r"(?i)COALESCE\(([^)]*)\)", lambda m: "COALESCE(" + m.group(1).replace(" ", "") + ")", query)
    if analysis.has_return and not analysis.has_return_distinct:
        query = re.sub(r"(?i)\bRETURN\b", "RETURN DISTINCT", query, count=1)
    return query


def clean_cypher(query: str) -> str:
    query = strip_code_fences(query)
    return re.sub(r"\s+", " ", query).strip()


def assert_read_only(query: str) -> None:
    upper = strip_code_fences(query).upper()
    for token in WRITE_TOKENS:
        if re.search(rf"(?<![A-Z0-9_]){re.escape(token)}(?![A-Z0-9_])", upper):
            raise ValueError(f"Generated Cypher is not read-only: blocked token {token}")


def is_read_only(query: str) -> bool:
    try:
        assert_read_only(query)
        return True
    except ValueError:
        return False


def _node_patterns(query: str) -> list[tuple[str | None, str | None, str | None]]:
    # Returns variable, first label, property-map body.
    pattern = re.compile(r"\(\s*([A-Za-z_][A-Za-z0-9_]*)?\s*(?::([A-Za-z_][A-Za-z0-9_]*))?(?:\s*\{([^}]*)\})?\s*\)")
    return [(m.group(1), m.group(2), m.group(3)) for m in pattern.finditer(query)]


def _relationship_fragments(query: str) -> list[tuple[str | None, str | None, str]]:
    pattern = re.compile(
        r"(?P<left_arrow><)?-\[\s*(?P<var>[A-Za-z_][A-Za-z0-9_]*)?"
        r"\s*(?::(?P<rel>[A-Za-z_][A-Za-z0-9_]*))?"
        r"(?:\*[^]\s{}]*)?(?:\s*\{[^}]*\})?\s*\]-(?P<right_arrow>>)?"
    )
    fragments: list[tuple[str | None, str | None, str]] = []
    for match in pattern.finditer(query):
        left_arrow = bool(match.group("left_arrow"))
        right_arrow = bool(match.group("right_arrow"))
        if left_arrow and right_arrow:
            direction = "bidirectional"
        elif left_arrow:
            direction = "incoming"
        elif right_arrow:
            direction = "outgoing"
        else:
            direction = "undirected"
        fragments.append((match.group("var"), match.group("rel"), direction))
    return fragments


def _relationship_fragments_with_properties(
    query: str,
) -> list[tuple[str | None, str | None, str | None, str]]:
    pattern = re.compile(
        r"(?P<left_arrow><)?-\[\s*(?P<var>[A-Za-z_][A-Za-z0-9_]*)?"
        r"\s*(?::(?P<rel>[A-Za-z_][A-Za-z0-9_]*))?"
        r"(?:\*[^]\s{}]*)?(?:\s*\{(?P<props>[^}]*)\})?\s*\]-(?P<right_arrow>>)?"
    )
    fragments: list[tuple[str | None, str | None, str | None, str]] = []
    for match in pattern.finditer(query):
        left_arrow = bool(match.group("left_arrow"))
        right_arrow = bool(match.group("right_arrow"))
        if left_arrow and right_arrow:
            direction = "bidirectional"
        elif left_arrow:
            direction = "incoming"
        elif right_arrow:
            direction = "outgoing"
        else:
            direction = "undirected"
        fragments.append(
            (match.group("var"), match.group("rel"), match.group("props"), direction)
        )
    return fragments


def _relationship_patterns(query: str) -> list[tuple[str | None, str | None]]:
    return [(var, rel_type) for var, rel_type, _ in _relationship_fragments(query)]


def _relationship_triples(query: str) -> list[tuple[str | None, str | None, str | None, str]]:
    pattern = re.compile(
        r"\(\s*(?:[A-Za-z_][A-Za-z0-9_]*\s*)?(?::(?P<left_label>[A-Za-z_][A-Za-z0-9_]*))?[^)]*\)"
        r"\s*(?P<left_arrow><)?-\[\s*(?:[A-Za-z_][A-Za-z0-9_]*\s*)?"
        r"(?::(?P<rel>[A-Za-z_][A-Za-z0-9_]*))[^]]*\]-(?P<right_arrow>>)?\s*"
        r"\(\s*(?:[A-Za-z_][A-Za-z0-9_]*\s*)?(?::(?P<right_label>[A-Za-z_][A-Za-z0-9_]*))?[^)]*\)"
    )
    triples: list[tuple[str | None, str | None, str | None, str]] = []
    for match in pattern.finditer(query):
        left_label = match.group("left_label")
        right_label = match.group("right_label")
        rel_type = match.group("rel")
        left_arrow = bool(match.group("left_arrow"))
        right_arrow = bool(match.group("right_arrow"))
        if left_arrow and right_arrow:
            triples.append((left_label, rel_type, right_label, "bidirectional"))
        elif left_arrow:
            triples.append((right_label, rel_type, left_label, "incoming"))
        elif right_arrow:
            triples.append((left_label, rel_type, right_label, "outgoing"))
        else:
            triples.append((left_label, rel_type, right_label, "undirected"))
    return triples


def _property_names(prop_map: str | None) -> list[str]:
    if not prop_map:
        return []
    return re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*:", prop_map)


def _string_literals(text: str) -> list[str]:
    literals: list[str] = []
    for single, double in re.findall(r"'((?:\\'|[^'])*)'|\"((?:\\\"|[^\"])*)\"", text):
        literals.append(single if single else double)
    return literals


def _property_literal_pairs(prop_map: str | None) -> list[tuple[str, str]]:
    if not prop_map:
        return []
    pairs: list[tuple[str, str]] = []
    for match in re.finditer(
        r"([A-Za-z_][A-Za-z0-9_]*)\s*:\s*('(?:\\'|[^'])*'|\"(?:\\\"|[^\"])*\")",
        prop_map,
    ):
        for literal in _string_literals(match.group(2)):
            pairs.append((match.group(1), literal))
    return pairs


def _where_property_literal_pairs(query: str) -> list[tuple[str, str, str]]:
    pairs: list[tuple[str, str, str]] = []
    pattern = re.compile(
        r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\s*"
        r"(?:=|<>|IN)\s*(\[[^\]]+\]|'(?:\\'|[^'])*'|\"(?:\\\"|[^\"])*\")",
        re.I,
    )
    for var, prop, literal_expr in pattern.findall(query):
        for literal in _string_literals(literal_expr):
            pairs.append((var, prop, literal))
    return pairs


def categorical_property_issues(
    query: str,
    schema: SchemaSummary,
    var_to_label: dict[str, str],
) -> list[ValidationIssue]:
    allowed_by_key = {
        key: {str(value) for value in values}
        for key, values in schema.categorical_properties.items()
        if values
    }
    if not allowed_by_key:
        return []

    checks: list[tuple[str, str, str]] = []
    for var, label, prop_map in _node_patterns(query):
        if not label:
            continue
        for prop, literal in _property_literal_pairs(prop_map):
            checks.append((label, prop, literal))
            if var:
                var_to_label.setdefault(var, label)
    for var, prop, literal in _where_property_literal_pairs(query):
        label = var_to_label.get(var)
        if label:
            checks.append((label, prop, literal))

    issues: list[ValidationIssue] = []
    seen: set[tuple[str, str, str]] = set()
    for label, prop, literal in checks:
        key = f"{label}.{prop}"
        allowed = allowed_by_key.get(key)
        if not allowed or literal in allowed:
            continue
        issue_key = (key, literal, ",".join(sorted(allowed)))
        if issue_key in seen:
            continue
        seen.add(issue_key)
        issues.append(
            ValidationIssue(
                "error",
                "invalid_categorical_value",
                f"Value `{literal}` is not allowed for categorical property {key}; "
                f"expected one of: {', '.join(sorted(allowed))}",
            )
        )
    return issues


def _return_projection_items(query: str) -> list[str]:
    items: list[str] = []
    for item in analyze_cypher(query).projection_items:
        if item.alias:
            items.append(f"{item.expression} AS {item.alias}")
        else:
            items.append(item.expression)
    return items


def _exact_variable_returned(items: Iterable[str], var: str) -> bool:
    return any(re.match(rf"^{re.escape(var)}(?:\s+AS\s+[A-Za-z_][A-Za-z0-9_]*)?$", item, re.I) for item in items)


def contextual_return_issues(query: str, var_to_label: dict[str, str]) -> list[ValidationIssue]:
    analysis = analyze_cypher(query)
    if not analysis.projection_items:
        return []
    returned_props_by_var: dict[str, set[str]] = {}
    items = _return_projection_items(query)
    for item in analysis.projection_items:
        for var, prop in re.findall(
            r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b",
            item.expression,
        ):
            returned_props_by_var.setdefault(var, set()).add(prop)

    issues: list[ValidationIssue] = []
    for var, props in returned_props_by_var.items():
        label = var_to_label.get(var)
        if not label or _exact_variable_returned(items, var):
            continue
        rules = CONTEXTUAL_RETURN_PROPERTIES.get(label, {})
        for trigger_prop, required_props in rules.items():
            if trigger_prop not in props:
                continue
            missing = [prop for prop in required_props if prop not in props]
            if missing:
                issues.append(
                    ValidationIssue(
                        "warning",
                        "missing_context_column",
                        f"Return {label}.{trigger_prop} with contextual column(s): {', '.join(missing)}",
                    )
                )
    return issues


def generic_node_scan_issues(query: str) -> list[ValidationIssue]:
    nodes = _node_patterns(query)
    rels = _relationship_patterns(query)
    if not nodes or rels:
        return []
    if any(label or prop_map for _, label, prop_map in nodes):
        return []

    items = _return_projection_items(query)
    if not items:
        return []
    node_vars = [var for var, _, _ in nodes if var]
    if len(node_vars) == 1 and _exact_variable_returned(items, node_vars[0]):
        return [
            ValidationIssue(
                "warning",
                "generic_node_scan",
                "Query returns an unlabeled node variable; use schema-specific labels and columns",
            )
        ]
    return []


def variable_label_map(query: str) -> dict[str, str]:
    mapping = {}
    for var, label, _ in _node_patterns(query):
        if var and label:
            mapping[var] = label
    return mapping


def variable_relationship_map(query: str) -> dict[str, str]:
    mapping = {}
    for var, rel_type, _ in _relationship_fragments(query):
        if var and rel_type:
            mapping[var] = rel_type
    return mapping


def structural_features(query: str) -> dict[str, Any]:
    upper = query.upper()
    analysis = analyze_cypher(query)
    rel_count = len(_relationship_patterns(query))
    return_items = [item.expression for item in analysis.projection_items]
    labels = [label for _, label, _ in _node_patterns(query) if label]
    rels = [rel_type for _, rel_type in _relationship_patterns(query) if rel_type]
    features = {
        "node_pattern_count": len(_node_patterns(query)),
        "relationship_pattern_count": rel_count,
        "optional_match": "OPTIONAL MATCH" in upper,
        "aggregation": any(fn in upper for fn in AGGREGATES),
        "ordering": bool(analysis.order_by_items),
        "limit": analysis.limit_value is not None,
        "skip": analysis.skip_value is not None,
        "negation": any(tok in upper for tok in (" NOT ", "NOT EXISTS", "WHERE NOT", "<>")),
        "path_pattern": "*" in query or "shortestPath" in query,
        "return_arity": len(return_items),
        "labels": sorted(set(labels)),
        "relationship_types": sorted(set(rels)),
        "label_counts": dict(Counter(labels)),
        "relationship_counts": dict(Counter(rels)),
    }
    features.update(analysis.to_feature_dict())
    features["difficulty"] = infer_difficulty(features)
    features["strategy_tags"] = strategy_tags(features)
    features["primary_strategy"] = primary_strategy(features)
    return features


def infer_difficulty(features: dict[str, Any]) -> str:
    score = 0
    score += int(features.get("relationship_pattern_count", 0) >= 2)
    score += int(features.get("aggregation", False))
    score += int(features.get("ordering", False))
    score += int(features.get("negation", False))
    score += int(features.get("optional_match", False))
    score += int(features.get("path_pattern", False))
    if score <= 1:
        return "easy"
    if score <= 3:
        return "medium"
    return "hard"


def validate_cypher(
    query: str,
    schema: SchemaSummary | None = None,
    *,
    parser: OptionalCypherParser | None = None,
    normalize: bool = True,
) -> ValidationResult:
    cleaned = clean_cypher(query)
    pre_normalization_analysis = analyze_cypher(cleaned)
    normalized = normalize_cypher(query) if normalize else clean_cypher(query)
    post_normalization_analysis = analyze_cypher(normalized)
    issues: list[ValidationIssue] = []

    if normalize and pre_normalization_analysis.rewrite_skip_reasons:
        issues.append(
            ValidationIssue(
                "warning",
                "rewrite_skipped",
                "Skipped Cypher normalization because "
                + "; ".join(pre_normalization_analysis.rewrite_skip_reasons),
            )
        )
        if (
            post_normalization_analysis.has_return
            and not post_normalization_analysis.has_return_distinct
        ):
            issues.append(
                ValidationIssue(
                    "warning",
                    "missing_return_distinct",
                    "RETURN DISTINCT was not inserted because parser-aware rewrite safety checks failed",
                )
            )

    read_only = is_read_only(normalized)
    if not read_only:
        issues.append(ValidationIssue("error", "not_read_only", "Query contains write/admin tokens"))

    syntax_valid = True
    if not re.search(r"(?i)\b(MATCH|OPTIONAL MATCH|WITH|RETURN|ASK|CALL)\b", normalized):
        syntax_valid = False
        issues.append(ValidationIssue("error", "syntax_shape", "Query lacks recognizable Cypher clauses"))
    if normalized.count("(") != normalized.count(")"):
        syntax_valid = False
        issues.append(ValidationIssue("error", "unbalanced_parentheses", "Parentheses are unbalanced"))
    if normalized.count("[") != normalized.count("]"):
        syntax_valid = False
        issues.append(ValidationIssue("error", "unbalanced_brackets", "Relationship brackets are unbalanced"))
    issues.extend(generic_node_scan_issues(normalized))

    for var, _, _ in _node_patterns(normalized):
        if var and var.lower() in RESERVED_VARIABLES:
            syntax_valid = False
            issues.append(
                ValidationIssue(
                    "error",
                    "reserved_variable",
                    f"Variable `{var}` is a reserved or high-risk Cypher keyword",
                )
            )
    for var, _ in _relationship_patterns(normalized):
        if var and var.lower() in RESERVED_VARIABLES:
            syntax_valid = False
            issues.append(
                ValidationIssue("error", "reserved_variable", f"Relationship variable `{var}` is reserved")
            )

    parser = parser or OptionalCypherParser()
    parse_error = parser.parse_error(normalized)
    if parse_error:
        syntax_valid = False
        issues.append(ValidationIssue("error", "antlr_parse", parse_error))

    schema_valid = True
    if schema is not None:
        labels = schema.labels
        rel_types = schema.relationship_types
        var_to_label = variable_label_map(normalized)
        var_to_relationship = variable_relationship_map(normalized)
        for _, label, prop_map in _node_patterns(normalized):
            if label and labels and label not in labels:
                schema_valid = False
                issues.append(ValidationIssue("error", "unknown_label", f"Unknown label :{label}"))
            if label and prop_map:
                allowed = schema.properties_for_label(label)
                for prop in _property_names(prop_map):
                    if allowed and prop not in allowed:
                        schema_valid = False
                        issues.append(
                            ValidationIssue("error", "unknown_property", f"Unknown property :{label}.{prop}")
                        )
        for _, rel_type, direction in _relationship_fragments(normalized):
            if direction == "undirected":
                schema_valid = False
                issues.append(
                    ValidationIssue(
                        "error",
                        "undirected_relationship",
                        "Relationship patterns must use an explicit Cypher direction",
                    )
                )
            if direction == "bidirectional":
                schema_valid = False
                issues.append(
                    ValidationIssue(
                        "error",
                        "bidirectional_relationship",
                        "Relationship patterns cannot point in both directions",
                    )
                )
            if not rel_type:
                schema_valid = False
                issues.append(
                    ValidationIssue(
                        "error",
                        "missing_relationship_type",
                        "Relationship patterns must include a schema-visible type",
                    )
                )
                continue
            if rel_types and rel_type not in rel_types:
                schema_valid = False
                issues.append(
                    ValidationIssue("error", "unknown_relationship", f"Unknown relationship :{rel_type}")
                )
        for _, rel_type, prop_map, _ in _relationship_fragments_with_properties(normalized):
            if not rel_type or not prop_map:
                continue
            allowed = schema.properties_for_relationship(rel_type)
            for prop in _property_names(prop_map):
                if (allowed or schema.relationship_properties) and prop not in allowed:
                    schema_valid = False
                    issues.append(
                        ValidationIssue(
                            "error",
                            "unknown_relationship_property",
                            f"Unknown property :{rel_type}.{prop}",
                        )
                    )
        for start, rel_type, end, direction in _relationship_triples(normalized):
            if direction in {"undirected", "bidirectional"}:
                continue
            if not (start and rel_type and end):
                continue
            if schema.relationships and not schema.has_relationship(start, rel_type, end):
                if schema.has_reverse_relationship(start, rel_type, end):
                    msg = f"Relationship direction should be (:{end})-[:{rel_type}]->(:{start})"
                    issues.append(ValidationIssue("error", "wrong_direction", msg))
                    schema_valid = False
                else:
                    issues.append(
                        ValidationIssue(
                            "warning",
                            "unseen_relationship_pattern",
                            f"Pattern (:{start})-[:{rel_type}]->(:{end}) was not observed",
                        )
                    )
        for var, prop in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b", normalized):
            label = var_to_label.get(var)
            if not label:
                rel_type = var_to_relationship.get(var)
                if rel_type:
                    allowed = schema.properties_for_relationship(rel_type)
                    if (allowed or schema.relationship_properties) and prop not in allowed:
                        schema_valid = False
                        issues.append(
                            ValidationIssue(
                                "error",
                                "unknown_relationship_property",
                                f"Unknown property :{rel_type}.{prop}",
                            )
                        )
                continue
            allowed = schema.properties_for_label(label)
            if allowed and prop not in allowed:
                schema_valid = False
                issues.append(
                    ValidationIssue("error", "unknown_property", f"Unknown property :{label}.{prop}")
                )
        categorical_issues = categorical_property_issues(normalized, schema, var_to_label)
        if categorical_issues:
            schema_valid = False
            issues.extend(categorical_issues)
        issues.extend(contextual_return_issues(normalized, var_to_label))

    return ValidationResult(
        read_only=read_only,
        syntax_valid=syntax_valid,
        schema_valid=schema_valid,
        normalized_cypher=normalized,
        issues=issues,
        structural_features=structural_features(normalized),
    )
