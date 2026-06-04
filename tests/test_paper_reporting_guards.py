from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts.render_ablation_paper_table import validate_paper_target


REPO_ROOT = Path(__file__).resolve().parents[1]
PAPER_ROOT = REPO_ROOT / "paper_emnlp2026_industry"

FORBIDDEN_PAPER_EVIDENCE_PATTERNS = {
    "smoke evidence": re.compile(r"(?:^|[^A-Za-z])smoke(?:$|[^A-Za-z])", re.IGNORECASE),
    "mini evidence": re.compile(r"(?:^|[^A-Za-z])mini(?:$|[^A-Za-z])", re.IGNORECASE),
    "midscale evidence": re.compile(r"(?:^|[^A-Za-z])midscale(?:$|[^A-Za-z])", re.IGNORECASE),
    "target-five evidence": re.compile(r"\btarget[-_\s]?five\b|\btarget5\b|\btarget[-_\s]?5\b", re.IGNORECASE),
    "target-25 evidence": re.compile(r"\btarget[-_\s]?25\b|\bablation25\b", re.IGNORECASE),
    "deprecated smoke table": re.compile(r"\btables_smoke\b", re.IGNORECASE),
    "deprecated mini table": re.compile(r"\btables_mini_results\b", re.IGNORECASE),
    "deprecated midscale table": re.compile(r"\btables_midscale_results\b", re.IGNORECASE),
    "deprecated target-five table": re.compile(r"\btables_ablation5_results\b", re.IGNORECASE),
    "deprecated target-25 table": re.compile(r"\btables_ablation25_results\b", re.IGNORECASE),
    "mini benchmark artifact": re.compile(r"\blive_all_category_mini\b", re.IGNORECASE),
    "midscale benchmark artifact": re.compile(r"\blive_midscale\b", re.IGNORECASE),
    "remote host leakage": re.compile(r"\bds-serv6\b", re.IGNORECASE),
    "stale prompt-plan wording": re.compile(
        r"Prompt-profile plan|should be promoted", re.IGNORECASE
    ),
    "ambiguous Mind the Query model endpoint": re.compile(
        r"Model endpoint\s*&\s*Gemini for generation", re.IGNORECASE
    ),
    "incorrect downstream Qwen scope": re.compile(
        r"All reported generation,\s*judging,\s*and downstream evaluation runs use",
        re.IGNORECASE,
    ),
    "unconstrained baseline without attempts": re.compile(
        r"Unconstrained LLM\s*&\s*(?:FinBench|SNB)\s*&\s*0\s*&\s*0\s*&\s*0\.000",
        re.IGNORECASE,
    ),
}


def test_paper_reporting_surfaces_do_not_include_diagnostic_runs():
    offenders: list[str] = []
    for path in _paper_reporting_sources():
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(REPO_ROOT)
        for label, pattern in FORBIDDEN_PAPER_EVIDENCE_PATTERNS.items():
            match = pattern.search(text)
            if match:
                offenders.append(f"{rel}: {label} matched {match.group(0)!r}")

    assert offenders == []


def test_paper_reporting_filenames_do_not_include_diagnostic_runs():
    offenders: list[str] = []
    for path in _paper_reporting_artifacts():
        rel = str(path.relative_to(REPO_ROOT))
        for label, pattern in FORBIDDEN_PAPER_EVIDENCE_PATTERNS.items():
            match = pattern.search(rel)
            if match:
                offenders.append(f"{rel}: {label} matched {match.group(0)!r}")

    assert offenders == []


def test_appendix_stays_in_acl_two_column_mode():
    offenders: list[str] = []
    for name in ("main_acl.tex", "main.tex"):
        path = PAPER_ROOT / name
        text = path.read_text(encoding="utf-8")
        appendix_match = re.search(r"\\appendix(?P<body>.*)", text, re.DOTALL)
        if appendix_match and r"\onecolumn" in appendix_match.group("body"):
            offenders.append(name)

    assert offenders == []


def test_appendix_result_tables_use_venue_compliant_placement():
    appendix_table_names = {
        "tables_ablation_results.tex",
        "tables_ablation_quality.tex",
        "tables_ablation_comparison.tex",
        "tables_failure_taxonomy.tex",
        "tables_graph_statistics.tex",
        "tables_icij_onboarding.tex",
        "tables_category_crosswalk.tex",
        "tables_downstream_fewshot_controls.tex",
        "tables_downstream_fewshot_control_uncertainty.tex",
        "tables_fewshot_leakage_controls.tex",
        "tables_downstream_error_taxonomy.tex",
        "tables_supported_text_metrics.tex",
        "tables_diversity.tex",
        "tables_diversity_improvement.tex",
        "tables_strategy_diagnostics.tex",
        "tables_validator_cascade.tex",
        "tables_prompt_refinement.tex",
        "tables_effort_automation.tex",
        "tables_judge_audit_coverage.tex",
    }
    allowed_full_width = {
        "tables_downstream_fewshot_controls.tex",
        "tables_supported_text_metrics.tex",
    }
    offenders: list[str] = []
    for name in appendix_table_names:
        path = PAPER_ROOT / name
        text = path.read_text(encoding="utf-8")
        if r"\begin{table*}" in text and name not in allowed_full_width:
            offenders.append(name)
        if r"\begin{table}[t]" in text:
            offenders.append(name)

    assert offenders == []


def test_legacy_paper_ablation_renderer_refuses_sub50_targets_by_default():
    with pytest.raises(SystemExit, match="refusing to render paper ablation table below"):
        validate_paper_target(25, allow_diagnostic_target=False)

    validate_paper_target(25, allow_diagnostic_target=True)
    validate_paper_target(50, allow_diagnostic_target=False)


def _paper_reporting_sources() -> list[Path]:
    paths = [
        PAPER_ROOT / "main.tex",
        PAPER_ROOT / "main_acl.tex",
        PAPER_ROOT / "paper.md",
    ]
    paths.extend(sorted(PAPER_ROOT.glob("tables_*.tex")))
    paths.extend(sorted(PAPER_ROOT.glob("appendix_*.tex")))
    return [path for path in paths if path.exists()]


def _paper_reporting_artifacts() -> list[Path]:
    paths: list[Path] = []
    paths.extend(_paper_reporting_sources())
    paths.extend(path for path in sorted((PAPER_ROOT / "figures").glob("*")) if path.is_file())
    return paths
