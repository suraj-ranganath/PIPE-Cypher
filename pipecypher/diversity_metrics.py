from __future__ import annotations

import json
import math
import re
import hashlib
from collections import Counter
from pathlib import Path
from typing import Any

TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
QUOTED_LITERAL_RE = re.compile(r"'(?:\\'|[^'])*'|\"(?:\\\"|[^\"])*\"")
NUMERIC_LITERAL_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
VARIABLE_RE = re.compile(r"\(([A-Za-z_][A-Za-z0-9_]*)\s*:")
PROPERTY_OWNER_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?=\.)")


def load_benchmark_examples(path: str | Path) -> list[dict[str, Any]]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def load_schema_inventory(paths: list[str | Path]) -> dict[str, set[str]]:
    labels: set[str] = set()
    relationships: set[str] = set()
    properties: set[str] = set()
    for path in paths:
        schema = json.loads(Path(path).read_text(encoding="utf-8"))
        for item in schema.get("node_properties", []):
            labels.add(str(item.get("label", "")))
            properties.add(str(item.get("property", "")))
        for item in schema.get("relationship_properties", []):
            rel_type = str(item.get("type", "")).strip(":`")
            if rel_type:
                relationships.add(rel_type)
            prop = str(item.get("property", ""))
            if prop:
                properties.add(prop)
        for item in schema.get("relationships", []):
            rel_type = str(item.get("type", ""))
            if rel_type:
                relationships.add(rel_type)
    return {
        "labels": {item for item in labels if item},
        "relationship_types": {item for item in relationships if item},
        "properties": {item for item in properties if item},
    }


def benchmark_diversity_report(
    examples: list[dict[str, Any]],
    *,
    schema_inventory: dict[str, set[str]] | None = None,
    self_bleu_sample_size: int = 200,
    include_by_graph: bool = True,
    include_by_category: bool = True,
) -> dict[str, Any]:
    if not examples:
        raise ValueError("cannot analyze an empty benchmark")

    schema_inventory = schema_inventory or {}
    questions = [str(row.get("question", "")) for row in examples]
    signatures = [
        canonical_query_signature(str(row.get("normalized_cypher") or row.get("cypher", "")))
        for row in examples
    ]
    template_families = [template_family_signature(row) for row in examples]
    operator_combinations = [operator_combination_signature(row) for row in examples]
    substructure_values = _flatten_substructures(examples)
    signature_counts = Counter(signatures)
    labels = _flatten_feature(examples, "labels")
    relationships = _flatten_feature(examples, "relationship_types")
    properties = _extract_properties(examples)
    category_counts = Counter(str(row.get("category", "unknown")) for row in examples)
    graph_category_counts = Counter(
        f"{row.get('graph_profile')}::{row.get('category')}" for row in examples
    )
    report: dict[str, Any] = {
        "n": len(examples),
        "question_text": {
            "distinct_1": distinct_n(questions, 1),
            "distinct_2": distinct_n(questions, 2),
            "distinct_3": distinct_n(questions, 3),
            "ead_distinct_1": expected_distinct_ratio(questions, 1),
            "ead_distinct_2": expected_distinct_ratio(questions, 2),
            "pairwise_jaccard_sampled": pairwise_question_similarity(
                questions,
                max_examples=self_bleu_sample_size,
            ),
            "self_bleu_2_sampled": self_bleu(
                questions,
                max_examples=self_bleu_sample_size,
                max_order=2,
            ),
            "unique_question_ratio": len(set(_normalize_text(q) for q in questions))
            / len(questions),
        },
        "query_templates": {
            "unique_signature_count": len(set(signatures)),
            "unique_signature_ratio": len(set(signatures)) / len(signatures),
            "top_signature_share": _top_share(signatures),
            "top_signatures": _top_signature_rows(signature_counts, total=len(signatures)),
        },
        "template_families": {
            "unique_family_count": len(set(template_families)),
            "unique_family_ratio": len(set(template_families)) / len(template_families),
            "top_family_share": _top_share(template_families),
            "distribution": distribution_metrics(Counter(template_families)),
            "top_families": _top_signature_rows(Counter(template_families), total=len(examples)),
        },
        "schema_coverage": {
            "labels": _coverage(labels, schema_inventory.get("labels", set())),
            "relationship_types": _coverage(
                relationships,
                schema_inventory.get("relationship_types", set()),
            ),
            "properties": _coverage(properties, schema_inventory.get("properties", set())),
        },
        "value_grounding": value_grounding_summary(examples),
        "distributions": {
            "category": distribution_metrics(category_counts),
            "graph_category": distribution_metrics(graph_category_counts),
            "difficulty": distribution_metrics(
                Counter(str(row.get("difficulty", "unknown")) for row in examples)
            ),
            "primary_strategy": distribution_metrics(
                Counter(
                    str(row.get("structural_features", {}).get("primary_strategy", "unknown"))
                    for row in examples
                )
            ),
            "labels": distribution_metrics(Counter(labels)),
            "relationship_types": distribution_metrics(Counter(relationships)),
            "operator_combinations": distribution_metrics(Counter(operator_combinations)),
        },
        "structural_substructures": structural_substructure_summary(
            examples,
            substructure_values,
        ),
        "structural_features": structural_feature_summary(examples),
    }
    report["pipe_diversity_index"] = pipe_diversity_index(report)
    if include_by_graph:
        report["by_graph"] = {
            graph: benchmark_diversity_report(
                rows,
                schema_inventory=schema_inventory,
                self_bleu_sample_size=self_bleu_sample_size,
                include_by_graph=False,
                include_by_category=False,
            )
            for graph, rows in _group_by_graph(examples).items()
        }
    if include_by_category:
        report["by_category"] = {
            category: benchmark_diversity_report(
                rows,
                schema_inventory=schema_inventory,
                self_bleu_sample_size=self_bleu_sample_size,
                include_by_graph=False,
                include_by_category=False,
            )
            for category, rows in _group_by_key(examples, "category").items()
        }
    return report


def value_grounding_summary(examples: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate graph-bound value diversity without exposing raw values."""

    entity_values = [_normalize_value(value) for value in _flatten_entity_values(examples)]
    entity_values = [value for value in entity_values if value]
    quoted_literals = [_normalize_value(value) for value in _extract_quoted_literals(examples)]
    quoted_literals = [value for value in quoted_literals if value]
    examples_with_entities = [
        row
        for row in examples
        if any(_normalize_value(value) for value in row.get("entity_values", []))
    ]
    exact_matched = sum(
        1
        for row in examples_with_entities
        if _entity_values_are_quoted(row)
    )
    return {
        "total_entity_mentions": len(entity_values),
        "unique_entity_values": len(set(entity_values)),
        "unique_entity_value_ratio": _unique_ratio(entity_values),
        "top_entity_value_share": _top_share(entity_values),
        "examples_with_entity_values_rate": len(examples_with_entities) / len(examples),
        "entity_values_exact_quoted_rate": (
            exact_matched / len(examples_with_entities) if examples_with_entities else 0.0
        ),
        "total_quoted_literal_mentions": len(quoted_literals),
        "unique_quoted_literals": len(set(quoted_literals)),
        "unique_quoted_literal_ratio": _unique_ratio(quoted_literals),
        "top_quoted_literal_share": _top_share(quoted_literals),
        "examples_with_quoted_literals_rate": _examples_with_quoted_literals_rate(examples),
    }


def distribution_metrics(counts: Counter[str]) -> dict[str, Any]:
    total = sum(counts.values())
    if total == 0:
        return {
            "total": 0,
            "unique": 0,
            "entropy_bits": 0.0,
            "normalized_entropy": 0.0,
            "effective_count": 0.0,
            "simpson_diversity": 0.0,
            "counts": {},
        }
    probabilities = [count / total for count in counts.values()]
    entropy = -sum(p * math.log2(p) for p in probabilities if p > 0)
    max_entropy = math.log2(len(counts)) if len(counts) > 1 else 0.0
    simpson = 1.0 - sum(p * p for p in probabilities)
    return {
        "total": total,
        "unique": len(counts),
        "entropy_bits": entropy,
        "normalized_entropy": entropy / max_entropy if max_entropy else 1.0,
        "effective_count": 2**entropy,
        "simpson_diversity": simpson,
        "counts": dict(sorted(counts.items())),
    }


def structural_substructures(row: dict[str, Any]) -> set[str]:
    """Return compact Cypher substructure atoms for diversity accounting."""

    features = row.get("structural_features", {}) or {}
    cypher = str(row.get("normalized_cypher") or row.get("cypher", ""))
    atoms: set[str] = set()
    for label in features.get("labels", []) or []:
        atoms.add(f"label:{label}")
    for rel_type in features.get("relationship_types", []) or []:
        atoms.add(f"rel:{rel_type}")
    for rel in features.get("relationship_observations", []) or []:
        if not isinstance(rel, dict):
            continue
        start = rel.get("start_label") or "?"
        rel_type = rel.get("relationship_type") or "?"
        end = rel.get("end_label") or "?"
        direction = rel.get("direction") or "?"
        atoms.add(f"triple:{start}-[{rel_type}:{direction}]->{end}")
    for name in (
        "optional_match",
        "aggregation",
        "ordering",
        "limit",
        "skip",
        "negation",
        "path_pattern",
    ):
        if features.get(name):
            atoms.add(f"op:{name}")
    for fn in re.findall(r"\b(COUNT|SUM|AVG|MIN|MAX|COLLECT)\s*\(", cypher, re.I):
        atoms.add(f"agg:{fn.upper()}")
    for op in re.findall(
        r"\s(=|<>|<=|>=|<|>|IN|CONTAINS|STARTS\s+WITH|ENDS\s+WITH)\s",
        cypher,
        re.I,
    ):
        atoms.add("pred:" + " ".join(op.upper().split()))
    for prop in _extract_properties([row]):
        atoms.add(f"prop:{prop}")
    atoms.add(f"strategy:{features.get('primary_strategy', 'unknown')}")
    atoms.add(f"return_arity:{_bucket_int(features.get('return_arity', 0))}")
    atoms.add(f"rel_count:{_bucket_int(features.get('relationship_pattern_count', 0))}")
    return atoms


def structural_substructure_summary(
    examples: list[dict[str, Any]],
    substructures: list[str] | None = None,
) -> dict[str, Any]:
    values = substructures if substructures is not None else _flatten_substructures(examples)
    counts = Counter(values)
    distribution = distribution_metrics(counts)
    return {
        "unique_substructure_count": len(counts),
        "unique_substructure_per_example": len(counts) / len(examples) if examples else 0.0,
        "normalized_entropy": distribution["normalized_entropy"],
        "effective_count": distribution["effective_count"],
        "top_substructures": _top_signature_rows(counts, total=len(values) or 1),
    }


def structural_feature_summary(examples: list[dict[str, Any]]) -> dict[str, float]:
    feature_names = (
        "optional_match",
        "aggregation",
        "ordering",
        "limit",
        "negation",
        "path_pattern",
    )
    summary: dict[str, float] = {}
    for name in feature_names:
        summary[f"{name}_rate"] = sum(
            1 for row in examples if row.get("structural_features", {}).get(name)
        ) / len(examples)
    summary["mean_relationship_patterns"] = _mean_feature(
        examples,
        "relationship_pattern_count",
    )
    summary["mean_node_patterns"] = _mean_feature(examples, "node_pattern_count")
    summary["mean_return_arity"] = _mean_feature(examples, "return_arity")
    return summary


def expected_distinct_ratio(
    texts: list[str],
    n: int,
    *,
    reference_size: int = 1000,
) -> float:
    """Finite-sample adjusted Distinct-n from the empirical n-gram distribution.

    This EAD-style score estimates the expected unique n-gram ratio after drawing
    a fixed-size sample from the observed distribution, making comparisons less
    sensitive to the number of benchmark rows than raw Distinct-n alone.
    """

    counts: Counter[tuple[str, ...]] = Counter()
    total = 0
    for text in texts:
        grams = list(_ngrams(tokenize(text), n))
        counts.update(grams)
        total += len(grams)
    if total == 0:
        return 0.0
    sample_size = min(reference_size, total)
    expected_unique = sum(
        1.0 - (1.0 - (count / total)) ** sample_size
        for count in counts.values()
    )
    return expected_unique / sample_size if sample_size else 0.0


def pairwise_question_similarity(
    texts: list[str],
    *,
    max_examples: int = 200,
) -> dict[str, float]:
    sample = sorted(_normalize_text(text) for text in texts if text.strip())[:max_examples]
    token_sets = [set(tokenize(text)) for text in sample]
    if len(token_sets) < 2:
        return {"mean_jaccard": 0.0, "mean_nearest_neighbor_jaccard": 0.0}
    similarities: list[float] = []
    nearest: list[float] = []
    for idx, current in enumerate(token_sets):
        current_nearest = 0.0
        for other_idx, other in enumerate(token_sets):
            if idx == other_idx:
                continue
            score = jaccard(current, other)
            similarities.append(score)
            current_nearest = max(current_nearest, score)
        nearest.append(current_nearest)
    return {
        "mean_jaccard": sum(similarities) / len(similarities) if similarities else 0.0,
        "mean_nearest_neighbor_jaccard": sum(nearest) / len(nearest) if nearest else 0.0,
    }


def distinct_n(texts: list[str], n: int) -> float:
    total = 0
    unique: set[tuple[str, ...]] = set()
    for text in texts:
        tokens = tokenize(text)
        grams = list(_ngrams(tokens, n))
        total += len(grams)
        unique.update(grams)
    return len(unique) / total if total else 0.0


def self_bleu(texts: list[str], *, max_examples: int = 200, max_order: int = 2) -> float:
    sample = sorted(_normalize_text(text) for text in texts if text.strip())[:max_examples]
    if len(sample) < 2:
        return 0.0
    tokenized = [tokenize(text) for text in sample]
    scores = []
    for idx, candidate in enumerate(tokenized):
        references = tokenized[:idx] + tokenized[idx + 1 :]
        scores.append(_sentence_bleu(candidate, references, max_order=max_order))
    return sum(scores) / len(scores)


def canonical_query_signature(cypher: str) -> str:
    signature = QUOTED_LITERAL_RE.sub("<str>", cypher)
    signature = NUMERIC_LITERAL_RE.sub("<num>", signature)
    signature = VARIABLE_RE.sub("(<var>:", signature)
    signature = PROPERTY_OWNER_RE.sub("<var>", signature)
    return " ".join(signature.lower().split())


def template_family_signature(row: dict[str, Any]) -> str:
    metadata = row.get("template_metadata") or {}
    schema_kind = metadata.get("schema_template_kind") if isinstance(metadata, dict) else None
    if schema_kind:
        return f"schema:{schema_kind}"
    template = row.get("template")
    if template:
        return "template:" + _mask_surface_template(str(template))
    source = row.get("source") or {}
    if isinstance(source, dict) and source.get("template"):
        return "template:" + _mask_surface_template(str(source["template"]))
    return "query:" + canonical_query_signature(str(row.get("normalized_cypher") or row.get("cypher", "")))


def operator_combination_signature(row: dict[str, Any]) -> str:
    features = row.get("structural_features", {}) or {}
    names = [
        name
        for name in (
            "optional_match",
            "aggregation",
            "ordering",
            "limit",
            "skip",
            "negation",
            "path_pattern",
        )
        if features.get(name)
    ]
    primary = str(features.get("primary_strategy", "unknown"))
    return primary + "+" + ("+".join(names) if names else "plain")


def pipe_diversity_index(report: dict[str, Any]) -> dict[str, Any]:
    text = report.get("question_text", {})
    templates = report.get("query_templates", {})
    families = report.get("template_families", {})
    coverage = report.get("schema_coverage", {})
    values = report.get("value_grounding", {})
    distributions = report.get("distributions", {})
    substructures = report.get("structural_substructures", {})

    components = {
        "lexical": _mean(
            [
                float(text.get("distinct_2", 0.0)),
                float(text.get("ead_distinct_2", 0.0)),
                1.0 - float(text.get("self_bleu_2_sampled", 1.0)),
                1.0
                - float(
                    text.get("pairwise_jaccard_sampled", {}).get(
                        "mean_nearest_neighbor_jaccard",
                        1.0,
                    )
                ),
            ]
        ),
        "query_template": _mean(
            [
                float(templates.get("unique_signature_ratio", 0.0)),
                1.0 - float(templates.get("top_signature_share", 1.0)),
                float(families.get("unique_family_ratio", 0.0)),
                float(families.get("distribution", {}).get("normalized_entropy", 0.0)),
            ]
        ),
        "structural": _mean(
            [
                float(distributions.get("primary_strategy", {}).get("normalized_entropy", 0.0)),
                float(distributions.get("operator_combinations", {}).get("normalized_entropy", 0.0)),
                min(1.0, float(substructures.get("unique_substructure_per_example", 0.0))),
                float(substructures.get("normalized_entropy", 0.0)),
            ]
        ),
        "schema": _mean(
            [
                float(coverage.get("labels", {}).get("coverage", 0.0)),
                float(coverage.get("relationship_types", {}).get("coverage", 0.0)),
                float(coverage.get("properties", {}).get("coverage", 0.0)),
            ]
        ),
        "value": _mean(
            [
                float(values.get("unique_entity_value_ratio", 0.0)),
                1.0 - float(values.get("top_entity_value_share", 1.0)),
                float(values.get("entity_values_exact_quoted_rate", 0.0)),
            ]
        ),
        "balance": _mean(
            [
                float(distributions.get("category", {}).get("normalized_entropy", 0.0)),
                float(distributions.get("graph_category", {}).get("normalized_entropy", 0.0)),
                float(distributions.get("difficulty", {}).get("normalized_entropy", 0.0)),
            ]
        ),
    }
    return {
        "score": _geometric_mean(list(components.values())),
        "components": components,
        "method": (
            "geometric mean of lexical, query-template, structural, schema, value, "
            "and balance components"
        ),
    }


def jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _top_signature_rows(
    counts: Counter[str],
    *,
    total: int,
    limit: int = 8,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for signature, count in counts.most_common(limit):
        rows.append(
            {
                "signature_id": hashlib.sha256(signature.encode("utf-8")).hexdigest()[:10],
                "count": int(count),
                "share": count / total if total else 0.0,
                "preview": signature[:140],
            }
        )
    return rows


def tokenize(text: str) -> list[str]:
    return [match.group(0).lower() for match in TOKEN_RE.finditer(text)]


def _sentence_bleu(candidate: list[str], references: list[list[str]], *, max_order: int) -> float:
    if not candidate:
        return 0.0
    precisions = []
    for order in range(1, max_order + 1):
        candidate_counts = Counter(_ngrams(candidate, order))
        if not candidate_counts:
            precisions.append(0.0)
            continue
        max_reference_counts: Counter[tuple[str, ...]] = Counter()
        for reference in references:
            for gram, count in Counter(_ngrams(reference, order)).items():
                max_reference_counts[gram] = max(max_reference_counts[gram], count)
        clipped = sum(
            min(count, max_reference_counts[gram]) for gram, count in candidate_counts.items()
        )
        precisions.append((clipped + 1) / (sum(candidate_counts.values()) + 1))

    closest_ref_len = min(
        (len(ref) for ref in references),
        key=lambda value: abs(value - len(candidate)),
    )
    brevity_penalty = (
        1.0
        if len(candidate) > closest_ref_len
        else math.exp(1 - closest_ref_len / len(candidate))
    )
    return brevity_penalty * math.exp(
        sum(math.log(max(p, 1e-12)) for p in precisions) / max_order
    )


def _coverage(used_values: list[str], available_values: set[str]) -> dict[str, Any]:
    used = {value for value in used_values if value}
    available = {value for value in available_values if value}
    denominator = len(available) if available else len(used)
    return {
        "used_count": len(used),
        "available_count": len(available),
        "coverage": len(used) / denominator if denominator else 0.0,
        "used": sorted(used),
    }


def _extract_properties(examples: list[dict[str, Any]]) -> list[str]:
    properties: list[str] = []
    for row in examples:
        cypher = str(row.get("normalized_cypher") or row.get("cypher", ""))
        properties.extend(re.findall(r"\.([A-Za-z_][A-Za-z0-9_]*)", cypher))
    return properties


def _flatten_substructures(examples: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for row in examples:
        values.extend(sorted(structural_substructures(row)))
    return values


def _flatten_entity_values(examples: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for row in examples:
        values.extend(str(value) for value in row.get("entity_values", []))
    return values


def _extract_quoted_literals(examples: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for row in examples:
        cypher = str(row.get("normalized_cypher") or row.get("cypher", ""))
        values.extend(_unquote(match.group(0)) for match in QUOTED_LITERAL_RE.finditer(cypher))
    return values


def _flatten_feature(examples: list[dict[str, Any]], key: str) -> list[str]:
    values: list[str] = []
    for row in examples:
        values.extend(str(value) for value in row.get("structural_features", {}).get(key, []))
    return values


def _mean_feature(examples: list[dict[str, Any]], key: str) -> float:
    return sum(float(row.get("structural_features", {}).get(key, 0)) for row in examples) / len(
        examples
    )


def _group_by_graph(examples: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return _group_by_key(examples, "graph_profile")


def _group_by_key(examples: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in examples:
        groups.setdefault(str(row.get(key, "unknown")), []).append(row)
    return groups


def _ngrams(tokens: list[str], n: int):
    for idx in range(0, max(0, len(tokens) - n + 1)):
        yield tuple(tokens[idx : idx + n])


def _normalize_text(text: str) -> str:
    return " ".join(tokenize(text))


def _normalize_value(value: Any) -> str:
    return " ".join(str(value).strip().casefold().split())


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].replace("\\'", "'").replace('\\"', '"')
    return value


def _top_share(values: list[str]) -> float:
    if not values:
        return 0.0
    return max(Counter(values).values()) / len(values)


def _unique_ratio(values: list[str]) -> float:
    return len(set(values)) / len(values) if values else 0.0


def _mask_surface_template(value: str) -> str:
    text = re.sub(r"\{[^}]+\}", "{slot}", value.lower())
    text = re.sub(r"'[^']*'", "'<value>'", text)
    text = re.sub(r"\b\d+(?:\.\d+)?\b", "<number>", text)
    return " ".join(tokenize(text))


def _bucket_int(value: Any) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 0
    if number <= 0:
        return "0"
    if number == 1:
        return "1"
    if number == 2:
        return "2"
    return "3+"


def _mean(values: list[float]) -> float:
    clean = [max(0.0, min(1.0, value)) for value in values if not math.isnan(value)]
    return sum(clean) / len(clean) if clean else 0.0


def _geometric_mean(values: list[float]) -> float:
    clean = [max(1e-6, min(1.0, value)) for value in values if not math.isnan(value)]
    if not clean:
        return 0.0
    return math.exp(sum(math.log(value) for value in clean) / len(clean))


def _entity_values_are_quoted(row: dict[str, Any]) -> bool:
    entity_values = {
        _normalize_value(value)
        for value in row.get("entity_values", [])
        if _normalize_value(value)
    }
    if not entity_values:
        return False
    cypher = str(row.get("normalized_cypher") or row.get("cypher", ""))
    quoted_values = {
        _normalize_value(_unquote(match.group(0)))
        for match in QUOTED_LITERAL_RE.finditer(cypher)
    }
    return entity_values.issubset(quoted_values)


def _examples_with_quoted_literals_rate(examples: list[dict[str, Any]]) -> float:
    count = 0
    for row in examples:
        cypher = str(row.get("normalized_cypher") or row.get("cypher", ""))
        if QUOTED_LITERAL_RE.search(cypher):
            count += 1
    return count / len(examples) if examples else 0.0
