from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


APPROVED_PAPER_MODELS = {"Qwen/Qwen3.5-9B", "Qwen3.5-9B"}
CLEAN_BENCHMARK_DIR = Path("artifacts/benchmarks/20260604_live_full_qwen9b_reviewfix")
CLEAN_EVIDENCE_MANIFEST = Path(
    "experiments/snapshots/20260604_review_remediation/"
    "clean_qwen9b_submission_evidence_manifest.json"
)
CLEAN_DOWNSTREAM_MANIFEST = Path(
    "experiments/snapshots/20260604_clean_downstream_model_transfer/"
    "downstream_control_manifest.json"
)

PAPER_TEXT_PATTERNS: dict[str, re.Pattern[str]] = {
    "remote host leakage": re.compile(r"\bds-serv6\b", re.IGNORECASE),
    "local path leakage": re.compile(r"/Users/suraj|/home/suraj", re.IGNORECASE),
    "contaminated benchmark export": re.compile(
        r"20260601_live_full_qwen9b", re.IGNORECASE
    ),
    "stale downstream snapshot": re.compile(
        r"20260603_downstream_model_transfer", re.IGNORECASE
    ),
    "stale 12-model claim": re.compile(r"\b12[-\s]?(?:model|local)\b", re.IGNORECASE),
    "stale downstream aggregate": re.compile(
        r"\b0\.(?:139|245|291|378|380)\b", re.IGNORECASE
    ),
    "larger generation or judge model": re.compile(
        r"Qwen/?Qwen3\.5-35B|35B-A3B", re.IGNORECASE
    ),
    "diagnostic run evidence": re.compile(
        r"\bsmoke\b|\bmini\b|\bmidscale\b|\btarget[-_\s]?25\b|\bablation25\b",
        re.IGNORECASE,
    ),
    "stale TODO wording": re.compile(r"\bTODO\b|should be promoted", re.IGNORECASE),
}

DEFAULT_REQUIRED_PATHS = (
    CLEAN_BENCHMARK_DIR / "manifest.json",
    CLEAN_BENCHMARK_DIR / "stats.json",
    CLEAN_BENCHMARK_DIR / "all.jsonl",
    CLEAN_BENCHMARK_DIR / "train.jsonl",
    CLEAN_BENCHMARK_DIR / "dev.jsonl",
    CLEAN_BENCHMARK_DIR / "test.jsonl",
    CLEAN_EVIDENCE_MANIFEST,
    CLEAN_DOWNSTREAM_MANIFEST,
    Path("experiments/snapshots/20260604_review_remediation/failure_taxonomy.json"),
    Path("experiments/snapshots/20260604_review_remediation/rewrite_audit.json"),
    Path("experiments/snapshots/20260604_review_remediation/governance_audit.json"),
    Path("experiments/snapshots/20260604_review_remediation/gate_impact.json"),
    Path("experiments/snapshots/20260604_review_remediation/redaction_audit.json"),
    Path("experiments/snapshots/20260604_review_remediation/runtime_accounting.json"),
    Path("experiments/snapshots/20260604_review_remediation/diversity_report.json"),
    Path(
        "experiments/snapshots/20260604_diversity_governed_target50_reviewfix/"
        "diversity_improvement_comparison.json"
    ),
    Path(
        "experiments/snapshots/20260604_clean_downstream_model_transfer/"
        "fewshot_control_summary.json"
    ),
    Path(
        "experiments/snapshots/20260604_clean_downstream_model_transfer/"
        "fewshot_control_uncertainty.json"
    ),
    Path(
        "experiments/snapshots/20260604_clean_downstream_model_transfer/"
        "fewshot_leakage_control_audit.json"
    ),
    Path(
        "experiments/snapshots/20260604_clean_downstream_model_transfer/"
        "downstream_uncertainty.json"
    ),
    Path(
        "experiments/snapshots/20260604_clean_downstream_model_transfer/"
        "downstream_error_report.json"
    ),
)


def run_paper_evidence_audit(
    *,
    root: str | Path = ".",
    paper_text_paths: list[str | Path] | None = None,
    benchmark_dir: str | Path = CLEAN_BENCHMARK_DIR,
    evidence_manifest: str | Path = CLEAN_EVIDENCE_MANIFEST,
    downstream_manifest: str | Path = CLEAN_DOWNSTREAM_MANIFEST,
    required_paths: list[str | Path] | None = None,
    expected_total: int = 3000,
    expected_splits: dict[str, int] | None = None,
    expected_by_graph: dict[str, int] | None = None,
    expected_category_count: int | None = 375,
    expected_model_records: int = 4925,
    expected_downstream_zero_runs: int = 11,
    expected_downstream_control_runs: int = 45,
    expected_downstream_rows: int = 296,
    approved_models: set[str] | None = None,
) -> dict[str, Any]:
    """Audit paper-facing evidence provenance for the final submission package.

    This guard is intentionally stricter than a generic text scan. It checks the
    current clean benchmark export, evidence manifest, and downstream control
    manifest so old contaminated exports or stale model-count claims fail before
    they can re-enter paper tables.
    """

    base = Path(root)
    approved = approved_models or APPROVED_PAPER_MODELS
    issues: list[dict[str, str]] = []
    text_hits = _scan_text_sources(
        [_resolve(base, path) for path in (paper_text_paths or default_paper_text_paths(base))]
    )
    for hit in text_hits:
        _issue(issues, "forbidden_text", f"{hit['label']}: {hit['match']}", hit["path"])

    for path in required_paths if required_paths is not None else DEFAULT_REQUIRED_PATHS:
        resolved = _resolve(base, path)
        if not resolved.exists():
            _issue(issues, "missing_required_artifact", "required artifact is missing", resolved)

    benchmark_report = _audit_benchmark(
        _resolve(base, benchmark_dir),
        issues,
        expected_total=expected_total,
        expected_splits=expected_splits or {"train": 2408, "dev": 296, "test": 296},
        expected_by_graph=expected_by_graph or {"finbench": 2000, "snb": 1000},
        expected_category_count=expected_category_count,
    )
    evidence_report = _audit_evidence_manifest(
        _resolve(base, evidence_manifest),
        issues,
        approved_models=approved,
        expected_model_records=expected_model_records,
    )
    downstream_report = _audit_downstream_manifest(
        _resolve(base, downstream_manifest),
        issues,
        expected_zero_runs=expected_downstream_zero_runs,
        expected_control_runs=expected_downstream_control_runs,
        expected_rows=expected_downstream_rows,
    )

    return {
        "pass": not issues,
        "issues": issues,
        "text_hits": text_hits,
        "benchmark": benchmark_report,
        "evidence_manifest": evidence_report,
        "downstream_manifest": downstream_report,
    }


def default_paper_text_paths(root: str | Path = ".") -> list[Path]:
    base = Path(root)
    paper_root = base / "paper_emnlp2026_industry"
    paths = [
        paper_root / "main_acl.tex",
        paper_root / "main.tex",
        paper_root / "paper.md",
        paper_root / "README.md",
        paper_root / "reproducibility_README.md",
        base / "knowledge_base" / "claim_evidence_map.yaml",
        base / "knowledge_base" / "review_response_matrix.md",
    ]
    paths.extend(sorted(paper_root.glob("tables_*.tex")))
    paths.extend(sorted(paper_root.glob("appendix_*.tex")))
    return [path for path in paths if path.exists()]


def format_paper_evidence_audit(report: dict[str, Any]) -> str:
    lines = [
        "# Paper Evidence Provenance Audit",
        "",
        f"- Status: {'pass' if report.get('pass') else 'fail'}",
        f"- Issues: {len(report.get('issues', []))}",
        f"- Forbidden text hits: {len(report.get('text_hits', []))}",
    ]
    benchmark = report.get("benchmark") or {}
    evidence = report.get("evidence_manifest") or {}
    downstream = report.get("downstream_manifest") or {}
    if benchmark:
        lines.append(f"- Benchmark examples: {benchmark.get('total_examples')}")
    if evidence:
        lines.append(f"- Evidence model counts: `{evidence.get('model_counts')}`")
    if downstream:
        lines.append(
            "- Downstream complete runs: "
            f"{downstream.get('zero_runs')} zero, {downstream.get('control_runs')} controls"
        )
    if report.get("issues"):
        lines.append("")
        lines.append("Issues:")
        for issue in report["issues"]:
            location = f" ({issue['path']})" if issue.get("path") else ""
            lines.append(f"- {issue['code']}: {issue['message']}{location}")
    return "\n".join(lines)


def _audit_benchmark(
    benchmark_dir: Path,
    issues: list[dict[str, str]],
    *,
    expected_total: int,
    expected_splits: dict[str, int],
    expected_by_graph: dict[str, int],
    expected_category_count: int | None,
) -> dict[str, Any]:
    manifest = _read_json(benchmark_dir / "manifest.json", issues)
    stats = _read_json(benchmark_dir / "stats.json", issues)
    report: dict[str, Any] = {}
    if manifest:
        report["total_examples"] = manifest.get("total_examples")
        if manifest.get("total_examples") != expected_total:
            _issue(
                issues,
                "benchmark_total_mismatch",
                f"expected {expected_total}, found {manifest.get('total_examples')}",
                benchmark_dir / "manifest.json",
            )
        if manifest.get("split_counts") != expected_splits:
            _issue(
                issues,
                "benchmark_split_mismatch",
                f"expected {expected_splits}, found {manifest.get('split_counts')}",
                benchmark_dir / "manifest.json",
            )
        if "20260601_live_full_qwen9b" in json.dumps(manifest, sort_keys=True):
            _issue(
                issues,
                "benchmark_manifest_uses_old_export",
                "manifest still references the contaminated June 1 export",
                benchmark_dir / "manifest.json",
            )
    if stats:
        report["stats_total"] = stats.get("total")
        if stats.get("total") != expected_total:
            _issue(
                issues,
                "stats_total_mismatch",
                f"expected {expected_total}, found {stats.get('total')}",
                benchmark_dir / "stats.json",
            )
        if stats.get("by_graph") != expected_by_graph:
            _issue(
                issues,
                "graph_count_mismatch",
                f"expected {expected_by_graph}, found {stats.get('by_graph')}",
                benchmark_dir / "stats.json",
            )
        if stats.get("by_split") != expected_splits:
            _issue(
                issues,
                "stats_split_mismatch",
                f"expected {expected_splits}, found {stats.get('by_split')}",
                benchmark_dir / "stats.json",
            )
        gates = stats.get("gate_counts") or {}
        for gate in ("accepted", "read_only", "syntax_valid", "schema_valid", "execution_success", "judge_pass"):
            if gates.get(gate) != expected_total:
                _issue(
                    issues,
                    "gate_count_mismatch",
                    f"{gate} expected {expected_total}, found {gates.get(gate)}",
                    benchmark_dir / "stats.json",
                )
        if expected_category_count is not None:
            for category, count in (stats.get("by_category") or {}).items():
                if count != expected_category_count:
                    _issue(
                        issues,
                        "category_count_mismatch",
                        f"{category} expected {expected_category_count}, found {count}",
                        benchmark_dir / "stats.json",
                    )
    for filename, expected in {
        "all.jsonl": expected_total,
        **{f"{split}.jsonl": count for split, count in expected_splits.items()},
    }.items():
        path = benchmark_dir / filename
        if path.exists():
            count = _line_count(path)
            if count != expected:
                _issue(
                    issues,
                    "benchmark_jsonl_count_mismatch",
                    f"{filename} expected {expected}, found {count}",
                    path,
                )
    return report


def _audit_evidence_manifest(
    path: Path,
    issues: list[dict[str, str]],
    *,
    approved_models: set[str],
    expected_model_records: int,
) -> dict[str, Any]:
    data = _read_json(path, issues)
    if not data:
        return {}
    if not data.get("paper_ready"):
        _issue(issues, "evidence_manifest_not_paper_ready", "paper_ready is not true", path)
    if data.get("missing_artifacts"):
        _issue(
            issues,
            "evidence_manifest_missing_artifacts",
            f"missing artifacts: {data.get('missing_artifacts')}",
            path,
        )
    model = data.get("model_provenance") or {}
    counts = model.get("model_counts") or {}
    disallowed = {
        name: count
        for name, count in counts.items()
        if name not in approved_models
    }
    if not model.get("pass"):
        _issue(issues, "model_provenance_failed", "manifest model_provenance.pass is false", path)
    if disallowed or model.get("disallowed_model_counts"):
        _issue(
            issues,
            "disallowed_generation_or_judge_model",
            f"disallowed model counts: {disallowed or model.get('disallowed_model_counts')}",
            path,
        )
    if model.get("records") != expected_model_records:
        _issue(
            issues,
            "model_record_count_mismatch",
            f"expected {expected_model_records}, found {model.get('records')}",
            path,
        )
    artifact_text = json.dumps(data.get("artifacts", []), sort_keys=True)
    if "20260601_live_full_qwen9b" in artifact_text:
        _issue(
            issues,
            "evidence_manifest_uses_old_export",
            "evidence artifact list references the contaminated June 1 export",
            path,
        )
    return {
        "paper_ready": data.get("paper_ready"),
        "records": model.get("records"),
        "model_counts": counts,
        "missing_artifacts": data.get("missing_artifacts", []),
    }


def _audit_downstream_manifest(
    path: Path,
    issues: list[dict[str, str]],
    *,
    expected_zero_runs: int,
    expected_control_runs: int,
    expected_rows: int,
) -> dict[str, Any]:
    data = _read_json(path, issues)
    if not data:
        return {}
    observed = data.get("observed") or {}
    expected = data.get("expected") or {}
    if observed.get("zero_runs") != expected_zero_runs:
        _issue(
            issues,
            "downstream_zero_count_mismatch",
            f"expected {expected_zero_runs}, found {observed.get('zero_runs')}",
            path,
        )
    if observed.get("control_runs") != expected_control_runs:
        _issue(
            issues,
            "downstream_control_count_mismatch",
            f"expected {expected_control_runs}, found {observed.get('control_runs')}",
            path,
        )
    if expected.get("rows_per_run") != expected_rows:
        _issue(
            issues,
            "downstream_expected_rows_mismatch",
            f"expected {expected_rows}, found {expected.get('rows_per_run')}",
            path,
        )
    if not observed.get("all_complete") or data.get("issues"):
        _issue(
            issues,
            "downstream_manifest_incomplete",
            f"all_complete={observed.get('all_complete')}, issues={data.get('issues')}",
            path,
        )
    for run in [*(data.get("zero_runs") or []), *(data.get("control_runs") or [])]:
        for name, meta in (run.get("files") or {}).items():
            if name.endswith(".jsonl") and meta.get("line_count") != expected_rows:
                _issue(
                    issues,
                    "downstream_jsonl_count_mismatch",
                    f"{run.get('run_id')} {name} expected {expected_rows}, found {meta.get('line_count')}",
                    path,
                )
    return {
        "zero_runs": observed.get("zero_runs"),
        "control_runs": observed.get("control_runs"),
        "all_complete": observed.get("all_complete"),
    }


def _scan_text_sources(paths: list[Path]) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in PAPER_TEXT_PATTERNS.items():
            match = pattern.search(text)
            if match:
                hits.append({"path": str(path), "label": label, "match": match.group(0)})
    return hits


def _read_json(path: Path, issues: list[dict[str, str]]) -> dict[str, Any]:
    if not path.exists():
        _issue(issues, "missing_json", "JSON artifact is missing", path)
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _issue(issues, "invalid_json", str(exc), path)
        return {}
    if not isinstance(data, dict):
        _issue(issues, "invalid_json_shape", "expected a JSON object", path)
        return {}
    return data


def _line_count(path: Path) -> int:
    with path.open(encoding="utf-8") as handle:
        return sum(1 for _ in handle)


def _resolve(root: Path, path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else root / p


def _issue(
    issues: list[dict[str, str]],
    code: str,
    message: str,
    path: str | Path | None = None,
) -> None:
    row = {"code": code, "message": message}
    if path is not None:
        row["path"] = str(path)
    issues.append(row)
