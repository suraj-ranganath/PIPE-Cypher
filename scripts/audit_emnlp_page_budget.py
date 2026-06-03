#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


COUNTED_BODY_MARKERS = ("Conclusion",)
APPENDIX_SECTION_MARKERS = ("Additional Results", "Governed Generation Evidence")
EXCLUDED_SECTION_MARKERS = ("Limitations", "Ethics Statement", "References") + APPENDIX_SECTION_MARKERS
A4_WIDTH_PT = 595.276
A4_HEIGHT_PT = 841.89
A4_TOLERANCE_PT = 2.0
FORBIDDEN_TEXT_PATTERNS = {
    "remote host leakage": re.compile(r"\bds-serv6\b", re.IGNORECASE),
    "local path leakage": re.compile(r"/Users/suraj|/home/suraj", re.IGNORECASE),
    "non-anonymized repository link": re.compile(
        r"github\.com/suraj-ranganath/PIPE-Cypher", re.IGNORECASE
    ),
    "stale TODO wording": re.compile(r"\bTODO\b|should be promoted", re.IGNORECASE),
    "diagnostic run evidence": re.compile(
        r"\bsmoke\b|"
        r"\bmini(?:\s+(?:run|suite|result|results|table|artifact|evidence)|[-_](?:run|suite|result|results|table|artifact|evidence))\b|"
        r"\bmidscale\b|\btarget[-_\s]?25\b|\bablation25\b",
        re.IGNORECASE,
    ),
}


@dataclass(frozen=True)
class PageBudgetAudit:
    pdf: str
    max_counted_page: int
    page_count: int
    marker_pages: dict[str, list[int]]
    page_size_ok: bool
    page_sizes: list[tuple[float, float]]
    fonts_embedded_ok: bool | None
    forbidden_text_hits: list[str]
    pass_: bool
    failures: list[str]

    def to_dict(self) -> dict:
        return {
            "pdf": self.pdf,
            "max_counted_page": self.max_counted_page,
            "page_count": self.page_count,
            "marker_pages": self.marker_pages,
            "page_size_ok": self.page_size_ok,
            "page_sizes": self.page_sizes,
            "fonts_embedded_ok": self.fonts_embedded_ok,
            "forbidden_text_hits": self.forbidden_text_hits,
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
    page_sizes = extract_page_sizes(pdf)
    page_size_ok = all(_is_a4_size(width, height) for width, height in page_sizes)
    fonts_embedded_ok = fonts_are_embedded(pdf)
    forbidden_text_hits = forbidden_text_matches(pdf)
    failures = validate_page_budget(marker_pages, max_counted_page=max_counted_page)
    if not page_size_ok:
        failures.append("one or more pages are not A4-sized")
    if fonts_embedded_ok is False:
        failures.append("one or more fonts are not embedded")
    if forbidden_text_hits:
        failures.append("forbidden or non-anonymized text appears in PDF")
    return PageBudgetAudit(
        pdf=str(pdf),
        max_counted_page=max_counted_page,
        page_count=page_count,
        marker_pages=marker_pages,
        page_size_ok=page_size_ok,
        page_sizes=page_sizes,
        fonts_embedded_ok=fonts_embedded_ok,
        forbidden_text_hits=forbidden_text_hits,
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


def extract_page_sizes(pdf: Path) -> list[tuple[float, float]]:
    reader = _reader(pdf)
    sizes: list[tuple[float, float]] = []
    for page in reader.pages:
        box = page.mediabox
        sizes.append((float(box.width), float(box.height)))
    return sizes


def fonts_are_embedded(pdf: Path) -> bool | None:
    try:
        output = subprocess.check_output(
            ["pdffonts", str(pdf)],
            text=True,
            stderr=subprocess.STDOUT,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    lines = output.splitlines()[2:]
    embedded_values = []
    for line in lines:
        parts = line.split()
        if len(parts) >= 7:
            embedded_values.append(parts[4].lower())
    return all(value == "yes" for value in embedded_values) if embedded_values else None


def forbidden_text_matches(pdf: Path) -> list[str]:
    reader = _reader(pdf)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    hits = []
    for label, pattern in FORBIDDEN_TEXT_PATTERNS.items():
        if pattern.search(text):
            hits.append(label)
    return hits


def validate_page_budget(
    marker_pages: dict[str, list[int]],
    *,
    max_counted_page: int = 6,
) -> list[str]:
    failures: list[str] = []
    conclusion_page = _first_page(marker_pages, "Conclusion")
    limitations_page = _first_page(marker_pages, "Limitations")
    references_page = _first_page(marker_pages, "References")
    appendix_marker, appendix_page = _first_available_marker_page(
        marker_pages, APPENDIX_SECTION_MARKERS
    )

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
        expected = " or ".join(APPENDIX_SECTION_MARKERS)
        failures.append(f"missing appendix marker ({expected})")
    elif references_page is not None and appendix_page < references_page:
        failures.append(f"Appendix {appendix_marker} appears before References")

    return failures


def format_page_budget_audit(audit: PageBudgetAudit) -> str:
    lines = [
        "# EMNLP Page-Budget Audit",
        "",
        f"- PDF: `{audit.pdf}`",
        f"- PDF pages: {audit.page_count}",
        f"- Counted-body page limit: {audit.max_counted_page}",
        f"- A4 page size: {'pass' if audit.page_size_ok else 'fail'}",
        "- Embedded fonts: "
        + (
            "pass"
            if audit.fonts_embedded_ok is True
            else "not checked"
            if audit.fonts_embedded_ok is None
            else "fail"
        ),
        f"- Forbidden text: {'none' if not audit.forbidden_text_hits else ', '.join(audit.forbidden_text_hits)}",
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


def _first_available_marker_page(
    marker_pages: dict[str, list[int]], markers: Iterable[str]
) -> tuple[str | None, int | None]:
    first_marker: str | None = None
    first_page: int | None = None
    for marker in markers:
        page = _first_page(marker_pages, marker)
        if page is None:
            continue
        if first_page is None or page < first_page:
            first_marker = marker
            first_page = page
    return first_marker, first_page


def _reader(pdf: Path):
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise SystemExit("pypdf is required for EMNLP page-budget auditing") from exc
    return PdfReader(str(pdf))


def _page_count(pdf: Path) -> int:
    return len(_reader(pdf).pages)


def _is_a4_size(width: float, height: float) -> bool:
    return (
        abs(width - A4_WIDTH_PT) <= A4_TOLERANCE_PT
        and abs(height - A4_HEIGHT_PT) <= A4_TOLERANCE_PT
    )


if __name__ == "__main__":
    main()
