from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .llm import OpenAICompatibleLLM
from .models import SchemaSummary
from .validator import strip_code_fences


TEXT2CYPHER_SYSTEM = (
    "You are an expert Text2Cypher system for enterprise property graphs. "
    "Return only one read-only Cypher query. Do not include markdown or explanations."
)

TEXT2CYPHER_PROMPT = """
Graph schema:
{schema}

{few_shot_block}
Question:
{question}

Rules:
- Use only labels, relationship types, properties, and relationship directions in the schema.
- Preserve relationship direction exactly as listed.
- Use exact equality for quoted values.
- All set-returning RETURN clauses must use RETURN DISTINCT.
- For counts, use COUNT(DISTINCT variable).
- For top-k/ranking, use ORDER BY plus LIMIT.
- For yes/no questions, return a boolean expression with a clear alias.
- Do not use CREATE, MERGE, DELETE, SET, REMOVE, LOAD CSV, APOC writes, or admin calls.
- Return only the Cypher query.
""".strip()


@dataclass
class Text2CypherPrediction:
    id: str
    question: str
    graph_profile: str
    category: str
    difficulty: str
    predicted_cypher: str
    raw_text: str
    model: str
    gold_cypher: str | None = None
    error: str | None = None


def build_text2cypher_prompt(
    *,
    question: str,
    schema: SchemaSummary,
    schema_max_items: int = 80,
    few_shot_examples: list[dict[str, Any]] | None = None,
) -> str:
    return TEXT2CYPHER_PROMPT.format(
        schema=schema.to_prompt(max_items=schema_max_items),
        few_shot_block=_few_shot_block(few_shot_examples or []),
        question=question,
    )


def predict_text2cypher(
    *,
    llm: OpenAICompatibleLLM,
    example: dict[str, Any],
    schema: SchemaSummary,
    few_shot_examples: list[dict[str, Any]] | None = None,
    schema_max_items: int = 80,
    temperature: float = 0.0,
    max_tokens: int = 512,
) -> Text2CypherPrediction:
    prompt = build_text2cypher_prompt(
        question=str(example["question"]),
        schema=schema,
        schema_max_items=schema_max_items,
        few_shot_examples=few_shot_examples,
    )
    try:
        response = llm.chat(
            system=TEXT2CYPHER_SYSTEM,
            user=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        predicted = clean_predicted_cypher(response.text)
        error = None
        raw_text = response.text
    except Exception as exc:  # pragma: no cover - live model path
        predicted = ""
        raw_text = ""
        error = str(exc)

    return Text2CypherPrediction(
        id=str(example.get("id") or stable_question_id(example)),
        question=str(example["question"]),
        graph_profile=str(example.get("graph_profile", "")),
        category=str(example.get("category", "")),
        difficulty=str(example.get("difficulty", "")),
        predicted_cypher=predicted,
        raw_text=raw_text,
        model=llm.model,
        gold_cypher=example.get("cypher"),
        error=error,
    )


def choose_few_shots(
    examples: list[dict[str, Any]],
    *,
    current: dict[str, Any],
    k: int,
) -> list[dict[str, Any]]:
    if k <= 0:
        return []
    current_id = current.get("id")
    same_graph_category = [
        item
        for item in examples
        if item.get("id") != current_id
        and item.get("graph_profile") == current.get("graph_profile")
        and item.get("category") == current.get("category")
    ]
    same_graph = [
        item
        for item in examples
        if item.get("id") != current_id
        and item.get("graph_profile") == current.get("graph_profile")
        and item not in same_graph_category
    ]
    ordered = sorted(same_graph_category, key=lambda item: str(item.get("id")))
    ordered.extend(sorted(same_graph, key=lambda item: str(item.get("id"))))
    return ordered[:k]


def clean_predicted_cypher(text: str) -> str:
    cleaned = strip_code_fences(text).strip()
    for prefix in ("Cypher:", "Query:", "Answer:"):
        if cleaned.lower().startswith(prefix.lower()):
            cleaned = cleaned[len(prefix) :].strip()
    if "\n" in cleaned:
        lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
        cypher_lines = [
            line
            for line in lines
            if not line.lower().startswith(("here", "this query", "explanation"))
        ]
        cleaned = " ".join(cypher_lines or lines)
    if ";" in cleaned:
        cleaned = cleaned.split(";", 1)[0].strip()
    return " ".join(cleaned.split())


def stable_question_id(example: dict[str, Any]) -> str:
    payload = {
        "graph_profile": example.get("graph_profile", ""),
        "question": example.get("question", ""),
    }
    digest = hashlib.sha256(repr(sorted(payload.items())).encode("utf-8")).hexdigest()
    return f"pred_{digest[:16]}"


def prediction_to_dict(prediction: Text2CypherPrediction) -> dict[str, Any]:
    return {
        "id": prediction.id,
        "question": prediction.question,
        "graph_profile": prediction.graph_profile,
        "category": prediction.category,
        "difficulty": prediction.difficulty,
        "predicted_cypher": prediction.predicted_cypher,
        "raw_text": prediction.raw_text,
        "model": prediction.model,
        "gold_cypher": prediction.gold_cypher,
        "error": prediction.error,
    }


def _few_shot_block(examples: list[dict[str, Any]]) -> str:
    if not examples:
        return ""
    parts = ["Examples:"]
    for example in examples:
        parts.append(f"Question: {example.get('question')}")
        parts.append(f"Cypher: {example.get('cypher')}")
    return "\n".join(parts) + "\n\n"
