from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .config import RunConfig, load_config
from .experiments import summarize_records_path
from .graph_profiles import reference_schema
from .models import SchemaSummary
from .schema import load_schema


def render_benchmark_card(
    *,
    config_path: str | Path,
    records_path: str | Path | None = None,
    benchmark_dir: str | Path | None = None,
    title: str = "PIPE-Cypher Benchmark Card",
) -> str:
    config = load_config(config_path, strict=True, validate=True)
    schema = _load_schema(config)
    schema_fingerprint = _schema_fingerprint(config)
    run_summary = summarize_records_path(records_path) if records_path else None
    benchmark_summary = _load_benchmark_summary(benchmark_dir) if benchmark_dir else None

    lines = [
        f"# {title}",
        "",
        "## Intended Use",
        "",
        (
            "This benchmark is intended for evaluating natural-language-to-Cypher systems "
            "on a property-graph workload under local, auditable generation settings."
        ),
        "",
        "## Graph And Schema",
        "",
        f"- Graph profile: `{config.generation.graph_profile}`",
        f"- Schema source: `{config.paths.schema_path or 'built-in reference schema'}`",
        f"- Schema fingerprint: `{schema_fingerprint}`",
        f"- Node labels: {len(schema.labels)}",
        f"- Relationship types: {len(schema.relationship_types)}",
        f"- Relationship patterns: {len(schema.relationships)}",
        "",
        "## Generation Setup",
        "",
        f"- Generation model: `{config.models.generation_model}`",
        f"- Judge model: `{config.models.judge_model if config.judge.enabled else 'disabled'}`",
        f"- Embedding model: `{config.models.embedding_model}`",
        f"- Template source: `{config.generation.template_source}`",
        f"- Categories: {', '.join(config.generation.categories)}",
        f"- Target per category: {config.generation.target_per_category}",
        f"- Retrieval top-k: {config.generation.retrieval_top_k}",
        f"- Repair attempts: {config.generation.repair_attempts}",
        f"- Deterministic Cypher fallback: `{config.generation.deterministic_cypher_fallback}`",
        f"- Non-empty execution required: `{config.generation.require_non_empty}`",
        "",
        "## Privacy And Redaction",
        "",
        f"- Redact questions: `{config.privacy.redact_questions}`",
        f"- Redact Cypher literals: `{config.privacy.redact_cypher_literals}`",
        f"- Redact entity values: `{config.privacy.redact_entity_values}`",
        f"- Redact result samples: `{config.privacy.redact_result_samples}`",
        f"- Value sampling mode: `{config.privacy.value_sampling_mode}`",
        f"- Categorical max values: {config.privacy.categorical_max_values}",
        f"- Categorical omitted properties: {', '.join(config.privacy.categorical_omitted_properties) or 'none'}",
        "",
        "## Quality Gates",
        "",
        "- Generated Cypher is treated as unsafe until it passes read-only, syntax, schema, execution, and judge checks.",
        "- Human review is not a generation gate; post-hoc human audit may calibrate judge behavior.",
    ]
    if run_summary:
        lines.extend(["", *format_run_summary_section(run_summary)])
    if benchmark_summary:
        lines.extend(["", *format_benchmark_summary_section(benchmark_summary)])
    lines.extend(
        [
            "",
            "## Reproducibility Notes",
            "",
            f"- Config path: `{config_path}`",
            f"- Records path: `{records_path or 'not provided'}`",
            f"- Benchmark directory: `{benchmark_dir or 'not provided'}`",
            "- Use this card with the corresponding run logs, code revision, model endpoint metadata, and redacted export manifest.",
        ]
    )
    return "\n".join(lines)


def format_run_summary_section(summary: dict[str, Any]) -> list[str]:
    gates = summary.get("gates", {})
    return [
        "## Run Summary",
        "",
        f"- Run: `{summary.get('run', 'unknown')}`",
        f"- Records: {summary.get('records', 0)}",
        f"- Accepted: {summary.get('accepted', 0)}",
        f"- Acceptance rate: {summary.get('accept_rate', 0.0):.3f}",
        f"- Read-only pass count: {gates.get('read_only', 0)}",
        f"- Syntax-valid count: {gates.get('syntax_valid', 0)}",
        f"- Schema-valid count: {gates.get('schema_valid', 0)}",
        f"- Execution-success count: {gates.get('execution_success', 0)}",
        f"- Judge-pass count: {gates.get('judge_pass', 0)}",
        "",
        "Accepted by category:",
        "",
        *_format_count_table(summary.get("accepted_by_category", {}), "Category"),
    ]


def format_benchmark_summary_section(summary: dict[str, Any]) -> list[str]:
    manifest = summary.get("manifest", {})
    stats = summary.get("stats", {})
    lines = [
        "## Export Summary",
        "",
        f"- Total examples: {manifest.get('total_examples', stats.get('total', 0))}",
        f"- Split counts: `{json.dumps(manifest.get('split_counts', stats.get('by_split', {})), sort_keys=True)}`",
        f"- Export SHA-256: `{manifest.get('sha256', 'unknown')}`",
    ]
    for key, label in [
        ("by_graph", "Graph"),
        ("by_category", "Category"),
        ("by_difficulty", "Difficulty"),
    ]:
        if stats.get(key):
            lines.extend(["", f"Examples by {label.lower()}:", ""])
            lines.extend(_format_count_table(stats[key], label))
    return lines


def _load_schema(config: RunConfig) -> SchemaSummary:
    if config.paths.schema_path and Path(config.paths.schema_path).exists():
        return load_schema(config.paths.schema_path)
    return reference_schema(config.generation.graph_profile)


def _schema_fingerprint(config: RunConfig) -> str:
    if config.paths.schema_path and Path(config.paths.schema_path).exists():
        return _sha256_file(Path(config.paths.schema_path))
    schema = reference_schema(config.generation.graph_profile).to_dict()
    raw = json.dumps(schema, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _load_benchmark_summary(path: str | Path) -> dict[str, Any]:
    root = Path(path)
    manifest_path = root / "manifest.json"
    stats_path = root / "stats.json"
    return {
        "manifest": _read_json(manifest_path) if manifest_path.exists() else {},
        "stats": _read_json(stats_path) if stats_path.exists() else {},
    }


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _format_count_table(counts: dict[str, int], key_label: str) -> list[str]:
    lines = [f"| {key_label} | Count |", "|---|---:|"]
    for key, count in sorted(counts.items()):
        lines.append(f"| {key} | {count} |")
    if len(lines) == 2:
        lines.append("| none | 0 |")
    return lines
