#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


COUNTED_BODY_MARKERS = ("Conclusion",)
EXCLUDED_SECTION_MARKERS = ("Limitations", "Ethics Statement", "References", "Additional Results")


@dataclass(frozen=True)
class PageBudgetAudit:
    pdf: str
    max_counted_page: int
    page_count: int
    marker_pages: dict[str, list[int]]
    pass_: bool
    failures: list[str]

    def to_dict(self) -> dict:
        return {
            "pdf": self.pdf,
            "max_counted_page": self.max_counted_page,
            "page_count": self.page_count,
            "marker_pages": self.marker_pages,
            "pass": self.pass_,
            "failures": self.failures,
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit EMNLP Industry page accounting for the ACL-style PDF draft."
    )
    parser.add_argument(
        "--pdf",
        default="paper_emnlp2026_industry/main_acl.pdf",
        help="Compiled ACL-style PDF to audit.",
    )
    parser.add_argument("--max-counted-page", type=int, default=6)
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args()

    audit = audit_page_budget(Path(args.pdf), max_counted_page=args.max_counted_page)
    if args.format == "json":
        print(json.dumps(audit.to_dict(), indent=2, sort_keys=True))
    else:
        print(format_page_budget_audit(audit))
    if not audit.pass_:
        raise SystemExit(1)


def audit_page_budget(pdf: Path, *, max_counted_page: int = 6) -> PageBudgetAudit:
    marker_pages = extract_marker_pages(pdf, COUNTED_BODY_MARKERS + EXCLUDED_SECTION_MARKERS)
    page_count = _page_count(pdf)
    failures = validate_page_budget(marker_pages, max_counted_page=max_counted_page)
    return PageBudgetAudit(
        pdf=str(pdf),
        max_counted_page=max_counted_page,
        page_count=page_count,
        marker_pages=marker_pages,
        pass_=not failures,
        failures=failures,
    )


def extract_marker_pages(pdf: Path, markers: Iterable[str]) -> dict[str, list[int]]:
    reader = _reader(pdf)
    marker_pages = {marker: [] for marker in markers}
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        for marker in marker_pages:
            if marker in text:
                marker_pages[marker].append(page_number)
    return marker_pages


def validate_page_budget(
    marker_pages: dict[str, list[int]],
    *,
    max_counted_page: int = 6,
) -> list[str]:
    failures: list[str] = []
    conclusion_page = _first_page(marker_pages, "Conclusion")
    limitations_page = _first_page(marker_pages, "Limitations")
    references_page = _first_page(marker_pages, "References")
    appendix_page = _first_page(marker_pages, "Additional Results")

    if conclusion_page is None:
        failures.append("missing Conclusion marker")
    elif conclusion_page > max_counted_page:
        failures.append(
            f"Conclusion starts on page {conclusion_page}, after counted page {max_counted_page}"
        )

    if limitations_page is None:
        failures.append("missing Limitations marker")
    elif conclusion_page is not None and limitations_page < conclusion_page:
        failures.append("Limitations appears before Conclusion")

    if references_page is None:
        failures.append("missing References marker")
    elif limitations_page is not None and references_page < limitations_page:
        failures.append("References appears before Limitations")

    if appendix_page is None:
        failures.append("missing appendix Additional Results marker")
    elif references_page is not None and appendix_page < references_page:
        failures.append("Appendix appears before References")

    return failures


def format_page_budget_audit(audit: PageBudgetAudit) -> str:
    lines = [
        "# EMNLP Page-Budget Audit",
        "",
        f"- PDF: `{audit.pdf}`",
        f"- PDF pages: {audit.page_count}",
        f"- Counted-body page limit: {audit.max_counted_page}",
        f"- Status: {'pass' if audit.pass_ else 'fail'}",
        "",
        "| Marker | Pages |",
        "| --- | --- |",
    ]
    for marker, pages in audit.marker_pages.items():
        page_text = ", ".join(str(page) for page in pages) if pages else "missing"
        lines.append(f"| {marker} | {page_text} |")
    if audit.failures:
        lines.extend(["", "Failures:"])
        lines.extend(f"- {failure}" for failure in audit.failures)
    lines.append("")
    return "\n".join(lines)


def _first_page(marker_pages: dict[str, list[int]], marker: str) -> int | None:
    pages = marker_pages.get(marker, [])
    return min(pages) if pages else None


def _reader(pdf: Path):
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise SystemExit("pypdf is required for EMNLP page-budget auditing") from exc
    return PdfReader(str(pdf))


def _page_count(pdf: Path) -> int:
    return len(_reader(pdf).pages)


if __name__ == "__main__":
    main()
