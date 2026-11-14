from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from typing import Any

import requests

from .diversity_metrics import canonical_query_signature
from .llm import ChatResponse, OpenAICompatibleLLM, strip_reasoning_text
from .models import SchemaSummary
from .retrieval import cosine_counts, tokenize
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
    few_shot_selection: dict[str, Any] | None = None
    prompt_sha256: str | None = None
    prompt_format: str = "pipe_standard"
    prompt_transport: str = "chat"
    system_message_mode: str | None = None
    provider: str | None = None


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
    prompt_format: str = "pipe_standard",
) -> Text2CypherPrediction:
    from .prompt_formats import render_prompt

    # Prompt-format errors (unknown name, few-shot with a zero-shot native
    # template) are configuration errors and propagate instead of being logged
    # as per-row request failures.
    rendered = render_prompt(
        prompt_format,
        schema_text=schema.to_prompt(max_items=schema_max_items),
        question=str(example["question"]),
        few_shot_examples=few_shot_examples,
        schema=schema,
    )
    system_message_mode = str(getattr(llm, "system_message_mode", "separate") or "separate")
    # Hash of the prompt content actually sent (messages after system-message
    # merging, or the raw completion prompt).
    prompt_sha256 = rendered.sha256(system_message_mode)
    try:
        response = send_rendered_prompt(
            llm,
            rendered,
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
        prompt_sha256=prompt_sha256,
        prompt_format=rendered.format_name,
        prompt_transport=rendered.transport,
        system_message_mode=system_message_mode if rendered.transport == "chat" else None,
        provider=getattr(llm, "provider", None),
        few_shot_selection=selection_metadata(
            current=example,
            selected=few_shot_examples or [],
        )
        if few_shot_examples
        else None,
    )


def send_rendered_prompt(
    llm: Any,
    rendered: Any,
    *,
    temperature: float = 0.0,
    max_tokens: int = 512,
) -> ChatResponse:
    """Send a :class:`pipecypher.prompt_formats.RenderedPrompt` to ``llm``.

    ``(system, user)`` chat prompts go through ``llm.chat`` unchanged, so the
    historical pipe_standard request path is untouched. Documented formats that
    use a single user turn or a raw completion prompt need message-level access.
    """

    if rendered.transport == "completion":
        complete = getattr(llm, "complete", None)
        if callable(complete):
            return complete(
                prompt=rendered.user,
                temperature=temperature,
                max_tokens=max_tokens,
                stop=list(rendered.stop),
            )
        if isinstance(llm, OpenAICompatibleLLM):
            return _openai_compatible_completion(
                llm,
                prompt=rendered.user,
                temperature=temperature,
                max_tokens=max_tokens,
                stop=list(rendered.stop),
            )
        raise TypeError(f"{type(llm).__name__} cannot send completion-transport prompts")

    if rendered.system is not None and not rendered.stop:
        return llm.chat(
            system=rendered.system,
            user=rendered.user,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    messages = rendered.messages(str(getattr(llm, "system_message_mode", "separate") or "separate"))
    chat_messages = getattr(llm, "chat_messages", None)
    if callable(chat_messages):
        return chat_messages(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stop=list(rendered.stop),
        )
    if isinstance(llm, OpenAICompatibleLLM):
        payload = llm._payload(messages, temperature, max_tokens, None)
        if rendered.stop:
            payload["stop"] = list(rendered.stop)
        data = llm._post(payload).json()
        text = data["choices"][0]["message"]["content"]
        if llm.strip_reasoning:
            text = strip_reasoning_text(text)
        return ChatResponse(text=text, raw=data)
    raise TypeError(f"{type(llm).__name__} cannot send user-only chat prompts")


def _openai_compatible_completion(
    llm: OpenAICompatibleLLM,
    *,
    prompt: str,
    temperature: float,
    max_tokens: int,
    stop: list[str],
) -> ChatResponse:
    """POST a raw prompt to a local vLLM ``/completions`` route."""

    if getattr(llm, "provider", "vllm") != "vllm":
        raise ValueError("completion-transport prompt formats are only supported on local vLLM endpoints")
    payload: dict[str, Any] = {
        "model": llm.model,
        "prompt": prompt,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if stop:
        payload["stop"] = stop
    resp = requests.post(
        f"{llm.base_url}/completions",
        headers={"Authorization": f"Bearer {llm.api_key}"},
        json=payload,
        timeout=llm.timeout_sec,
    )
    resp.raise_for_status()
    data = resp.json()
    text = data["choices"][0]["text"]
    if llm.strip_reasoning:
        text = strip_reasoning_text(text)
    return ChatResponse(text=text, raw=data)


def choose_few_shots(
    examples: list[dict[str, Any]],
    *,
    current: dict[str, Any],
    k: int,
    mode: str = "ordered_same_category",
    seed: int = 13,
    max_question_similarity: float = 0.90,
    exclude_signature_match: bool = False,
) -> list[dict[str, Any]]:
    if k <= 0:
        return []
    if mode not in {"ordered_same_category", "random_same_category", "scored_no_signature"}:
        raise ValueError(f"unknown few-shot mode: {mode}")
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
    if mode == "ordered_same_category":
        ordered = sorted(same_graph_category, key=lambda item: str(item.get("id")))
        ordered.extend(sorted(same_graph, key=lambda item: str(item.get("id"))))
        return _annotate_selected(current=current, selected=ordered[:k], mode=mode)

    if mode == "random_same_category":
        rng = random.Random(f"{seed}:{current_id}")
        primary = sorted(same_graph_category, key=lambda item: str(item.get("id")))
        secondary = sorted(same_graph, key=lambda item: str(item.get("id")))
        rng.shuffle(primary)
        rng.shuffle(secondary)
        return _annotate_selected(
            current=current,
            selected=[*primary, *secondary][:k],
            mode=mode,
            seed=seed,
        )

    scored: list[tuple[float, dict[str, Any], bool]] = []
    current_tokens = tokenize(str(current.get("question", "")))
    current_signature = canonical_query_signature(str(current.get("cypher", "")))
    for item in sorted([*same_graph_category, *same_graph], key=lambda row: str(row.get("id"))):
        question_similarity = cosine_counts(
            current_tokens,
            tokenize(str(item.get("question", ""))),
        )
        signature_match = (
            canonical_query_signature(str(item.get("cypher", ""))) == current_signature
        )
        if exclude_signature_match and signature_match:
            continue
        if question_similarity >= max_question_similarity:
            continue
        scored.append((question_similarity, item, signature_match))
    scored.sort(key=lambda item: (-item[0], str(item[1].get("id"))))
    selected = [
        {
            **item,
            "few_shot_question_similarity": score,
            "few_shot_signature_match": signature_match,
        }
        for score, item, signature_match in scored[:k]
    ]
    return _annotate_selected(
        current=current,
        selected=selected,
        mode=mode,
        seed=seed,
        max_question_similarity=max_question_similarity,
        exclude_signature_match=exclude_signature_match,
    )


def selection_metadata(
    *,
    current: dict[str, Any],
    selected: list[dict[str, Any]],
) -> dict[str, Any]:
    current_signature = canonical_query_signature(str(current.get("cypher", "")))
    current_tokens = tokenize(str(current.get("question", "")))
    selected_rows = []
    for rank, item in enumerate(selected, start=1):
        similarity = float(
            item.get(
                "few_shot_question_similarity",
                cosine_counts(current_tokens, tokenize(str(item.get("question", "")))),
            )
        )
        signature = canonical_query_signature(str(item.get("cypher", "")))
        selected_rows.append(
            {
                "rank": rank,
                "id": str(item.get("id", "")),
                "graph_profile": str(item.get("graph_profile", "")),
                "category": str(item.get("category", "")),
                "question_similarity": similarity,
                "query_signature_match": signature == current_signature,
                "query_signature": signature,
            }
        )
    return {
        "mode": str(selected[0].get("few_shot_mode", "")) if selected else "",
        "seed": selected[0].get("few_shot_seed") if selected else None,
        "current_id": str(current.get("id", "")),
        "current_graph_profile": str(current.get("graph_profile", "")),
        "current_category": str(current.get("category", "")),
        "current_query_signature": current_signature,
        "selected_count": len(selected_rows),
        "selected": selected_rows,
    }


def _annotate_selected(
    *,
    current: dict[str, Any],
    selected: list[dict[str, Any]],
    mode: str,
    seed: int | None = None,
    max_question_similarity: float | None = None,
    exclude_signature_match: bool | None = None,
) -> list[dict[str, Any]]:
    current_tokens = tokenize(str(current.get("question", "")))
    current_signature = canonical_query_signature(str(current.get("cypher", "")))
    annotated = []
    for rank, item in enumerate(selected, start=1):
        question_similarity = float(
            item.get(
                "few_shot_question_similarity",
                cosine_counts(current_tokens, tokenize(str(item.get("question", "")))),
            )
        )
        signature_match = bool(
            item.get(
                "few_shot_signature_match",
                canonical_query_signature(str(item.get("cypher", ""))) == current_signature,
            )
        )
        annotated.append(
            {
                **item,
                "few_shot_rank": rank,
                "few_shot_mode": mode,
                "few_shot_seed": seed,
                "few_shot_question_similarity": question_similarity,
                "few_shot_signature_match": signature_match,
                "few_shot_max_question_similarity": max_question_similarity,
                "few_shot_exclude_signature_match": exclude_signature_match,
            }
        )
    return annotated


# Chat-template end markers that some local servers return as text (e.g. MLX
# serving Gemma-2 emits "<end_of_turn>"); everything after one is not the answer.
_END_OF_TURN_MARKERS = ("<end_of_turn>", "<eos>", "<|im_end|>", "<|eot_id|>", "<|end|>", "</s>")


def strip_end_of_turn(text: str) -> str:
    cut = len(text)
    for marker in _END_OF_TURN_MARKERS:
        index = text.find(marker)
        if index >= 0:
            cut = min(cut, index)
    return text[:cut]


def clean_predicted_cypher(text: str) -> str:
    cleaned = strip_code_fences(unescape_literal_whitespace(strip_end_of_turn(text))).strip()
    for prefix in ("Cypher:", "Query:", "Answer:"):
        if cleaned.lower().startswith(prefix.lower()):
            cleaned = cleaned[len(prefix) :].strip()
    for marker in ("Cypher query:", "Cypher:", "Query:", "Response:", "Answer:"):
        index = cleaned.lower().find(marker.lower())
        if index >= 0:
            cleaned = cleaned[index + len(marker) :].strip()
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


def unescape_literal_whitespace(text: str) -> str:
    """Turn escaped ``\\n``/``\\t``/``\\r`` emitted *as text* into whitespace.

    Some fine-tuned checkpoints emit JSON-style escapes (the two characters
    backslash + ``n``) instead of real newlines. Neo4j rejects those queries, so
    every prediction fails execution. Escapes inside quoted Cypher literals are
    preserved exactly.
    """

    if "\\" not in text:
        return text
    out: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(text):
        char = text[index]
        if quote:
            out.append(char)
            if char == "\\" and index + 1 < len(text):
                out.append(text[index + 1])
                index += 2
                continue
            if char == quote:
                quote = None
            index += 1
            continue
        if char in {"'", '"', "`"}:
            quote = char
            out.append(char)
            index += 1
            continue
        if char == "\\" and index + 1 < len(text) and text[index + 1] in "ntr":
            out.append("\n" if text[index + 1] == "n" else " ")
            index += 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


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
        "prompt_sha256": prediction.prompt_sha256,
        "prompt_format": prediction.prompt_format,
        "prompt_transport": prediction.prompt_transport,
        "system_message_mode": prediction.system_message_mode,
        "provider": prediction.provider,
        "few_shot_selection": prediction.few_shot_selection,
    }


def _few_shot_block(examples: list[dict[str, Any]]) -> str:
    if not examples:
        return ""
    parts = ["Examples:"]
    for example in examples:
        parts.append(f"Question: {example.get('question')}")
        parts.append(f"Cypher: {example.get('cypher')}")
    return "\n".join(parts) + "\n\n"
