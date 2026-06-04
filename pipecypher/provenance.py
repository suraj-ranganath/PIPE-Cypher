from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_APPROVED_MODELS = {"Qwen/Qwen3.5-9B", "Qwen3.5-9B"}
FORBIDDEN_PAPER_PATTERNS = {
    "remote host leakage": re.compile(r"\bds-serv6\b", re.IGNORECASE),
    "local path leakage": re.compile(r"/Users/suraj|/home/suraj", re.IGNORECASE),
    "diagnostic run evidence": re.compile(
        r"\bsmoke\b|\bmini\b|\bmidscale\b|\btarget[-_\s]?25\b|\bablation25\b",
        re.IGNORECASE,
    ),
    "larger generation model leakage": re.compile(r"Qwen/?Qwen3\.5-35B|35B-A3B", re.IGNORECASE),
    "stale TODO wording": re.compile(r"\bTODO\b|should be promoted", re.IGNORECASE),
}
FORBIDDEN_PACKAGE_PATTERNS = {
    "remote host leakage": FORBIDDEN_PAPER_PATTERNS["remote host leakage"],
    "local path leakage": FORBIDDEN_PAPER_PATTERNS["local path leakage"],
}


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_manifest(paths: list[str | Path], *, root: str | Path = ".") -> list[dict[str, Any]]:
    root_path = Path(root).resolve()
    rows = []
    for path in sorted({Path(p) for p in paths}):
        if not path.exists() or not path.is_file():
            continue
        resolved = path.resolve()
        rows.append(
            {
                "path": str(resolved.relative_to(root_path) if resolved.is_relative_to(root_path) else path),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return rows


def scan_forbidden_text(
    paths: list[str | Path],
    *,
    patterns: dict[str, re.Pattern[str]] | None = None,
) -> list[dict[str, str]]:
    active_patterns = patterns or FORBIDDEN_PAPER_PATTERNS
    hits: list[dict[str, str]] = []
    for path in paths:
        p = Path(path)
        if not p.exists() or not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in active_patterns.items():
            match = pattern.search(text)
            if match:
                hits.append({"path": str(p), "label": label, "match": match.group(0)})
    return hits


def model_provenance_from_records(
    records_paths: list[str | Path],
    *,
    approved_models: set[str] | None = None,
) -> dict[str, Any]:
    approved = approved_models or DEFAULT_APPROVED_MODELS
    counts: Counter[str] = Counter()
    source_counts: dict[str, Counter[str]] = {}
    rows = 0
    for records_path in records_paths:
        path = Path(records_path)
        if path.is_dir():
            path = path / "records.jsonl"
        source_counts[str(path)] = Counter()
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rows += 1
            record = json.loads(line)
            model = str(record.get("model") or record.get("source", {}).get("model") or "unknown")
            counts[model] += 1
            source_counts[str(path)][model] += 1
    disallowed = {model: count for model, count in counts.items() if model not in approved}
    return {
        "records": rows,
        "approved_models": sorted(approved),
        "model_counts": dict(sorted(counts.items())),
        "disallowed_model_counts": dict(sorted(disallowed.items())),
        "pass": not disallowed and rows > 0,
        "by_source": {path: dict(sorted(counter.items())) for path, counter in source_counts.items()},
    }


def referenced_latex_inputs(tex_path: str | Path) -> list[Path]:
    tex = Path(tex_path)
    text = tex.read_text(encoding="utf-8")
    refs: list[Path] = []
    for command in ("input", "includegraphics"):
        for match in re.finditer(r"\\" + command + r"(?:\[[^\]]*\])?\{([^}]+)\}", text):
            value = match.group(1)
            if command == "input" and not Path(value).suffix:
                value = value + ".tex"
            refs.append((tex.parent / value).resolve())
    return refs


def missing_latex_inputs(tex_path: str | Path) -> list[str]:
    missing = []
    for path in referenced_latex_inputs(tex_path):
        if not path.exists():
            missing.append(str(path))
    return missing


def referenced_html_tables(paths: list[str | Path]) -> list[str]:
    """Return unique tbl-*.html references from Markdown/HTML preprint surfaces."""

    refs: set[str] = set()
    for path in paths:
        p = Path(path)
        if not p.exists() or not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        refs.update(re.findall(r"\btbl-[A-Za-z0-9_.-]+\.html\b", text))
    return sorted(refs)


def missing_html_table_references(
    paths: list[str | Path],
    *,
    html_dir: str | Path | None = None,
) -> list[str]:
    """Check optional HTML/preprint table references.

    PIPE-Cypher's submission source is LaTeX, but arXiv/preprint exports may
    reference sidecar HTML tables. This guard is intentionally opt-in through
    the verifier: if no HTML/preprint sources are supplied, it reports no
    failures.
    """

    if not paths:
        return []
    base = Path(html_dir) if html_dir is not None else Path(paths[0]).parent
    missing = []
    for ref in referenced_html_tables(paths):
        if not (base / ref).exists():
            missing.append(str(base / ref))
    return missing
