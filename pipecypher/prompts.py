from __future__ import annotations


SYSTEM_CYPHER_ENGINEER = """You are an expert Cypher benchmark engineer. Return only the requested artifact. No markdown, apologies, or explanations."""

SYSTEM_JSON_ENGINEER = """You are an expert benchmark engineer. Return strict JSON only. No markdown or extra text."""

TEMPLATE_GENERATION_PROMPT = """
Graph schema:
{schema}

Task:
Generate {n} diverse natural-language question templates for the category `{category}`.

Rules:
- Use only labels, relationship types, properties, and categorical values visible in the schema.
- Templates must sound like realistic enterprise analyst questions.
- Prefer finance, fraud, risk, identity, operations, access, compliance, or customer-support wording when the schema supports it.
- Use no more than two entity slots.
- Use slot placeholders in braces, such as {{account}}, {{person}}, {{merchant}}, {{loan}}, {{company}}.
- Avoid vague metrics such as "important", "popular", "interesting", or "best" unless an explicit property supports it.
- Each item must include `template`, `slots`, and `rationale`.

Return a JSON array.
""".strip()

REVERSE_CYPHER_PROMPT = """
Graph schema:
{schema}

Question template:
{template}

Slots:
{slots}

Task:
Write a read-only Cypher query that returns bindings for every slot.

Rules:
- Use variables named exactly as the slots.
- Use only schema-visible labels, relationships, and properties.
- Use forward relationship directions as listed in the schema.
- Keep it simple: MATCH, WHERE, RETURN DISTINCT, LIMIT only.
- Do not use write clauses, APOC writes, subqueries, or comments.
- Add `LIMIT {limit}`.

Return only Cypher.
""".strip()

CYPHER_GENERATION_PROMPT = """
Task:
Generate a read-only Cypher statement for the natural-language question.

Graph schema:
{schema}

Question:
{question}

Retrieved examples:
{examples}

Entity hints:
{entity_hints}

Instructions:
- Use only the provided labels, relationship types, properties, categorical values, and relationship directions.
- Do not invent labels, relationship types, or properties.
- Retrieved examples may replace graph-specific values with placeholders like `{{PERSONNAME_1}}`; copy their query structure, not the placeholder values.
- If Entity hints include `_grounded_mentions` or `_annotated_question`, use the canonical values
  and schema paths there for entity and categorical matches.
- Return only one Cypher statement.
- Do not include explanations, apologies, comments, markdown, or new lines.
- All set-returning RETURN clauses must use RETURN DISTINCT.
- Include nodes or properties explicitly requested by the question in the RETURN clause.
- Include useful context columns with returned identifiers or names: account type and blocked status with Account.accountId; personId with Person.personName; companyId and business with Company.companyName; loan amount and balance with Loan.loanId; medium type and risk level with Medium.mediumId.
- Use exact matching for quoted strings in the question; do not use CONTAINS for quoted values.
- Use CONTAINS or case-insensitive matching only for unquoted fuzzy user phrasing.
- Prefer explicit relationship directions from the schema; if two patterns are needed to preserve direction, use comma-separated MATCH patterns instead of reversing an edge.
- For counts, use COUNT(DISTINCT variable).
- For top-k or ranking, use ORDER BY plus LIMIT.
- For yes/no questions, return a boolean expression with a clear alias.
- Avoid OPTIONAL MATCH unless the question asks for missing/optional data.
- Avoid CALL, UNION, and write clauses.

Return only Cypher.
""".strip()

REPAIR_PROMPT = """
Graph schema:
{schema}

Question:
{question}

Cypher attempt:
{cypher}

Validation or execution issue:
{issue}

Task:
Repair the query while preserving the question intent.

Rules:
- Use only schema-visible labels, relationships, properties, and directions.
- Keep the query read-only.
- Use RETURN DISTINCT for set-returning queries.
- Return only the corrected Cypher.
""".strip()

JUDGE_PROMPT = """
You are judging whether an NL-to-Cypher benchmark example is acceptable for an enterprise benchmark.

Graph schema:
{schema}

Question:
{question}

Cypher:
{cypher}

Execution sample:
{rows}

Validation summary:
{validation}

Return strict JSON with:
- pass: boolean
- ambiguity_score: number from 0 to 1, lower is better
- semantic_alignment_score: number from 0 to 1
- schema_use_score: number from 0 to 1
- difficulty: one of easy, medium, hard
- failure_reason: short string, empty if pass is true

Pass only if the question is unambiguous, the Cypher answers it, the schema use is valid, and the result would be useful in an enterprise benchmark.
""".strip()
