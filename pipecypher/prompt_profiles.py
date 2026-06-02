from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptProfile:
    name: str
    label: str
    include_examples: bool
    include_instructions: bool
    include_entity_hints: bool
    governed: bool


PROMPT_PROFILES: dict[str, PromptProfile] = {
    "schema_only": PromptProfile(
        name="schema_only",
        label="Schema only",
        include_examples=False,
        include_instructions=False,
        include_entity_hints=False,
        governed=False,
    ),
    "instructions_only": PromptProfile(
        name="instructions_only",
        label="Instructions only",
        include_examples=False,
        include_instructions=True,
        include_entity_hints=False,
        governed=False,
    ),
    "examples_only": PromptProfile(
        name="examples_only",
        label="Examples only",
        include_examples=True,
        include_instructions=False,
        include_entity_hints=False,
        governed=False,
    ),
    "examples_plus_instructions": PromptProfile(
        name="examples_plus_instructions",
        label="Examples + instructions",
        include_examples=True,
        include_instructions=True,
        include_entity_hints=False,
        governed=False,
    ),
    "full_pipe_cypher_governed": PromptProfile(
        name="full_pipe_cypher_governed",
        label="Full governed PIPE-Cypher",
        include_examples=True,
        include_instructions=True,
        include_entity_hints=True,
        governed=True,
    ),
}


def allowed_prompt_profiles() -> set[str]:
    return set(PROMPT_PROFILES)


def get_prompt_profile(name: str) -> PromptProfile:
    try:
        return PROMPT_PROFILES[name]
    except KeyError as exc:
        allowed = ", ".join(sorted(PROMPT_PROFILES))
        raise ValueError(f"unknown prompt profile {name!r}; expected one of {allowed}") from exc
