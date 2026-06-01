# BalkanID Cypher Design Notes To Transfer

Source inspected: `/Users/suraj/Documents/Archive/BalkanID/Dev/copilot-api`.

## Prompt-Level Constraints

The BalkanID Cypher prompt contains several production lessons that should remain central in PIPE-Cypher:

- Use only schema-provided relationship types and properties.
- Preserve relationship directions and use comma-separated `MATCH` patterns when necessary rather than reversing edges.
- Return only Cypher, with no commentary or markdown.
- Enforce `RETURN DISTINCT` to avoid duplicate rows.
- Include entities mentioned in the question in the return surface.
- Use exact matching for text inside single quotes.
- Handle domain synonyms explicitly, such as group/membership mapping to graph concepts.
- Encode categorical property values directly in prompt context.
- Add domain-specific semantics for insights, reviews, roles, purposes, and constraints when those concepts exist.

## Rewrite And Validation Ideas

BalkanID's `AlterCypherQuery` and listeners motivate PIPE-Cypher's deterministic gate:

- reject unsafe/reserved variable names such as `index`, `constraint`, `create`, `drop`, `exists`, and `remove`;
- skip risky parser transformations for complex features such as `CASE`, `UNION`, `CALL`, `WHERE EXISTS`, `UNWIND`;
- add `RETURN DISTINCT` when missing;
- normalize function formatting such as `COALESCE(a,b)`;
- add display/context columns programmatically where the product requires them;
- enrich returned entities with optional context only after the core query is valid;
- prefer parser-aware modification over broad string replacement.
- extract return columns with parser listeners before changing the display surface;
- split long `MATCH` chains into safer anchored `MATCH` plus `OPTIONAL MATCH` expansions only when the parser sees no relationship variables/properties that would change semantics;
- add product-context enrichments after parsing, such as optional insight/finding matches, while keeping the base query available for execution validation;
- document programmatic query-alteration steps to users and reviewers so rewritten Cypher is auditable rather than silent.

Implemented transfer in PIPE-Cypher:

- `pipecypher.validator.normalize_cypher` strips fences, normalizes whitespace, normalizes `COALESCE(...)`, and enforces `RETURN DISTINCT`.
- `pipecypher.validator.validate_cypher` rejects write/admin tokens, unsafe reserved variable names, unknown labels, missing or unknown relationship types, unknown properties, reversed relationship directions, and undirected relationship patterns. It now interprets incoming Cypher arrows such as `(:A)<-[:R]-(:B)` as the directed edge `(:B)-[:R]->(:A)` before checking the observed schema direction, closing a common gap in string-only direction checks.
- `pipecypher.validator.categorical_property_issues` turns BalkanID's categorical-value prompt rule into a deterministic schema gate: if a schema provides values such as `Account.accountType: checking, savings`, generated node maps and `WHERE` predicates using other string literals are rejected.
- `pipecypher.question_constraints.apply_question_constraints` turns the quoted-exact-match prompt rule into an executable gate.
- `pipecypher.validator.contextual_return_issues` warns when returned FinBench identifiers or names lack useful enterprise context columns, mirroring BalkanID's table-display return enrichment pattern without making parser-risky rewrites.
- `pipecypher.cypher_parser.OptionalCypherParser` can use the BalkanID ANTLR parser when its local runtime dependencies are available, but keeps offline tests independent of that archive.

## Benchmark Implication

PIPE-Cypher should not simply ask an LLM to write Cypher. It should test whether generated examples follow the sort of constraints deployed systems need: schema discipline, directionality, safe execution, exact matching, contextual return fields, and robust handling of domain synonyms.

For the paper, the deeper innovation story should frame these as "parser-aware Cypher governance" rather than only prompt engineering. The BalkanID archive shows why deployed text-to-Cypher systems need a layered approach: constrained prompting, grammar/AST parsing, conservative skip rules for high-risk constructs, deterministic rewrites, display-column enrichment, and explicit explanation of any alteration. PIPE-Cypher adapts the parts that are benchmark-safe: validation, normalization, exact-match checks, relationship-direction discipline, and contextual return diagnostics. Future work can port more listener-based AST rewrites into PIPE-Cypher once the ANTLR runtime is packaged cleanly.
