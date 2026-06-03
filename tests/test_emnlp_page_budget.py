from __future__ import annotations

from pathlib import Path

from scripts.audit_emnlp_page_budget import (
    audit_page_budget,
    format_page_budget_audit,
    validate_page_budget,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_validate_page_budget_accepts_current_emnlp_accounting():
    failures = validate_page_budget(
        {
            "Conclusion": [4],
            "Limitations": [4],
            "Ethics Statement": [4],
            "References": [4],
            "Additional Results": [5],
            "Governed Generation Evidence": [],
        },
        max_counted_page=6,
    )

    assert failures == []


def test_validate_page_budget_accepts_reorganized_appendix_title():
    failures = validate_page_budget(
        {
            "Conclusion": [6],
            "Limitations": [6],
            "Ethics Statement": [6],
            "References": [7],
            "Additional Results": [],
            "Governed Generation Evidence": [8],
        },
        max_counted_page=6,
    )

    assert failures == []


def test_validate_page_budget_rejects_late_conclusion_and_bad_ordering():
    failures = validate_page_budget(
        {
            "Conclusion": [7],
            "Limitations": [6],
            "Ethics Statement": [6],
            "References": [5],
            "Additional Results": [4],
            "Governed Generation Evidence": [],
        },
        max_counted_page=6,
    )

    assert "Conclusion starts on page 7, after counted page 6" in failures
    assert "Limitations appears before Conclusion" in failures
    assert "References appears before Limitations" in failures
    assert "Appendix Additional Results appears before References" in failures


def test_current_acl_pdf_satisfies_emnlp_page_budget():
    audit = audit_page_budget(REPO_ROOT / "paper_emnlp2026_industry/main_acl.pdf")
    text = format_page_budget_audit(audit)

    assert audit.pass_ is True
    assert min(audit.marker_pages["Conclusion"]) <= 6
    assert min(audit.marker_pages["Limitations"]) >= min(audit.marker_pages["Conclusion"])
    assert "Status: pass" in text
