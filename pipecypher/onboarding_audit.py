from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .artifact_snapshot import sha256_file
from .io import read_jsonl
from .models import DEFAULT_CATEGORIES
from .schema_templates import SCHEMA_TEMPLATE_KIND


ONBOARDING_SNAPSHOT_VERSION = "1.0"


def redact_runtime_log(text: str) -> str:
    """Remove value-bearing Cypher snippets from runtime logs before tracking."""

    lines: list[str] = []
    for line in text.splitlines():
        if "for query:" in line:
            lines.append(
                'Received notification from DBMS server: [REDACTED_NOTIFICATION] '
                'for query: "[REDACTED_CYPHER]"'
            )
        else:
            lines.append(line)
    redacted = "\n".join(lines)
    if text.endswith("\n"):
        redacted += "\n"
    redacted = re.sub(
        r"(?i)(query|cypher)=('|\")(?:\\.|(?!\2).)*\2",
        r"\1=[REDACTED_CYPHER]",
        redacted,
    )
    redacted = re.sub(r"'[^'\n]{1,200}'", "'[REDACTED_LITERAL]'", redacted)
    return redacted


def build_onboarding_summary(
    rows: list[dict[str, Any]],
    *,
    run_name: str,
    target_per_category: int,
    expected_categories: list[str] | None = None,
    graph_profile: str = "",
    metadata: dict[str, Any] | None = None,
    records_path: str | Path | None = None,
    summary_present: bool = False,
    collected_at: str | None = None,
) -> dict[str, Any]:
    categories = expected_categories or list(DEFAULT_CATEGORIES)
    total = len(rows)
    accepted_rows = [row for row in rows if row.get("accepted")]
    accepted_total = len(accepted_rows)
    records_by_category = _count_by(rows, "category")
    accepted_by_category = _count_by(accepted_rows, "category")
    failure_by_category = _failure_counts(rows)
    gate_counts = _gate_counts(rows)
    accepted_gate_counts = _gate_counts(accepted_rows)
    category_coverage = {
        category: {
            "accepted": int(accepted_by_category.get(category, 0)),
            "target": int(target_per_category),
            "at_target": int(accepted_by_category.get(category, 0)) >= target_per_category,
        }
        for category in categories
    }
    difficulty_counts = _difficulty_counts(rows)
    accepted_difficulty_counts = _difficulty_counts(accepted_rows)
    schema_template_accepts = Counter()
    legacy_schema_template_accepts = Counter()
    for row in accepted_rows:
        category = str(row.get("category") or "unknown")
        if _has_schema_template_metadata(row):
            schema_template_accepts[category] += 1
        elif _legacy_schema_template_inference(row):
            legacy_schema_template_accepts[category] += 1

    audit = _readiness_audit(
        categories=categories,
        accepted_by_category=accepted_by_category,
        target_per_category=target_per_category,
        metadata=metadata or {},
        records_present=total > 0,
        summary_present=summary_present,
    )
    records_digest = ""
    if records_path:
        path = Path(records_path)
        if path.exists() and path.is_file():
            records_digest = sha256_file(path)

    return {
        "snapshot_version": ONBOARDING_SNAPSHOT_VERSION,
        "collected_at": collected_at or datetime.now(timezone.utc).isoformat(),
        "run_name": run_name,
        "graph_profile": graph_profile,
        "target_per_category": target_per_category,
        "expected_categories": categories,
        "records": total,
        "accepted": accepted_total,
        "accept_rate": accepted_total / total if total else 0.0,
        "records_by_category": dict(sorted(records_by_category.items())),
        "accepted_by_category": dict(sorted(accepted_by_category.items())),
        "category_coverage": category_coverage,
        "categories_at_target": sum(1 for row in category_coverage.values() if row["at_target"]),
        "failure_by_category": {
            category: dict(counts.most_common())
            for category, counts in sorted(failure_by_category.items())
        },
        "gate_counts": dict(sorted(gate_counts.items())),
        "gate_rates": _rates(gate_counts, total),
        "accepted_gate_counts": dict(sorted(accepted_gate_counts.items())),
        "accepted_gate_rates": _rates(accepted_gate_counts, accepted_total),
        "difficulty_counts": dict(sorted(difficulty_counts.items())),
        "accepted_difficulty_counts": dict(sorted(accepted_difficulty_counts.items())),
        "schema_template_accepts_by_category": dict(sorted(schema_template_accepts.items())),
        "legacy_inferred_schema_template_accepts_by_category": dict(
            sorted(legacy_schema_template_accepts.items())
        ),
        "empty_result_diagnostics": _empty_result_diagnostics(rows),
        "audit": audit,
        "metadata": dict(sorted((metadata or {}).items())),
        "source_records": {
            "path": str(records_path) if records_path else "",
            "sha256": records_digest,
            "tracked": False,
            "privacy_note": (
                "Raw records may contain questions, Cypher literals, entity values, and "
                "execution samples. Keep them in ignored artifacts and share only this "
                "sanitized aggregate summary unless a redacted export is explicitly created."
            ),
        },
    }


def summarize_onboarding_records_path(
    path: str | Path,
    *,
    target_per_category: int,
    expected_categories: list[str] | None = None,
    graph_profile: str = "",
    metadata: dict[str, Any] | None = None,
    summary_present: bool | None = None,
) -> dict[str, Any]:
    records_path = _records_path(path)
    run_name = records_path.parent.name
    return build_onboarding_summary(
        read_jsonl(records_path),
        run_name=run_name,
        target_per_category=target_per_category,
        expected_categories=expected_categories,
        graph_profile=graph_profile,
        metadata=metadata,
        records_path=records_path,
        summary_present=(records_path.parent / "summary.txt").exists()
        if summary_present is None
        else summary_present,
    )


def render_onboarding_summary_markdown(summary: dict[str, Any]) -> str:
    audit = summary.get("audit", {})
    lines = [
        f"# Enterprise Onboarding Run: {summary.get('run_name', '')}",
        "",
        "This is a sanitized aggregate snapshot. It intentionally excludes raw "
        "questions, Cypher, entity values, and execution result samples.",
        "",
        "## Run",
        "",
        f"- Graph profile: `{summary.get('graph_profile') or 'unknown'}`",
        f"- Target per category: `{summary.get('target_per_category')}`",
        f"- Records: `{summary.get('records')}`",
        f"- Accepted: `{summary.get('accepted')}`",
        f"- Accept rate: `{float(summary.get('accept_rate', 0.0)):.3f}`",
        f"- Categories at target: `{summary.get('categories_at_target')}/"
        f"{len(summary.get('expected_categories', []))}`",
        f"- Ready for paper promotion: `{str(audit.get('ready_for_paper_promotion')).lower()}`",
        "",
    ]
    metadata = summary.get("metadata", {})
    if metadata:
        lines.extend(["## Metadata", ""])
        for key, value in sorted(metadata.items()):
            lines.append(f"- `{key}`: `{value}`")
        lines.append("")
    lines.extend(
        [
        "## Category Coverage",
        "",
        "| Category | Accepted | Target | At Target |",
        "|---|---:|---:|---|",
        ]
    )
    for category, row in summary.get("category_coverage", {}).items():
        lines.append(
            f"| {category} | {row.get('accepted', 0)} | {row.get('target', 0)} | "
            f"{str(row.get('at_target')).lower()} |"
        )
    lines.extend(
        [
            "",
            "## Gate Rates",
            "",
            "| Gate | Count | Rate |",
            "|---|---:|---:|",
        ]
    )
    for gate, count in summary.get("gate_counts", {}).items():
        rate = summary.get("gate_rates", {}).get(gate, 0.0)
        lines.append(f"| {gate} | {count} | {float(rate):.3f} |")
    lines.extend(["", "## Failure Taxonomy", "", "| Category | Failure | Count |", "|---|---|---:|"])
    failures = summary.get("failure_by_category", {})
    if failures:
        for category, counts in failures.items():
            for reason, count in counts.items():
                lines.append(f"| {category} | {reason} | {count} |")
    else:
        lines.append("| none | none | 0 |")
    if summary.get("schema_template_accepts_by_category"):
        lines.extend(["", "## Schema-Derived Template Evidence", ""])
        lines.append(
            "Accepted examples with explicit schema-template metadata: "
            f"`{json.dumps(summary['schema_template_accepts_by_category'], sort_keys=True)}`."
        )
    if summary.get("legacy_inferred_schema_template_accepts_by_category"):
        lines.extend(["", "## Legacy Schema-Derived Template Inference", ""])
        lines.append(
            "This run predates template metadata logging, so these counts are inferred from "
            "the deterministic schema-derived question style and should be treated as "
            "diagnostic provenance rather than a row-level metadata field: "
            f"`{json.dumps(summary['legacy_inferred_schema_template_accepts_by_category'], sort_keys=True)}`."
        )
    issues = audit.get("issues", [])
    if issues:
        lines.extend(["", "## Audit Issues", ""])
        lines.extend(f"- {issue}" for issue in issues)
    return "\n".join(lines) + "\n"


def build_onboarding_collection_manifest(
    *,
    host: str,
    remote_root: str,
    run_prefix: str,
    snapshot_dir: str | Path,
    local_run_root: str | Path,
    run_name: str,
    metadata: dict[str, Any],
    log_file: str,
    collected_at: str | None = None,
) -> dict[str, Any]:
    snapshot = Path(snapshot_dir)
    run_dir = Path(local_run_root) / run_name
    return {
        "collected_at": collected_at or datetime.now(timezone.utc).isoformat(),
        "host": host,
        "remote_root": remote_root,
        "run_prefix": run_prefix,
        "run_name": run_name,
        "metadata": dict(sorted(metadata.items())),
        "remote_log_file": log_file,
        "runs": {
            run_name: _checksums_for_paths(run_dir, ["records.jsonl", "summary.txt"]),
        },
        "snapshot_files": _checksums_for_paths(
            snapshot,
            [
                "remote_run.log",
                "onboarding_summary.json",
                "onboarding_summary.md",
                "collection_manifest.json",
            ],
        ),
    }


def _records_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_dir():
        candidate = candidate / "records.jsonl"
    return candidate


def _count_by(rows: list[dict[str, Any]], key: str) -> Counter[str]:
    return Counter(str(row.get(key) or "unknown") for row in rows)


def _difficulty_counts(rows: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        validation = row.get("validation") or {}
        features = validation.get("structural_features") or {}
        counts[str(features.get("difficulty") or "unknown")] += 1
    return counts


def _gate_counts(rows: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        validation = row.get("validation") or {}
        execution = row.get("execution") or {}
        judge = row.get("judge") or {}
        if validation.get("read_only"):
            counts["read_only"] += 1
        if validation.get("syntax_valid"):
            counts["syntax_valid"] += 1
        if validation.get("schema_valid"):
            counts["schema_valid"] += 1
        if execution.get("success"):
            counts["execution_success"] += 1
            if execution.get("rows"):
                counts["non_empty_execution"] += 1
        if judge.get("passed"):
            counts["judge_pass"] += 1
    return counts


def _rates(counts: Counter[str], denominator: int) -> dict[str, float]:
    return {
        key: (value / denominator if denominator else 0.0)
        for key, value in sorted(counts.items())
    }


def _failure_counts(rows: list[dict[str, Any]]) -> dict[str, Counter[str]]:
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        if row.get("accepted"):
            continue
        category = str(row.get("category") or "unknown")
        counts[category][_failure_reason(row)] += 1
    return counts


def _failure_reason(row: dict[str, Any]) -> str:
    judge = row.get("judge") or {}
    reason = str(judge.get("failure_reason") or "").strip()
    if reason:
        return reason
    validation = row.get("validation") or {}
    issues = validation.get("issues") or []
    if issues:
        first = issues[0] or {}
        return str(first.get("code") or first.get("message") or "validation issue")
    execution = row.get("execution") or {}
    error = str(execution.get("error") or "").strip()
    return error or "unknown"


def _empty_result_diagnostics(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        diagnostic = row.get("empty_result_diagnostic") or {}
        if diagnostic:
            counts[str(diagnostic.get("classification") or "unknown")] += 1
    return dict(sorted(counts.items()))


def _readiness_audit(
    *,
    categories: list[str],
    accepted_by_category: Counter[str],
    target_per_category: int,
    metadata: dict[str, Any],
    records_present: bool,
    summary_present: bool,
) -> dict[str, Any]:
    issues: list[str] = []
    if not records_present:
        issues.append("records.jsonl is missing or empty")
    if not summary_present:
        issues.append("remote summary.txt was not collected")
    if target_per_category < 50:
        issues.append("target_per_category is below the research-quality minimum of 50")
    missing_categories = [
        category
        for category in categories
        if int(accepted_by_category.get(category, 0)) < target_per_category
    ]
    for key in ("generation_model", "judge_model", "code_revision", "run_seed"):
        if not metadata.get(key):
            issues.append(f"metadata missing {key}")
    if missing_categories:
        issues.append("categories below target: " + ", ".join(missing_categories))
    return {
        "ready_for_paper_promotion": not issues,
        "target_per_category": target_per_category,
        "missing_categories": missing_categories,
        "issues": issues,
    }


def _has_schema_template_metadata(row: dict[str, Any]) -> bool:
    metadata = row.get("template_metadata") or {}
    return bool(metadata.get(SCHEMA_TEMPLATE_KIND))


def _legacy_schema_template_inference(row: dict[str, Any]) -> bool:
    question = str(row.get("question") or "")
    cypher = str(row.get("cypher") or "")
    return (
        " through :" in question
        and (
            " records are linked from " in question
            or " records link to " in question
            or " linked to the most " in question
            or " are not linked " in question
            or " do not link " in question
        )
        and "MATCH" in cypher
    )


def _checksums_for_paths(base: Path, names: list[str]) -> dict[str, dict[str, Any]]:
    checksums: dict[str, dict[str, Any]] = {}
    for name in names:
        path = base / name
        if path.exists() and path.is_file():
            checksums[name] = {
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
    return checksums
