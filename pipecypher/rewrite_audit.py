from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .models import ExecutionResult
from .validator import clean_cypher


def load_records(paths: list[str | Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    return records


def record_normalized_cypher(record: dict[str, Any]) -> str:
    validation = record.get("validation") if isinstance(record.get("validation"), dict) else {}
    return str(
        record.get("normalized_cypher")
        or validation.get("normalized_cypher")
        or record.get("cypher")
        or ""
    )


def classify_rewrite(original: str, normalized: str) -> list[str]:
    """Return conservative rewrite classes between original and normalized Cypher."""

    original_raw = str(original or "")
    normalized_raw = str(normalized or "")
    original_clean = clean_cypher(original_raw)
    normalized_clean = clean_cypher(normalized_raw)
    if original_raw.strip() == normalized_raw.strip():
        return ["unchanged"]
    if original_clean == normalized_clean:
        return ["formatting_only"]

    classes: list[str] = []
    if _return_inserted(original_clean, normalized_clean):
        classes.append("return_distinct_inserted")
    if _coalesce_spacing_changed(original_clean, normalized_clean):
        classes.append("coalesce_spacing_normalized")
    if _strip_distinct(normalized_clean) == original_clean:
        classes.append("return_distinct_only")
    if not classes:
        classes.append("other_normalization")
    return classes


def summarize_rewrite_audit(records: list[dict[str, Any]]) -> dict[str, Any]:
    rewrite_type_counts: Counter[str] = Counter()
    accepted_rewrite_type_counts: Counter[str] = Counter()
    skip_reasons: Counter[str] = Counter()
    by_graph: dict[str, Counter[str]] = defaultdict(Counter)
    by_category: dict[str, Counter[str]] = defaultdict(Counter)
    changed_examples: list[dict[str, Any]] = []
    changed = 0
    accepted_changed = 0
    accepted = 0

    for record in records:
        graph = str(record.get("graph_profile") or "unknown")
        category = str(record.get("category") or "unknown")
        is_accepted = bool(record.get("accepted") or record.get("gates", {}).get("accepted"))
        accepted += int(is_accepted)
        original = str(record.get("cypher") or "")
        normalized = record_normalized_cypher(record)
        classes = classify_rewrite(original, normalized)
        for klass in classes:
            rewrite_type_counts[klass] += 1
            by_graph[graph][klass] += 1
            by_category[category][klass] += 1
            if is_accepted:
                accepted_rewrite_type_counts[klass] += 1
        if classes != ["unchanged"]:
            changed += 1
            accepted_changed += int(is_accepted)
            if len(changed_examples) < 8:
                changed_examples.append(
                    {
                        "id": record.get("id", ""),
                        "graph_profile": graph,
                        "category": category,
                        "accepted": is_accepted,
                        "rewrite_classes": classes,
                        "original": original,
                        "normalized": normalized,
                    }
                )

        features = _structural_features(record)
        for reason in features.get("rewrite_skip_reasons", []) or []:
            skip_reasons[str(reason)] += 1

    total = len(records)
    return {
        "records": total,
        "accepted_records": accepted,
        "changed_records": changed,
        "changed_rate": changed / total if total else 0.0,
        "accepted_changed_records": accepted_changed,
        "accepted_changed_rate": accepted_changed / accepted if accepted else 0.0,
        "rewrite_type_counts": dict(sorted(rewrite_type_counts.items())),
        "accepted_rewrite_type_counts": dict(sorted(accepted_rewrite_type_counts.items())),
        "rewrite_skip_reasons": dict(sorted(skip_reasons.items())),
        "by_graph": _counter_map(by_graph),
        "by_category": _counter_map(by_category),
        "changed_examples": changed_examples,
    }


def summarize_execution_comparisons(comparisons: list[dict[str, Any]]) -> dict[str, Any]:
    compared = len(comparisons)
    original_success = sum(1 for row in comparisons if row.get("original_success"))
    normalized_success = sum(1 for row in comparisons if row.get("normalized_success"))
    set_equal = sum(1 for row in comparisons if row.get("answer_set_equal"))
    multiset_equal = sum(1 for row in comparisons if row.get("answer_multiset_equal"))
    duplicate_collapse = sum(1 for row in comparisons if row.get("duplicate_collapse"))
    return {
        "compared": compared,
        "original_success": original_success,
        "normalized_success": normalized_success,
        "answer_set_equal": set_equal,
        "answer_multiset_equal": multiset_equal,
        "duplicate_collapse": duplicate_collapse,
        "answer_set_equal_rate": set_equal / compared if compared else 0.0,
        "answer_multiset_equal_rate": multiset_equal / compared if compared else 0.0,
    }


def compare_execution_results(
    original: ExecutionResult,
    normalized: ExecutionResult,
) -> dict[str, Any]:
    original_rows = [_canonical_row(row) for row in original.rows]
    normalized_rows = [_canonical_row(row) for row in normalized.rows]
    original_counts = Counter(original_rows)
    normalized_counts = Counter(normalized_rows)
    return {
        "original_success": original.success,
        "normalized_success": normalized.success,
        "original_error": original.error or "",
        "normalized_error": normalized.error or "",
        "original_row_count": len(original.rows),
        "normalized_row_count": len(normalized.rows),
        "answer_set_equal": set(original_rows) == set(normalized_rows),
        "answer_multiset_equal": original_counts == normalized_counts,
        "duplicate_collapse": (
            set(original_rows) == set(normalized_rows)
            and original_counts != normalized_counts
            and len(original_rows) > len(set(original_rows))
        ),
    }


def _return_inserted(original: str, normalized: str) -> bool:
    return bool(
        re.search(r"(?i)\bRETURN\b", original)
        and not re.search(r"(?i)\bRETURN\s+DISTINCT\b", original)
        and re.search(r"(?i)\bRETURN\s+DISTINCT\b", normalized)
    )


def _strip_distinct(query: str) -> str:
    return re.sub(r"(?i)\bRETURN\s+DISTINCT\b", "RETURN", query, count=1)


def _coalesce_spacing_changed(original: str, normalized: str) -> bool:
    if "COALESCE" not in original.upper() and "COALESCE" not in normalized.upper():
        return False
    return re.sub(r"(?i)COALESCE\(([^)]*)\)", _compact_coalesce, original) == normalized


def _compact_coalesce(match: re.Match[str]) -> str:
    return "COALESCE(" + match.group(1).replace(" ", "") + ")"


def _structural_features(record: dict[str, Any]) -> dict[str, Any]:
    if isinstance(record.get("structural_features"), dict):
        return record["structural_features"]
    validation = record.get("validation")
    if isinstance(validation, dict) and isinstance(validation.get("structural_features"), dict):
        return validation["structural_features"]
    return {}


def _counter_map(mapping: dict[str, Counter[str]]) -> dict[str, dict[str, int]]:
    return {key: dict(sorted(counter.items())) for key, counter in sorted(mapping.items())}


def _canonical_row(row: dict[str, Any]) -> str:
    return json.dumps(row, sort_keys=True, default=str, ensure_ascii=False)
