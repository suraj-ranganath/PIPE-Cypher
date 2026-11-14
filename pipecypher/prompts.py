from __future__ import annotations

import json
from typing import Any

from .prompt_profiles import get_prompt_profile


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
- Each item must include `template`, `slots`, and `rationale`. `slots` is an object mapping each slot name to `Label.property`, where the property exists in the schema and uniquely identifies the entity (an id, or a unique name/title; never a first or last name alone).

Return a JSON array.
""".strip()

TEMPLATE_INDUCTION_PROMPT = """
Graph schema:
{schema}

Category: `{category}`

Question templates already in the benchmark for this category (their query
structures are saturated; do NOT propose paraphrases of these):
{covered}

Task:
Propose {n} NEW question templates for `{category}` whose Cypher answers need a
query structure that differs from every template above: a different relationship
path, a filter on a different property, a different aggregation or grouping, a
time window on a timestamp property, a multi-hop or variable-length pattern, an
existence or negation sub-pattern, or ordering/top-k over an aggregate.
At least {hard_n} templates must be compositional, combining two or more of:
multi-hop traversal, aggregation, property filtering, ordering/top-k, negation,
variable-length paths.

Rules:
- Use only labels, relationship types, properties, and categorical values visible in the schema.
- Templates must sound like realistic enterprise analyst questions and must be answerable with one read-only Cypher query.
- If the answer has several attributes, name them in the question (for example "list the ID and type of ...").
- Use no more than two entity slots, as placeholders in braces such as {{person}} or {{account}}.
- Avoid vague metrics such as "important", "popular", or "best" unless a property defines them.
- Each item must include `template`, `slots` (slot -> Label.property, a property that uniquely identifies the entity: an id or a unique name/title, never a first or last name alone), and `rationale` (the intended query structure).

Return a JSON array.
""".strip()

QUESTION_PARAPHRASE_PROMPT = """
Rewrite the question below as a natural question an enterprise analyst might type.
Keep the meaning identical: same entities, same filters, same requested answer.

Hard rules:
- Copy each of these values exactly, character for character, including quotes: {values}
- Do not add quotation marks around numbers or IDs that are unquoted in the question.
- Do not add or remove constraints, attributes, counts, or time windows.
- Return only the rewritten question on one line.

Question:
{question}
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

# --- v3 prompts (NAACL 2027 rebuild) -------------------------------------
# Cache-ordered: fixed blocks (schema, rules, conventions) come first and the
# item-specific blocks last, so hosted providers can reuse the cached prefix.
# Content is not shortened relative to v2.

_TEMPLATE_RULES_V3 = """
Rules for every template:
- Use only labels, relationship types, properties, and categorical values visible in the schema.
- Templates must sound like realistic enterprise analyst questions and must be answerable with one read-only Cypher query.
- Prefer finance, fraud, risk, identity, operations, access, compliance, community, or customer-support wording when the schema supports it.
- If the answer has several attributes, name them in the template (for example "list the ID and type of ...").
- Use no more than two entity slots, as placeholders in braces such as {account}, {person}, or {company}.
- Avoid vague metrics such as "important", "popular", "interesting", or "best" unless a property defines them.
- Every other value (dates, thresholds, categories, k in top-k) is written into the template as a literal, not a slot.
- For top-k, rank by a measure that rarely ties (sums or averages of amounts, timestamps) or keep k small; references whose k-th and (k+1)-th rows tie are rejected.
- State the conventions above in the template wording whenever the answer depends on them.

Each item is a JSON object with:
- `template`: the question text with slot placeholders.
- `slots`: an object mapping each slot name to `Label.property`, where the property exists in the schema and uniquely identifies the entity (an id, or a unique name/title; never a first or last name alone).
- `cypher`: ONE read-only Cypher query that answers the template exactly, with a parameter `$slot` for every slot. Use each parameter exactly once, only in an equality such as `WHERE p.personId = $person` or `(p:Person {personId: $person})`. Every other value appears as the same literal as in the template. Follow schema relationship directions (symmetric relationship types are matched without a direction), use RETURN DISTINCT for set results, COUNT(DISTINCT x) for entity counts and count(r) for relationship or event counts (C4), an explicit `a <> b` when the template says other/different (C10), and ORDER BY plus LIMIT for top-k. Return exactly the columns the template asks for, plus identifier context columns.
- `rationale`: the intended query structure.
""".strip()

TEMPLATE_GENERATION_PROMPT_V3 = """
Graph schema:
{schema}

Conventions that questions and queries follow:
{conventions}

{rules}

Task:
Generate {n} diverse question templates for the category `{category}`.{tier_request}

Return a JSON array.
""".strip()

TEMPLATE_INDUCTION_PROMPT_V3 = """
Graph schema:
{schema}

Conventions that questions and queries follow:
{conventions}

{rules}

Task:
Propose {n} NEW question templates for the category `{category}` whose Cypher answers need a
query structure that differs from every template listed below: a different relationship
path, a filter on a different property, a different aggregation or grouping, a
time window on a timestamp property, a multi-hop or variable-length pattern, an
existence or negation sub-pattern, or ordering/top-k over an aggregate.
At least {hard_n} templates must be compositional, combining two or more of:
multi-hop traversal, aggregation, property filtering, ordering/top-k, negation,
variable-length paths.{tier_request}

Templates already in the benchmark for this category (their query structures are
saturated; do NOT propose paraphrases of these):
{covered}

Return a JSON array.
""".strip()

TIER_REQUESTS_V3 = {
    "easy": " The benchmark needs EASY templates for this category: one relationship hop or a single-label filter, one or two answer columns, no multi-stage aggregation.",
    "medium": " The benchmark needs MEDIUM templates for this category: two relationship hops, or one aggregation with grouping, or a filter combined with ordering.",
    "hard": " The benchmark needs HARD templates for this category: each query combines at least three of multi-hop traversal, variable-length paths, aggregation with grouping, a second query stage (WITH), negation, a temporal comparison, ranking over an aggregate, and a multi-column answer.",
}

QUESTION_REALIZATION_PROMPT_V3 = """
Rewrite an analyst question in a requested style without changing its meaning:
same entities, same filters, same requested answer.

Conventions that questions follow:
{conventions}

Styles:
- terse_analyst: short and technical, no pleasantries.
- business_manager: plain business language a manager would use.
- imperative: a command such as "List ...", "Show ...", or "Give me ...".
- context_first: one short clause of business context, then the request.
- keyword: a keyword-style search query rather than a full sentence, keeping every constraint.

Hard rules:
- Copy each listed value exactly, character for character, including quotes.
- Do not add quotation marks around numbers or IDs that are unquoted in the question.
- Do not add or remove constraints, attributes, counts, ranks, or time windows.
- Keep wording that a convention depends on explicit (for example distinct counts, inclusive ranges, hop ranges, strict "after"/"before").
- Return JSON: {{"paraphrases": [<rewrite 1>, <rewrite 2>]}} with two different rewrites in the requested style.

Style: {style}
Values to copy exactly: {values}
Question: {question}
""".strip()

CYPHER_GENERATION_PROMPT_V3 = """
Task:
Generate a read-only Cypher statement for the natural-language question.

Graph schema:
{schema}

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
- For counts, follow convention C4: COUNT(DISTINCT x) when counting entities, count(r) when counting relationships, events, or times.
- When the question says \"other\", \"different\", \"another\", or \"else\", exclude the anchor entity explicitly (for example `a <> b`); otherwise a node may match itself (C10).
- For top-k or ranking, use ORDER BY plus LIMIT.
- For yes/no questions, return a boolean expression with a clear alias.
- Do not return columns the question does not ask for, apart from the identifier context columns listed above; a yes/no question returns exactly one boolean column.
- "Within N hops" means 1 to N hops (a variable-length pattern such as -[:TYPE*1..N]-); use exactly N fixed hops only when the question says exactly N.
- Relationship types listed as symmetric in the schema must be matched without a direction.
- Avoid OPTIONAL MATCH unless the question asks for missing/optional data.
- Avoid CALL, UNION, and write clauses.

Conventions:
{conventions}

Retrieved examples:
{examples}

Entity hints:
{entity_hints}

Question:
{question}

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
- Do not return columns the question does not ask for, apart from the identifier context columns listed above; a yes/no question returns exactly one boolean column.
- "Within N hops" means 1 to N hops (a variable-length pattern such as -[:TYPE*1..N]-); use exactly N fixed hops only when the question says exactly N.
- Relationship types listed as symmetric in the schema must be matched without a direction.
- Avoid OPTIONAL MATCH unless the question asks for missing/optional data.
- Avoid CALL, UNION, and write clauses.

Return only Cypher.
""".strip()

_MINIMAL_CYPHER_GENERATION_PROMPT = """
Task:
Generate a read-only Cypher statement for the natural-language question.

Graph schema:
{schema}

Question:
{question}

{examples_block}{entity_hint_block}{instructions_block}
Return only Cypher.
""".strip()

_STANDARD_CYPHER_INSTRUCTIONS = """
Instructions:
- Use only the provided labels, relationship types, properties, categorical values, and relationship directions.
- Do not invent labels, relationship types, or properties.
- Return only one Cypher statement.
- Do not include explanations, apologies, comments, markdown, or new lines.
- All set-returning RETURN clauses must use RETURN DISTINCT.
- Include nodes or properties explicitly requested by the question in the RETURN clause.
- Use exact matching for quoted strings in the question; do not use CONTAINS for quoted values.
- Prefer explicit relationship directions from the schema.
- For counts, use COUNT(DISTINCT variable).
- For top-k or ranking, use ORDER BY plus LIMIT.
- For yes/no questions, return a boolean expression with a clear alias.
- Avoid CALL, UNION, and write clauses.
""".strip()


def render_cypher_generation_prompt(
    *,
    profile_name: str,
    schema: str,
    question: str,
    examples: str,
    entity_hints: dict[str, Any],
    conventions: str = "",
) -> str:
    """Render a generation prompt for a Mind-the-Query-style prompt-profile study."""

    profile = get_prompt_profile(profile_name)
    if profile.name == "full_pipe_cypher_governed_v3":
        return CYPHER_GENERATION_PROMPT_V3.format(
            schema=schema,
            conventions=conventions or "(none)",
            examples=examples,
            entity_hints=json.dumps(entity_hints, ensure_ascii=False),
            question=question,
        )
    if profile.governed:
        return CYPHER_GENERATION_PROMPT.format(
            schema=schema,
            question=question,
            examples=examples,
            entity_hints=json.dumps(entity_hints, ensure_ascii=False),
        )

    examples_block = ""
    if profile.include_examples:
        examples_block = f"Retrieved examples:\n{examples}\n\n"

    entity_hint_block = ""
    if profile.include_entity_hints:
        entity_hint_block = (
            "Entity hints:\n"
            + json.dumps(entity_hints, ensure_ascii=False)
            + "\n\n"
        )

    instructions_block = ""
    if profile.include_instructions:
        instructions_block = _STANDARD_CYPHER_INSTRUCTIONS + "\n\n"

    return _MINIMAL_CYPHER_GENERATION_PROMPT.format(
        schema=schema,
        question=question,
        examples_block=examples_block,
        entity_hint_block=entity_hint_block,
        instructions_block=instructions_block,
    )

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
- Categorical property values in the schema constrain literal values written in the Cypher query.
- Do not reject because the execution sample returns a value that is absent from the categorical-value list; result rows are observed graph outputs.
- If deterministic validation says schema use is valid, lower schema_use_score only when the Cypher itself uses nonexistent schema elements, invalid relationship directions, or invalid literal values.
""".strip()

# --- Judge v3 (NAACL 2027 rebuild): convention sheet + per-criterion checklist ---
# Order is fixed for prompt caching: every block before "Graph schema" is
# identical across items and graphs, the schema is identical within a graph,
# and only the item block at the end varies. Code (pipecypher/judge.py,
# compute_checklist_verdict) turns the checklist into the verdict.
JUDGE_V3_SYSTEM = (
    "You are a meticulous reviewer of natural-language-to-Cypher benchmark items. "
    "Return strict JSON only. No markdown or extra text."
)

JUDGE_V3_PROMPT = """
Task: decide whether a benchmark item is correct. An item is a natural-language question and a reference Cypher query over the graph schema below. The item is correct when the query returns exactly what the question asks for, read under the conventions.

{conventions}

Out of scope (code checks these before you see the item; never answer "no" because of them): read-only safety, Cypher syntax, empty results, ties at an ORDER BY ... LIMIT cutoff, and truncation by a LIMIT without ORDER BY. A large LIMIT that only caps a list (the result has fewer rows than the LIMIT) is harmless. Categorical value lists constrain literals written in the query, not values that appear in result rows. Code checks that labels and properties exist and that simple MATCH patterns follow the schema, but it does not check patterns inside EXISTS / NOT EXISTS subqueries, untyped nodes, or whether a pattern can relate the entities the question means; you must check those.

How to review: first read the query clause by clause and write down what it returns: which variables each MATCH binds, what each WITH carries forward (a variable that is not carried loses its binding and matches anything if it is used again), which entities each mandatory MATCH drops, whether separate patterns are combined into a cross product of rows, and what one result row represents. Then compare that reading with the question.

Checklist. For each criterion, first write short evidence that quotes the question and the query, then answer "yes", "no", or "na" (na only when the criterion does not apply).
1. values: every entity, identifier, number, date, and quoted value in the question appears in the query with the same meaning, and the query filters on no literal value the question does not state (C1). A quoted phrase that is not itself a stored value (for example 'account with id 123' or 'company id company') is a no.
2. relationships: relationship types, node labels, and directions express the question's meaning, and the pattern connects the entities the question relates (C2, C3). Every pattern, including patterns inside EXISTS / NOT EXISTS and after WITH, uses a relationship the schema lists between those labels in the listed direction (symmetric types excepted); variables used after a WITH were carried through it; independent sub-answers are not combined into a cross product of rows.
3. aggregation: the aggregate function and the counted unit match the question (C4). na if the question asks for no aggregate.
4. grouping: the grouping key and the per-group output match the question (C12). A question that asks for one overall value gets one value, not one per entity; a per-entity question is not collapsed into one value. na if there is neither grouping nor an overall aggregate.
5. comparisons: comparison operators, boundaries, time windows, and hop ranges match the question (C7, C8, C9). na if there are none.
6. ranking: the sort key, sort direction, and k match the question (C11). A ranking whose population is restricted to one given entity (for example "among accounts with id 123, which have the most ...") or whose sort key is the same for every row is a no. na if the question asks for no ranking or ordering.
7. columns: the query returns every attribute the question asks for (C6).
8. no_extra_constraints: the query adds no filter, exclusion, hop bound, or row limit that the question does not state and the conventions do not require (C6, C8, C10), and no mandatory MATCH drops entities the question asks for (for example, keeping only a person's comments that reply to comments when the question asks for all of their comments).
9. unambiguous: the question has one reasonable reading under the conventions, contains no unfilled placeholder, asks only for facts the graph stores (no "current" job, change history, or population the schema lacks), and its answer is meaningful to an analyst (C11, C13).

Output: one JSON object with exactly these keys:
{{"query_reading": "walk through the query clause by clause (each MATCH pattern as start label, type, end label; each WITH and what it carries; each WHERE; the RETURN), then say what one result row represents and which rows are kept or dropped", "values": {{"evidence": "...", "answer": "yes|no|na"}}, "relationships": {{"evidence": "...", "answer": "..."}}, "aggregation": {{...}}, "grouping": {{...}}, "comparisons": {{...}}, "ranking": {{...}}, "columns": {{...}}, "no_extra_constraints": {{...}}, "unambiguous": {{...}}, "clarified_question": "if unambiguous is no, one rewrite of the question that has a single reading and matches the query; otherwise an empty string", "difficulty": "easy|medium|hard"}}

Graph schema:
{schema}

Item to review
Question:
{question}

Reference Cypher:
{cypher}

Result: {row_summary}
{rows}

Query features (from the parser): {features}
Validator notes: {notes}

Return the JSON object now.
""".strip()
