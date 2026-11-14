"""Shared benchmark conventions for question writing and judging (v3).

The v2 judges disagreed mostly on *convention* questions that a benchmark
question never stated: count vs count DISTINCT, strict vs inclusive time
boundaries, "within N hops", direction of neutral verbs, self-matches, and
role nouns. The v3 pipeline writes questions under an explicit convention sheet
and gives the same sheet to every judge, so these questions are settled once
instead of being decided differently by each model.

Derived from the gpt-6-luna flag reasons on the v2 build (2,080 accepted
items): ties 132, count/aggregation 100, temporal 57, duplicates 40, LIMIT/top-k
37, hop counts 31, KNOWS direction 24, self-loops 21, ambiguity 45. Ties and
unordered-LIMIT truncation are decided by deterministic gates, not by the sheet.
"""

from __future__ import annotations

import hashlib

from .models import SchemaSummary

CONVENTION_SHEET_VERSION = "v3.2"

CONVENTION_SHEET = """
Benchmark conventions (questions are written under these rules and read with them):
C1 Values. Text in quotation marks is an exact, case-sensitive value. Identifiers are written without quotation marks (for example "account 4803651952544056659") and match the label's identifying property. A quoted number or boolean that names a value ("'73'", "'False'") means that value in the property's stored type. Every value the question states appears in the query, and the query filters on no literal value that the question does not state.
C2 Direction. A verb with a direction ("transferred to", "invested in", "owned by", "replied to", "applied for") fixes the relationship direction. A neutral verb ("connected to", "linked with", "related to", "associated with") means either direction; a question that intends one direction must use a directed verb. Symmetric relationship types (listed with the schema) are matched without a direction.
C3 Roles. A role noun ("investor", "owner", "member", "author") covers every label that can play that role in the schema unless the question names the label.
C4 Counting. "How many <entities>" counts distinct entities. "How many <transfers / links / relationships / events / times>" counts relationship or event instances. Sum, average, minimum, and maximum are taken over all matching instances, never over DISTINCT values, unless the question says "distinct" or "different".
C5 Sets. Answers are compared as sets of rows: duplicate rows and row order do not matter unless the question asks for an order ("in chronological order", "sorted by", "ranked"). DISTINCT in a query is never an error by itself.
C6 Columns. The query returns every attribute the question asks for, by name. Extra columns that identify or describe the returned entities (ids, names, types, status flags) are allowed. Extra filters, exclusions, or row limits that the question does not state are not allowed.
C7 Comparisons. "After", "before", "more than", "less than", "over", "under", "exceeds" are strict (>, <). "On or after", "since", "at least", "at most", "no more than", "up to", "until" are inclusive (>=, <=). "Between A and B" includes both ends. "In <year>" or "in <month> <year>" covers the whole period. A two-way split ("before and after", "above and below") may put the boundary value in either group.
C8 Paths. "Within N hops" means 1 to N hops; "exactly N hops" means N; "directly" means 1 hop. A reachability question states its hop bound, and the query uses exactly that bound.
C9 Temporal chains. "Then", "followed by", "later", or "subsequently" between steps require each later step's timestamp to be greater than the earlier step's.
C10 Self-matches. "Other", "another", "else", or "different" (in the sense of "not the same one") require the query to exclude the anchor entity, for example a <> b for self-transfers. Without such a word, the query may either allow or exclude self-matches; neither is an error.
C11 Ranking. "Top k by X" or "the k highest X" sorts by X descending and keeps k rows; "lowest", "bottom", "fewest" sort ascending. "Which <entity> has the most X" returns the maximum. The ranking is over the population the question names; ranking a single given entity against itself is degenerate and not allowed.
C12 Grouping. "For each X", "per X", or "by X" groups by X and returns X's identifier with each aggregate. Without such words an aggregate is one value over the whole population. Groups with zero matches are included only when the question says so ("including those with none").
C13 One reading. A question has exactly one reasonable reading under these conventions. It contains no unfilled placeholders such as {k} and no malformed values (such as a quoted "account with id 123"), it names any time window, threshold, k, or hop bound it relies on, and it asks only for facts the graph records (no "current" or historical status the schema does not store).
""".strip()


def symmetric_relationship_note(schema: SchemaSummary | None) -> str:
    rels = sorted(getattr(schema, "symmetric_relationships", None) or []) if schema is not None else []
    if not rels:
        return ""
    return (
        "Symmetric relationship types in this graph (match without a direction; "
        "'X knows Y' and 'Y knows X' are the same fact): " + ", ".join(rels)
    )


def convention_sheet(schema: SchemaSummary | None = None) -> str:
    """Return the convention sheet, plus graph-specific notes derived from ``schema``.

    Inject this verbatim into question-writing, paraphrase, Cypher-generation,
    and judge prompts so every stage applies the same rules. Put it early in the
    prompt (it is identical across items and therefore cacheable).
    """

    note = symmetric_relationship_note(schema)
    return CONVENTION_SHEET + ("\n" + note if note else "")


def convention_sheet_sha256() -> str:
    return hashlib.sha256(CONVENTION_SHEET.encode("utf-8")).hexdigest()


# Short writer-side rules that follow from the sheet; useful in question
# realization/paraphrase prompts where the full judge rubric is not needed.
WRITER_RULES = """
When you write or rewrite a question:
- Use a directed verb whenever the query follows one direction (C2); use "connected to" only for undirected matches.
- Say "distinct" or name the unit you count: entities vs transfers/links/events (C4).
- Use the comparison words from C7 that match the operator exactly (strict vs inclusive).
- State every hop bound, time window, threshold, and k (C8, C13).
- Say "other"/"different" only when the anchor entity is excluded (C10).
- Name every attribute the answer must contain (C6).
- Write identifiers without quotation marks; quote only exact text values (C1).
""".strip()
