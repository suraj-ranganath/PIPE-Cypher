"""Prompt-format registry for downstream Text2Cypher evaluation.

Every downstream prediction records the prompt format that produced it. Three
kinds of formats exist:

``pipe_standard``
    Byte-identical to the historical ``TEXT2CYPHER_SYSTEM`` /
    ``TEXT2CYPHER_PROMPT`` behaviour in :mod:`pipecypher.text2cypher`, so older
    downstream runs stay reproducible.
``pipe_governed``
    ``pipe_standard`` plus the answer conventions the benchmark generator was
    held to (contextual return columns, relationship-direction discipline,
    exact literals, categorical values, read-only tokens, reserved variables).
    The convention text is derived from :mod:`pipecypher.validator` constants
    and the active schema, never hand-copied, so it cannot drift from the
    gates that shaped the reference queries.
``native_<slug>``
    The prompt format documented by a public Text2Cypher checkpoint's model
    card (or its official companion material). Each builder carries the source
    URL and reproduces the documented template verbatim. Checkpoints whose
    cards document no format have no ``native_*`` entry; they are evaluated
    with ``pipe_standard`` and reported as "no documented format".

See ``knowledge_base/downstream_prompt_formats.md`` for the per-model evidence.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from . import text2cypher as _t2c
from .models import SchemaSummary
from .validator import CONTEXTUAL_RETURN_PROPERTIES, RESERVED_VARIABLES, WRITE_TOKENS

CHAT = "chat"
COMPLETION = "completion"
TRANSPORTS = (CHAT, COMPLETION)

DEFAULT_PROMPT_FORMAT = "pipe_standard"


class UnknownPromptFormatError(ValueError):
    """Raised for prompt-format names that are not registered."""


class PromptFormatUsageError(ValueError):
    """Raised when a format is used outside its documented contract."""


@dataclass(frozen=True)
class RenderedPrompt:
    """A prompt ready to send: ``(system, user)`` plus transport metadata.

    ``system`` is ``None`` when the documented format sends a single user
    message. For ``transport == "completion"`` the ``user`` text is the full raw
    prompt sent to ``/completions`` (no chat template is applied).
    Iterating yields ``(system, user)`` so callers may unpack it as a pair.
    """

    format_name: str
    system: str | None
    user: str
    transport: str = CHAT
    stop: tuple[str, ...] = ()

    def __iter__(self) -> Iterator[str | None]:
        yield self.system
        yield self.user

    def messages(self, system_message_mode: str = "separate") -> list[dict[str, str]]:
        """Chat messages exactly as the client sends them for this mode."""

        if self.transport != CHAT:
            raise PromptFormatUsageError(
                f"prompt format {self.format_name!r} uses {self.transport!r} transport, not chat"
            )
        if self.system is None:
            return [{"role": "user", "content": self.user}]
        from .llm import _chat_messages

        return _chat_messages(self.system, self.user, mode=system_message_mode)

    def request_body(self, system_message_mode: str = "separate") -> dict[str, Any]:
        """The prompt-bearing part of the request (messages or raw prompt)."""

        if self.transport == COMPLETION:
            body: dict[str, Any] = {"prompt": self.user}
        else:
            body = {"messages": self.messages(system_message_mode)}
        if self.stop:
            body["stop"] = list(self.stop)
        return body

    def sha256(self, system_message_mode: str = "separate") -> str:
        """Hash of the prompt content actually sent to the endpoint."""

        payload = json.dumps(
            self.request_body(system_message_mode),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


PromptBuilder = Callable[..., RenderedPrompt]


@dataclass(frozen=True)
class PromptFormat:
    name: str
    description: str
    builder: PromptBuilder
    transport: str = CHAT
    supports_few_shot: bool = True
    documented: bool = False
    source_url: str | None = None
    source_note: str = ""
    model_hf_ids: tuple[str, ...] = field(default_factory=tuple)

    def build(
        self,
        *,
        schema_text: str,
        question: str,
        few_shot_examples: list[dict[str, Any]] | None = None,
        schema: SchemaSummary | None = None,
    ) -> RenderedPrompt:
        examples = list(few_shot_examples or [])
        if examples and not self.supports_few_shot:
            raise PromptFormatUsageError(
                f"prompt format {self.name!r} reproduces a documented zero-shot template; "
                "few-shot examples are not part of that format. Use pipe_standard for few-shot runs."
            )
        rendered = self.builder(
            schema_text=schema_text,
            question=question,
            few_shot_examples=examples,
            schema=schema,
        )
        if rendered.format_name != self.name or rendered.transport != self.transport:
            raise PromptFormatUsageError(f"builder for {self.name!r} returned inconsistent metadata")
        return rendered


# ---------------------------------------------------------------------------
# PIPE-Cypher formats
# ---------------------------------------------------------------------------


def _pipe_standard_user(schema_text: str, question: str, examples: list[dict[str, Any]]) -> str:
    return _t2c.TEXT2CYPHER_PROMPT.format(
        schema=schema_text,
        few_shot_block=_t2c._few_shot_block(examples),
        question=question,
    )


def _build_pipe_standard(
    *,
    schema_text: str,
    question: str,
    few_shot_examples: list[dict[str, Any]],
    schema: SchemaSummary | None = None,
) -> RenderedPrompt:
    return RenderedPrompt(
        format_name="pipe_standard",
        system=_t2c.TEXT2CYPHER_SYSTEM,
        user=_pipe_standard_user(schema_text, question, few_shot_examples),
    )


GOVERNED_CONVENTIONS_HEADER = (
    "Answer conventions used when the benchmark reference queries were generated "
    "and validated:"
)


def contextual_return_rules(
    schema: SchemaSummary | None = None,
) -> list[tuple[str, str, tuple[str, ...]]]:
    """``(label, trigger_property, required_properties)`` from the validator.

    With a schema, a rule is kept only when its label and trigger property exist
    in that schema, and its required columns are narrowed to properties the
    schema actually has (asking for a nonexistent column would only produce
    schema errors). A rule for an absent label can never fire on a valid query.
    """

    rules: list[tuple[str, str, tuple[str, ...]]] = []
    for label in sorted(CONTEXTUAL_RETURN_PROPERTIES):
        for trigger, required in sorted(CONTEXTUAL_RETURN_PROPERTIES[label].items()):
            required_props = tuple(required)
            if schema is not None:
                if label not in schema.labels:
                    continue
                props = schema.properties_for_label(label)
                if trigger not in props:
                    continue
                required_props = tuple(prop for prop in required_props if prop in props)
                if not required_props:
                    continue
            rules.append((label, trigger, required_props))
    return rules


def governed_answer_conventions(schema: SchemaSummary | None = None) -> list[str]:
    """Bullet lines describing the generator-side answer conventions.

    Derived from ``pipecypher.validator`` constants (contextual return
    properties, write tokens, reserved variables) and from the schema
    (relationship directions, categorical properties).
    """

    lines: list[str] = []
    for label, trigger, required in contextual_return_rules(schema):
        required_text = ", ".join(f":{label}.{prop}" for prop in required)
        lines.append(
            f"- Contextual return columns: whenever RETURN projects :{label}.{trigger}, "
            f"also return {required_text} from the same node "
            "(returning the node variable itself also satisfies this)."
        )
    symmetric = _symmetric_relationships(schema)
    if symmetric:
        lines.append(
            "- Every relationship pattern must name a schema relationship type and use an explicit "
            "direction (-> or <-); never write bidirectional (<-->) patterns, and write undirected "
            "patterns only for the symmetric relationship types "
            + ", ".join(f":{rel}" for rel in symmetric)
            + " (e.g. -[:"
            + symmetric[0]
            + "]-)."
        )
    else:
        lines.append(
            "- Every relationship pattern must name a schema relationship type and use an explicit "
            "direction (-> or <-); never write undirected (--) or bidirectional (<-->) patterns."
        )
    example = _direction_example(schema)
    lines.append(
        "- Keep every directed relationship in the direction listed under Relationship patterns"
        + (f", e.g. {example}" if example else "")
        + "; if the question reads in the opposite direction, write the arrow back from the end "
        "node (<-) or use comma-separated MATCH patterns instead of reversing the edge."
    )
    lines.append(
        "- Copy quoted values from the question into string literals character for character "
        "(same case, spacing, and punctuation) and match them with exact equality; do not use "
        "CONTAINS, STARTS WITH, ENDS WITH, =~, or toLower() for quoted values."
    )
    lines.append("- Use CONTAINS or case-insensitive matching only for unquoted fuzzy phrasing.")
    categorical = sorted(schema.categorical_properties) if schema is not None else []
    if categorical:
        lines.append(
            "- Literal filters on categorical properties ("
            + ", ".join(f":{key}" for key in categorical)
            + ") must use one of the listed categorical values exactly."
        )
    elif schema is None:
        lines.append(
            "- Literal filters on categorical properties must use one of the listed "
            "categorical values exactly."
        )
    lines.append(
        "- Include the nodes or properties the question explicitly asks for in the RETURN clause; "
        "do not return a bare unlabeled node variable."
    )
    lines.append(
        "- Avoid OPTIONAL MATCH unless the question asks for missing or optional data; "
        "avoid CALL and UNION."
    )
    lines.append(
        "- The query must be read-only: never use "
        + ", ".join(WRITE_TOKENS)
        + "."
    )
    lines.append(
        "- Do not name variables "
        + ", ".join(sorted(RESERVED_VARIABLES))
        + "."
    )
    return lines


def governed_conventions_block(schema: SchemaSummary | None = None) -> str:
    return "\n".join(
        [GOVERNED_CONVENTIONS_HEADER, *governed_answer_conventions(schema), "Return only the Cypher query."]
    )


def _symmetric_relationships(schema: SchemaSummary | None) -> list[str]:
    """Relationship types the validator accepts without a direction."""

    if schema is None:
        return []
    return sorted({str(rel) for rel in getattr(schema, "symmetric_relationships", None) or [] if rel})


def _direction_example(schema: SchemaSummary | None) -> str:
    if schema is None or not schema.relationships:
        return ""
    symmetric = set(_symmetric_relationships(schema))
    directed = [rel for rel in schema.relationships if rel.type not in symmetric]
    if not directed:
        return ""
    rel = sorted(directed, key=lambda item: (item.start_label, item.type, item.end_label))[0]
    return f"(:{rel.start_label})-[:{rel.type}]->(:{rel.end_label})"


def _build_pipe_governed(
    *,
    schema_text: str,
    question: str,
    few_shot_examples: list[dict[str, Any]],
    schema: SchemaSummary | None = None,
) -> RenderedPrompt:
    standard = _pipe_standard_user(schema_text, question, few_shot_examples)
    return RenderedPrompt(
        format_name="pipe_governed",
        system=_t2c.TEXT2CYPHER_SYSTEM,
        user=standard + "\n\n" + governed_conventions_block(schema),
    )


# ---------------------------------------------------------------------------
# Native (model-card documented) formats. Templates are verbatim copies.
# ---------------------------------------------------------------------------

# Source: https://huggingface.co/neo4j/text2cypher-gemma-2-9b-it-finetuned-2024v1
# ("Example Cypher generation" section): single user message, no system turn.
NEO4J_GEMMA2_2024_INSTRUCTION = (
    "Generate Cypher statement to query a graph database. "
    "Use only the provided relationship types and properties in the schema. \n"
    "Schema: {schema} \n Question: {question}  \n Cypher output: "
)


def _build_native_neo4j_gemma2_2024(
    *,
    schema_text: str,
    question: str,
    few_shot_examples: list[dict[str, Any]],
    schema: SchemaSummary | None = None,
) -> RenderedPrompt:
    return RenderedPrompt(
        format_name="native_neo4j_gemma2_2024",
        system=None,
        user=NEO4J_GEMMA2_2024_INSTRUCTION.format(schema=schema_text, question=question),
    )


# Source: Neo4j's official Colab linked from
# https://neo4j.com/blog/news/text2cypher-vertex-ai/ ("You will need to prompt
# the model in a similar way the model was finetuned"):
# https://colab.research.google.com/drive/1HeESE-saKNN-ZfUv06axBrnSWuN0ijlc
# The Hugging Face model cards for the Gemma-3 4B/27B checkpoints document no
# prompt format themselves. Single user message, no system turn.
NEO4J_GEMMA3_2025_USER_PROMPT_TEMPLATE = """Generate a Cypher query for the Question below.
Use the information about the nodes, relationships, and properties from the Schema section below to generate the best possible Cypher query.
Return only the Cypher query as your final output, without any additional text or explanation.
####Schema:
{schema}
####Question:
{question}"""


def _build_native_neo4j_gemma3_2025(
    *,
    schema_text: str,
    question: str,
    few_shot_examples: list[dict[str, Any]],
    schema: SchemaSummary | None = None,
) -> RenderedPrompt:
    return RenderedPrompt(
        format_name="native_neo4j_gemma3_2025",
        system=None,
        user=NEO4J_GEMMA3_2025_USER_PROMPT_TEMPLATE.format(schema=schema_text, question=question),
    )


# Source: https://huggingface.co/tomasonjo/text2cypher-demo-16bit ("Example usage"),
# same template as the training notebook
# https://github.com/neo4j-labs/text2cypher/blob/main/finetuning/unsloth-llama3/llama3_text2cypher_chat.ipynb
TOMASONJO_SYSTEM = "Given an input question, convert it to a Cypher query. No pre-amble."
TOMASONJO_USER_TEMPLATE = """Based on the Neo4j graph schema below, write a Cypher query that would answer the user's question:
{schema}

Question: {question}
Cypher query:"""


def _build_native_tomasonjo_llama3(
    *,
    schema_text: str,
    question: str,
    few_shot_examples: list[dict[str, Any]],
    schema: SchemaSummary | None = None,
) -> RenderedPrompt:
    return RenderedPrompt(
        format_name="native_tomasonjo_llama3",
        system=TOMASONJO_SYSTEM,
        user=TOMASONJO_USER_TEMPLATE.format(schema=schema_text, question=question),
    )


# Source: https://huggingface.co/Azzedde/llama3.1-8b-text2cypher ("How to Get
# Started with the Model"): raw Alpaca-style prompt passed straight to the
# tokenizer (no chat template), so it is sent to /completions.
AZZEDDE_CYPHER_PROMPT = """Below is a database Neo4j schema and a question related to that database. Write a Cypher query to answer the question.

### Schema:
{schema}

### Question:
{question}

### Cypher:
"""


def _build_native_azzedde_alpaca(
    *,
    schema_text: str,
    question: str,
    few_shot_examples: list[dict[str, Any]],
    schema: SchemaSummary | None = None,
) -> RenderedPrompt:
    return RenderedPrompt(
        format_name="native_azzedde_alpaca",
        system=None,
        user=AZZEDDE_CYPHER_PROMPT.format(schema=schema_text, question=question),
        transport=COMPLETION,
        # The template delimits sections with "###"; stop at the next section
        # header so trailing sections are not concatenated into the query.
        stop=("\n###",),
    )


# Source: https://huggingface.co/ragraph-ai/stable-cypher-instruct-3b ("Usage"):
# ChatML with this system message (also the tokenizer chat template's default)
# and the bare question as the user turn. The documented format includes NO
# graph schema.
STABLE_CYPHER_SYSTEM = "Create a Cypher statement to answer the following question:"


def _build_native_stable_cypher(
    *,
    schema_text: str,
    question: str,
    few_shot_examples: list[dict[str, Any]],
    schema: SchemaSummary | None = None,
) -> RenderedPrompt:
    return RenderedPrompt(
        format_name="native_stable_cypher",
        system=STABLE_CYPHER_SYSTEM,
        user=question,
    )


PROMPT_FORMATS: dict[str, PromptFormat] = {
    "pipe_standard": PromptFormat(
        name="pipe_standard",
        description="Historical PIPE-Cypher downstream prompt (TEXT2CYPHER_SYSTEM + TEXT2CYPHER_PROMPT).",
        builder=_build_pipe_standard,
    ),
    "pipe_governed": PromptFormat(
        name="pipe_governed",
        description=(
            "pipe_standard plus the generator-side answer conventions derived from "
            "pipecypher.validator constants and the active schema."
        ),
        builder=_build_pipe_governed,
    ),
    "native_neo4j_gemma2_2024": PromptFormat(
        name="native_neo4j_gemma2_2024",
        description="Neo4j Text2Cypher (2024) Gemma-2 LoRA instruction, single user turn.",
        builder=_build_native_neo4j_gemma2_2024,
        supports_few_shot=False,
        documented=True,
        source_url="https://huggingface.co/neo4j/text2cypher-gemma-2-9b-it-finetuned-2024v1",
        source_note="Model card, 'Example Cypher generation' section.",
        model_hf_ids=("neo4j/text2cypher-gemma-2-9b-it-finetuned-2024v1",),
    ),
    "native_neo4j_gemma3_2025": PromptFormat(
        name="native_neo4j_gemma3_2025",
        description="Neo4j Text2Cypher (2025) Gemma-3 user prompt from Neo4j's official Colab.",
        builder=_build_native_neo4j_gemma3_2025,
        supports_few_shot=False,
        documented=True,
        source_url="https://colab.research.google.com/drive/1HeESE-saKNN-ZfUv06axBrnSWuN0ijlc",
        source_note=(
            "Not on the HF model cards (they document no format); official Neo4j Colab linked "
            "from https://neo4j.com/blog/news/text2cypher-vertex-ai/."
        ),
        model_hf_ids=(
            "neo4j/text-to-cypher-Gemma-3-4B-Instruct-2025.04.0",
            "neo4j/text-to-cypher-Gemma-3-27B-Instruct-2025.04.0",
        ),
    ),
    "native_tomasonjo_llama3": PromptFormat(
        name="native_tomasonjo_llama3",
        description="tomasonjo Llama-3 Text2Cypher demo chat prompt (system + user).",
        builder=_build_native_tomasonjo_llama3,
        supports_few_shot=False,
        documented=True,
        source_url="https://huggingface.co/tomasonjo/text2cypher-demo-16bit",
        source_note="Model card, 'Example usage' section.",
        model_hf_ids=("tomasonjo/text2cypher-demo-16bit",),
    ),
    "native_azzedde_alpaca": PromptFormat(
        name="native_azzedde_alpaca",
        description="Azzedde Llama-3.1 Text2Cypher raw Alpaca-style completion prompt.",
        builder=_build_native_azzedde_alpaca,
        transport=COMPLETION,
        supports_few_shot=False,
        documented=True,
        source_url="https://huggingface.co/Azzedde/llama3.1-8b-text2cypher",
        source_note="Model card, 'How to Get Started with the Model' section.",
        model_hf_ids=("Azzedde/llama3.1-8b-text2cypher",),
    ),
    "native_stable_cypher": PromptFormat(
        name="native_stable_cypher",
        description="ragraph-ai stable-cypher ChatML prompt: fixed system message + bare question.",
        builder=_build_native_stable_cypher,
        supports_few_shot=False,
        documented=True,
        source_url="https://huggingface.co/ragraph-ai/stable-cypher-instruct-3b",
        source_note="Model card, 'Usage' section (Safetensors and GGUF examples).",
        model_hf_ids=("ragraph-ai/stable-cypher-instruct-3b",),
    ),
}


def allowed_prompt_formats() -> list[str]:
    return sorted(PROMPT_FORMATS)


def get_prompt_format(name: str) -> PromptFormat:
    try:
        return PROMPT_FORMATS[name]
    except KeyError as exc:
        raise UnknownPromptFormatError(
            f"unknown prompt format {name!r}; expected one of {', '.join(allowed_prompt_formats())}"
        ) from exc


def render_prompt(
    name: str,
    *,
    schema_text: str,
    question: str,
    few_shot_examples: list[dict[str, Any]] | None = None,
    schema: SchemaSummary | None = None,
) -> RenderedPrompt:
    return get_prompt_format(name).build(
        schema_text=schema_text,
        question=question,
        few_shot_examples=few_shot_examples,
        schema=schema,
    )


def native_formats_for_model(hf_id: str) -> list[str]:
    return sorted(
        name for name, fmt in PROMPT_FORMATS.items() if hf_id in fmt.model_hf_ids
    )
