from __future__ import annotations

import re

from .models import ValidationIssue, ValidationResult


def quoted_values(question: str) -> list[str]:
    return [match.group(1) for match in re.finditer(r"'([^']+)'", question)]


def apply_question_constraints(validation: ValidationResult, question: str) -> ValidationResult:
    """Apply NL-question-specific Cypher constraints.

    The cypher example reference prompts distinguish quoted exact values from fuzzy text.
    This gate makes that rule executable: values quoted in the user question must
    appear as literals and must not be used with `CONTAINS`.
    """

    query = validation.normalized_cypher
    upper = query.upper()
    for value in quoted_values(question):
        if f"'{value}'" not in query and f'"{value}"' not in query:
            validation.issues.append(
                ValidationIssue(
                    "warning",
                    "quoted_value_not_literal",
                    f"Quoted question value `{value}` does not appear as an exact literal",
                )
            )
        contains_literal = re.search(
            rf"(?i)\bCONTAINS\s+['\"]{re.escape(value)}['\"]",
            query,
        )
        if "CONTAINS" in upper and contains_literal:
            validation.schema_valid = False
            validation.issues.append(
                ValidationIssue(
                    "error",
                    "quoted_value_fuzzy_match",
                    f"Quoted question value `{value}` must use exact matching, not CONTAINS",
                )
            )
    return validation
