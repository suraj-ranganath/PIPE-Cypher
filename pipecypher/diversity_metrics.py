from __future__ import annotations

import json
import math
import re
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
) -> dict[str, Any]:
    if not examples:
        raise ValueError("cannot analyze an empty benchmark")

    schema_inventory = schema_inventory or {}
    questions = [str(row.get("question", "")) for row in examples]
    signatures = [
        canonical_query_signature(str(row.get("normalized_cypher") or row.get("cypher", "")))
        for row in examples
    ]
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
        },
        "schema_coverage": {
            "labels": _coverage(labels, schema_inventory.get("labels", set())),
            "relationship_types": _coverage(
                relationships,
                schema_inventory.get("relationship_types", set()),
            ),
            "properties": _coverage(properties, schema_inventory.get("properties", set())),
        },
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
        },
        "structural_features": structural_feature_summary(examples),
    }
    if include_by_graph:
        report["by_graph"] = {
            graph: benchmark_diversity_report(
                rows,
                schema_inventory=schema_inventory,
                self_bleu_sample_size=self_bleu_sample_size,
                include_by_graph=False,
            )
            for graph, rows in _group_by_graph(examples).items()
        }
    return report


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
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in examples:
        groups.setdefault(str(row.get("graph_profile")), []).append(row)
    return groups


def _ngrams(tokens: list[str], n: int):
    for idx in range(0, max(0, len(tokens) - n + 1)):
        yield tuple(tokens[idx : idx + n])


def _normalize_text(text: str) -> str:
    return " ".join(tokenize(text))


def _top_share(values: list[str]) -> float:
    if not values:
        return 0.0
    return max(Counter(values).values()) / len(values)
