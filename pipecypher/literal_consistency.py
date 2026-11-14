"""Question <-> Cypher literal consistency (v3 gate).

A pipeline-validated reference must use exactly the values its question states:

* every bound slot value appears as a Cypher literal;
* every quoted value in the question appears as a Cypher literal;
* every string literal in the Cypher is stated in the question (case- and
  separator-insensitive; ISO dates may be written in common date formats);
* every number >= 2 in the Cypher (comparison thresholds, LIMIT k, hop bounds)
  is stated in the question as digits or a number word. ``> n`` may be stated
  as "more than n" or "at least n+1", so n +/- 1 is accepted.

The checks are conservative: values the parser cannot place (parameters,
numbers with 10+ digits that are not bound ids) are left unchecked rather than
rejected, and every problem is reported with the offending value.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Iterable

from .refresh_audit import mask_string_literals

_STRING_LITERAL_RE = re.compile(r"'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\"")
# Quotes must open after a non-word character and close before one, so the
# apostrophes in "I'd", "don't", or "accounts' owners" are not read as quotes.
_QUESTION_QUOTED_RE = re.compile(
    r"(?<![A-Za-z0-9])'([^']+)'(?![A-Za-z0-9])|(?<![A-Za-z0-9])\"([^\"]+)\"(?![A-Za-z0-9])|“([^”]+)”|‘([^’]+)’"
)
_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_.$])(-?\d+(?:\.\d+)?)(?![A-Za-z0-9_])")
_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_REL_BRACKET_RE = re.compile(r"\[[^\[\]]*\*[^\[\]]*\]")
_COMPARISON_TAIL_RE = re.compile(r"(?i)(<>|<=|>=|=|<|>|\bCONTAINS|\bSTARTS\s+WITH|\bENDS\s+WITH)\s*$")
_COMPARISON_HEAD_RE = re.compile(r"(?i)^\s*(<>|<=|>=|=|<|>)")
_TEMPORAL_FN_TAIL_RE = re.compile(r"(?i)\b(date|datetime|localdatetime|localtime|time|duration)\s*\(\s*$")
_PATTERN_MAP_OPEN_RE = re.compile(r"[\(\[]\s*[A-Za-z_][A-Za-z0-9_]*\s*(?::\s*`?[A-Za-z_][A-Za-z0-9_]*`?\s*)+$|[\(\[]\s*(?::\s*`?[A-Za-z_][A-Za-z0-9_]*`?\s*)+$")
_DURATION_RE = re.compile(r"^P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")
_NUMBER_WORDS = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "twenty-five": 25, "thirty": 30, "fifty": 50, "hundred": 100, "a hundred": 100,
    "one hundred": 100, "thousand": 1000, "a thousand": 1000, "one thousand": 1000,
    "double": 2, "twice": 2, "triple": 3, "pair": 2, "dozen": 12,
    "half": 2, "quarter": 4, "percent": 100, "percentage": 100, "%": 100,
    "week": 7, "weeks": 7, "fortnight": 14, "month": 30, "months": 30, "year": 365, "years": 365,
}
_ORDINAL_WORDS = {
    "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
    "eighth": 8, "ninth": 9, "tenth": 10,
}
_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ["january", "february", "march", "april", "may", "june", "july", "august",
         "september", "october", "november", "december"]
    )
}
_MONTHS.update({name[:3]: num for name, num in list(_MONTHS.items())})
_MONTHS["sept"] = 9


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[_\-]+", " ", text.lower()).split())


def _in_predicate_position(text: str, start: int, end: int) -> bool:
    """True when the literal spanning [start, end) is compared against data.

    Covers comparison operands (either side), IN-list members, CONTAINS / STARTS
    WITH / ENDS WITH operands, temporal constructor arguments used in such
    comparisons, and property-map values inside MATCH patterns. Constants in
    projections (``collect({type: 'University'})``) and arithmetic are skipped.
    """

    before = text[:start]
    stripped = before.rstrip()
    if _COMPARISON_TAIL_RE.search(stripped):
        return True
    if _COMPARISON_HEAD_RE.match(text[end:]):
        return True
    fn = _TEMPORAL_FN_TAIL_RE.search(stripped)
    if fn:
        outer = stripped[: fn.start()].rstrip()
        return bool(_COMPARISON_TAIL_RE.search(outer) or re.search(r"[+\-]$", outer))
    if stripped.endswith("[") or stripped.endswith(","):
        bracket = before.rfind("[")
        if bracket >= 0 and "]" not in before[bracket:] and re.search(r"(?i)\bIN\s*$", before[:bracket]):
            return True
    if stripped.endswith(":"):
        brace = before.rfind("{")
        if brace >= 0 and "}" not in before[brace:]:
            return bool(_PATTERN_MAP_OPEN_RE.search(before[:brace].rstrip()))
    return False


def cypher_string_literals(cypher: str, *, predicates_only: bool = False) -> list[str]:
    values = []
    for match in _STRING_LITERAL_RE.finditer(cypher):
        if predicates_only and not _in_predicate_position(cypher, match.start(), match.end()):
            continue
        raw = match.group(1) if match.group(1) is not None else match.group(2)
        values.append(re.sub(r"\\(.)", r"\1", raw))
    return values


def cypher_numbers(cypher: str) -> list[tuple[float, str]]:
    """(value, context) for data-facing numeric literals.

    Context is 'limit' (LIMIT k of an ordered query), 'hops' (variable-length
    bounds), or 'value' (a comparison operand). Arithmetic constants, unordered
    LIMITs (covered by the truncation gate), and SKIP are not returned.
    """

    masked = mask_string_literals(cypher)
    masked = re.sub(r"'[^']*'|\"[^\"]*\"", lambda m: " " * len(m.group(0)), masked)
    ordered = re.search(r"(?i)\bORDER\s+BY\b", masked) is not None
    hop_spans = [m.span() for m in _REL_BRACKET_RE.finditer(masked)]
    out: list[tuple[float, str]] = []
    for match in _NUMBER_RE.finditer(masked):
        start, end = match.span()
        stripped = masked[:start].rstrip()
        value = float(match.group(1))
        if any(a <= start < b for a, b in hop_spans) and re.search(r"(\*|\.\.)\s*$", stripped):
            out.append((value, "hops"))
        elif re.search(r"(?i)\bLIMIT$", stripped):
            if ordered:
                out.append((value, "limit"))
        elif re.search(r"(?i)\bSKIP$", stripped):
            continue
        elif _in_predicate_position(masked, start, end) and not re.search(r"[*/+\-%]\s*$", stripped) and not re.match(r"\s*[*/+%]", masked[end:]):
            out.append((value, "value"))
    return out


def _question_dates(question: str) -> set[date]:
    found: set[date] = set()
    text = question.lower()
    for y, m, d in re.findall(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text):
        try:
            found.add(date(int(y), int(m), int(d)))
        except ValueError:
            pass
    month_names = "|".join(sorted(_MONTHS, key=len, reverse=True))
    for mon, d, y in re.findall(rf"\b({month_names})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})", text):
        try:
            found.add(date(int(y), _MONTHS[mon], int(d)))
        except ValueError:
            pass
    for d, mon, y in re.findall(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({month_names})\.?,?\s+(\d{{4}})", text):
        try:
            found.add(date(int(y), _MONTHS[mon], int(d)))
        except ValueError:
            pass
    return found


def _question_months(question: str) -> set[tuple[int, int]]:
    text = question.lower()
    month_names = "|".join(sorted(_MONTHS, key=len, reverse=True))
    months = {(int(y), _MONTHS[m]) for m, y in re.findall(rf"\b({month_names})\.?,?\s+(\d{{4}})", text)}
    months |= {(int(y), int(m)) for y, m in re.findall(r"\b(\d{4})-(\d{2})\b", text)}
    return months


def _question_numbers(question: str) -> set[float]:
    text = question.lower().replace(",", "")
    numbers = {float(n) for n in re.findall(r"(?<![a-z0-9_])(-?\d+(?:\.\d+)?)", text)}
    for word, value in {**_NUMBER_WORDS, **_ORDINAL_WORDS}.items():
        if re.search(rf"\b{re.escape(word)}\b", text):
            numbers.add(float(value))
    for d in _question_dates(question):
        numbers.update({float(d.year), float(d.month), float(d.day)})
    return numbers


def _string_stated(value: str, question: str, q_dates: set[date], q_months: set[tuple[int, int]]) -> bool:
    if not value.strip():
        return True
    if value in question or _norm(value) in _norm(question):
        return True
    duration = _DURATION_RE.match(value)
    if duration and any(duration.groups()):
        q_numbers = _question_numbers(question)
        amounts = [float(g) for g in duration.groups() if g]
        return all(a in q_numbers or a == 1 for a in amounts)
    iso = _ISO_DATE_RE.match(value)
    if iso:
        y, m, d = (int(g) for g in iso.groups())
        try:
            if date(y, m, d) in q_dates:
                return True
        except ValueError:
            return False
        # "in March 2012" may be written as a range bound '2012-03-01' / '2012-04-01'.
        if d == 1 and ((y, m) in q_months or (y, m - 1 if m > 1 else 12) in q_months or (y - (m == 1), 12 if m == 1 else m - 1) in q_months):
            return True
        if d == 1 and (str(y) in question or (m == 1 and str(y - 1) in question)):
            return True
        if m == 12 and d == 31 and str(y) in question:
            return True
    return False


def literal_consistency_problems(
    question: str,
    cypher: str,
    bound_values: Iterable[Any] = (),
    *,
    ignore_limits: Iterable[int] = (),
) -> list[str]:
    """Problems found; ``ignore_limits`` lists pipeline-appended default LIMITs."""
    problems: list[str] = []
    for placeholder in re.findall(r"\{[A-Za-z_][A-Za-z0-9_]*\}", question):
        problems.append(f"question has an unfilled placeholder {placeholder}")
    all_strings = cypher_string_literals(cypher)
    strings = cypher_string_literals(cypher, predicates_only=True)
    numbers = cypher_numbers(cypher)
    all_numbers = {float(n) for n in _NUMBER_RE.findall(re.sub(r"'[^']*'|\"[^\"]*\"", " ", mask_string_literals(cypher)))}
    number_values = all_numbers
    string_set = set(all_strings)
    q_dates = _question_dates(question)
    q_months = _question_months(question)
    q_numbers = _question_numbers(question)

    bound_text: set[str] = set()
    for value in bound_values:
        if value is None:
            continue
        text = str(value)
        bound_text.add(text)
        as_number = None
        if isinstance(value, int | float) and not isinstance(value, bool):
            as_number = float(value)
        elif re.fullmatch(r"-?\d+(?:\.\d+)?", text):
            as_number = float(text)
        if text in string_set or (as_number is not None and as_number in number_values):
            continue
        problems.append(f"bound value {text!r} is not used in the Cypher")

    for match in _QUESTION_QUOTED_RE.finditer(question):
        quoted = next(group for group in match.groups() if group is not None)
        if quoted in string_set:
            continue
        if re.fullmatch(r"-?\d+(?:\.\d+)?", quoted) and float(quoted) in number_values:
            continue
        problems.append(f"quoted value {quoted!r} is not a Cypher literal")

    for value in strings:
        if value in bound_text or _string_stated(value, question, q_dates, q_months):
            continue
        problems.append(f"Cypher literal {value!r} is not stated in the question")

    bound_numbers = set()
    for text in bound_text:
        if re.fullmatch(r"-?\d+(?:\.\d+)?", text):
            bound_numbers.add(float(text))
    for value, context in numbers:
        if value in bound_numbers or abs(value) < 2:
            continue
        if abs(value) >= 1e9:  # epoch timestamps / ids that are not bound: left unchecked
            continue
        if value in q_numbers or (context == "value" and (value - 1 in q_numbers or value + 1 in q_numbers)):
            continue
        if context == "limit" and value in {float(v) for v in ignore_limits}:
            continue
        label = {"limit": "LIMIT", "hops": "hop bound"}.get(context, "number")
        problems.append(f"{label} {value:g} is not stated in the question")
    return problems
