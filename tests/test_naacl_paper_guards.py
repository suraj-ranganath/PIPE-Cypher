"""Guards for the NAACL 2027 Industry draft (paper_naacl2027_industry/).

The June 2026 downstream transfer suite was invalidated (8/11 checkpoints had
HTTP 404 on every request; see experiments/snapshots/
20260604_clean_downstream_model_transfer/status.md). None of its numbers or the
narrative built on them may appear in the resubmission.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PAPER_ROOT = REPO_ROOT / "paper_naacl2027_industry"

_spec = importlib.util.spec_from_file_location(
    "emnlp_guards", REPO_ROOT / "tests" / "test_paper_reporting_guards.py"
)
_emnlp = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_emnlp)

INVALIDATED_DOWNSTREAM_PATTERNS = {
    "invalid suite run id": re.compile(r"20260604_clean_(?:downstream|control)"),
    "invalid zero-shot mean": re.compile(r"\b0\.036\b"),
    "invalid zero-shot range": re.compile(r"0\.000\s*(?:to|--|-)\s*0\.203"),
    "invalid 8/11 failure claim": re.compile(r"\b8\s*/\s*11\b|\beight of (?:the )?11\b", re.IGNORECASE),
    "invalid 3/11 benefit claim": re.compile(r"\b3\s*/\s*11\b", re.IGNORECASE),
    "invalid bimodal narrative": re.compile(r"\bbimodal\b", re.IGNORECASE),
    "invalid few-shot means": re.compile(r"\b0\.269\b|\b0\.267\b|\b0\.200\b mean"),
}


def _sources() -> list[Path]:
    if not PAPER_ROOT.exists():
        return []
    paths = [PAPER_ROOT / "main.tex"]
    paths.extend(sorted(PAPER_ROOT.glob("tables_*.tex")))
    paths.extend(sorted(PAPER_ROOT.glob("appendix_*.tex")))
    return [path for path in paths if path.exists()]


def test_naacl_paper_has_no_invalidated_downstream_evidence():
    offenders = []
    for path in _sources():
        text = path.read_text(encoding="utf-8")
        for label, pattern in INVALIDATED_DOWNSTREAM_PATTERNS.items():
            match = pattern.search(text)
            if match:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {label} matched {match.group(0)!r}")
    assert offenders == []


def test_naacl_paper_has_no_diagnostic_run_evidence():
    offenders = []
    for path in _sources():
        text = path.read_text(encoding="utf-8")
        for label, pattern in _emnlp.FORBIDDEN_PAPER_EVIDENCE_PATTERNS.items():
            match = pattern.search(text)
            if match:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {label} matched {match.group(0)!r}")
    assert offenders == []
