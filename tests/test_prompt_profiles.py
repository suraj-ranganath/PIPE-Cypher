from __future__ import annotations

import pytest

from pipecypher.config import RunConfig, validate_config
from pipecypher.graph_profiles import finbench_reference_schema
from pipecypher.prompts import render_cypher_generation_prompt
from pipecypher.prompt_profiles import get_prompt_profile


def test_validate_config_accepts_known_prompt_profiles():
    config = RunConfig()
    config.generation.prompt_profile = "examples_plus_instructions"

    assert validate_config(config) == []


def test_validate_config_rejects_unknown_prompt_profile():
    config = RunConfig()
    config.generation.prompt_profile = "examples_plus_instruction"

    errors = validate_config(config)

    assert any("generation.prompt_profile" in error for error in errors)


def test_render_schema_only_prompt_excludes_examples_and_full_rules():
    prompt = render_cypher_generation_prompt(
        profile_name="schema_only",
        schema=finbench_reference_schema().to_prompt(max_items=5),
        question="List accounts.",
        examples="Question: example\nCypher: MATCH (n) RETURN n",
        entity_hints={"account": "A1 | Account.accountId"},
    )

    assert "Graph schema:" in prompt
    assert "Retrieved examples" not in prompt
    assert "Entity hints" not in prompt
    assert "All set-returning RETURN clauses" not in prompt


def test_render_examples_plus_instructions_prompt_includes_examples_and_rules():
    prompt = render_cypher_generation_prompt(
        profile_name="examples_plus_instructions",
        schema=finbench_reference_schema().to_prompt(max_items=5),
        question="List accounts.",
        examples="Question: example\nCypher: MATCH (n) RETURN DISTINCT n",
        entity_hints={"account": "A1 | Account.accountId"},
    )

    assert "Retrieved examples:" in prompt
    assert "RETURN DISTINCT" in prompt
    assert "Entity hints" not in prompt


def test_get_prompt_profile_rejects_unknown_name():
    with pytest.raises(ValueError, match="unknown prompt profile"):
        get_prompt_profile("bad")
