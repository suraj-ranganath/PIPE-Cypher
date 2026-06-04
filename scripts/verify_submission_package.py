#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.provenance import (
    DEFAULT_APPROVED_MODELS,
    FORBIDDEN_PACKAGE_PATTERNS,
    missing_html_table_references,
    missing_latex_inputs,
    model_provenance_from_records,
    scan_forbidden_text,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify that a PIPE-Cypher submission package is self-contained and provenance-clean."
    )
    parser.add_argument("--paper-tex", default="paper_emnlp2026_industry/main_acl.tex")
    parser.add_argument("--package-dir", default="")
    parser.add_argument(
        "--html-source",
        action="append",
        default=[],
        help="Optional Markdown/HTML preprint source that references tbl-*.html files.",
    )
    parser.add_argument(
        "--html-dir",
        default="",
        help="Directory that should contain referenced tbl-*.html files when an HTML export exists.",
    )
    parser.add_argument(
        "--evidence-manifest",
        action="append",
        default=[],
        help="JSON evidence manifest that must exist and parse.",
    )
    parser.add_argument(
        "--records",
        nargs="*",
        action="append",
        default=[],
        help="Record directories or records.jsonl paths. May be supplied multiple times.",
    )
    parser.add_argument("--approved-model", action="append", default=[])
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args()

    approved = set(args.approved_model or DEFAULT_APPROVED_MODELS)
    report = verify_submission(
        paper_tex=Path(args.paper_tex),
        package_dir=Path(args.package_dir) if args.package_dir else None,
        records=[Path(path) for path in _flatten(args.records)],
        approved_models=approved,
        html_sources=[Path(path) for path in args.html_source],
        html_dir=Path(args.html_dir) if args.html_dir else None,
        evidence_manifests=[Path(path) for path in args.evidence_manifest],
    )
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(_format_report(report))
    if not report["pass"]:
        raise SystemExit(1)


def verify_submission(
    *,
    paper_tex: Path,
    package_dir: Path | None,
    records: list[Path],
    approved_models: set[str],
    html_sources: list[Path] | None = None,
    html_dir: Path | None = None,
    evidence_manifests: list[Path] | None = None,
) -> dict[str, object]:
    required_roots = ["pipecypher", "scripts", "configs", "tests", "paper_emnlp2026_industry"]
    base = package_dir or PROJECT_ROOT
    effective_paper_tex = paper_tex if paper_tex.is_absolute() else base / paper_tex
    missing_roots = [name for name in required_roots if not (base / name).exists()]
    missing_inputs = missing_latex_inputs(effective_paper_tex)
    paper_sources = [effective_paper_tex]
    paper_sources.extend(sorted(effective_paper_tex.parent.glob("tables_*.tex")))
    paper_sources.extend(sorted(effective_paper_tex.parent.glob("appendix_*.tex")))
    forbidden_hits = scan_forbidden_text(paper_sources)
    package_forbidden_hits = (
        scan_forbidden_text(
            _package_text_files(base),
            patterns=FORBIDDEN_PACKAGE_PATTERNS,
        )
        if package_dir
        else []
    )
    missing_html_tables = missing_html_table_references(
        html_sources or [],
        html_dir=html_dir,
    )
    evidence_report = _verify_evidence_manifests(evidence_manifests or [])
    model_report = (
        model_provenance_from_records(records, approved_models=approved_models)
        if records
        else {"pass": True, "records": 0, "model_counts": {}, "disallowed_model_counts": {}}
    )
    failures = []
    if missing_roots:
        failures.append(f"missing package roots: {', '.join(missing_roots)}")
    if missing_inputs:
        failures.append(f"missing LaTeX inputs: {len(missing_inputs)}")
    if forbidden_hits:
        failures.append(f"forbidden paper text hits: {len(forbidden_hits)}")
    if package_forbidden_hits:
        failures.append(f"forbidden package text hits: {len(package_forbidden_hits)}")
    if missing_html_tables:
        failures.append(f"missing HTML table references: {len(missing_html_tables)}")
    if evidence_report["missing"] or evidence_report["invalid"]:
        failures.append("evidence manifests missing or invalid")
    if not model_report.get("pass", False):
        failures.append("model provenance includes disallowed or missing records")
    return {
        "pass": not failures,
        "failures": failures,
        "package_dir": str(base),
        "missing_roots": missing_roots,
        "missing_latex_inputs": missing_inputs,
        "missing_html_tables": missing_html_tables,
        "evidence_manifests": evidence_report,
        "forbidden_hits": forbidden_hits,
        "package_forbidden_hits": package_forbidden_hits,
        "model_provenance": model_report,
    }


def _format_report(report: dict[str, object]) -> str:
    lines = [
        "# Submission Package Verification",
        "",
        f"- Status: {'pass' if report['pass'] else 'fail'}",
        f"- Package dir: `{report['package_dir']}`",
        f"- Missing roots: {len(report['missing_roots'])}",
        f"- Missing LaTeX inputs: {len(report['missing_latex_inputs'])}",
        f"- Missing HTML tables: {len(report.get('missing_html_tables', []))}",
        f"- Evidence manifest problems: {len(report.get('evidence_manifests', {}).get('missing', [])) + len(report.get('evidence_manifests', {}).get('invalid', []))}",
        f"- Forbidden text hits: {len(report['forbidden_hits'])}",
        f"- Package forbidden text hits: {len(report.get('package_forbidden_hits', []))}",
        "",
    ]
    model = report["model_provenance"]
    if isinstance(model, dict):
        lines.append(f"- Model provenance pass: {model.get('pass')}")
        lines.append(f"- Model counts: `{model.get('model_counts')}`")
    failures = report.get("failures") or []
    if failures:
        lines.append("")
        lines.append("Failures:")
        lines.extend(f"- {failure}" for failure in failures)
    return "\n".join(lines)


def _verify_evidence_manifests(paths: list[Path]) -> dict[str, object]:
    missing: list[str] = []
    invalid: list[str] = []
    present: list[str] = []
    for path in paths:
        if not path.exists():
            missing.append(str(path))
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            invalid.append(str(path))
            continue
        present.append(str(path))
    return {"present": present, "missing": missing, "invalid": invalid}


def _flatten(groups: list[list[str]]) -> list[str]:
    return [item for group in groups for item in group]


def _package_text_files(package_dir: Path) -> list[Path]:
    suffixes = {".py", ".md", ".tex", ".bib", ".yaml", ".yml", ".json", ".sh", ".toml"}
    ignored_parts = {"__pycache__", ".pytest_cache", ".ruff_cache"}
    files = []
    for path in package_dir.rglob("*"):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        if any(part in ignored_parts for part in path.parts):
            continue
        files.append(path)
    return files


if __name__ == "__main__":
    main()
