from __future__ import annotations

import json
from unittest.mock import Mock, patch

from pipecypher.llm import OpenAICompatibleLLM, extract_json_text, strip_reasoning_text


def test_strip_reasoning_after_think_marker() -> None:
    text = "Thinking Process:\n\nNeed JSON.\n</think>\n\n{\"pass\": true}"

    assert strip_reasoning_text(text) == '{"pass": true}'


def test_extract_json_text_from_qwen_reasoning_preamble() -> None:
    text = (
        "Thinking Process:\n\n1. Build object.\n</think>\n\n"
        "```json\n{\"question\": \"q\", \"cypher\": \"MATCH (n) RETURN n\"}\n```"
    )

    assert json.loads(extract_json_text(text)) == {
        "question": "q",
        "cypher": "MATCH (n) RETURN n",
    }


def test_extract_json_text_finds_balanced_json_inside_prose() -> None:
    text = 'Here is the object: {"a": "{not a brace}", "b": [1, 2]} done.'

    assert json.loads(extract_json_text(text)) == {"a": "{not a brace}", "b": [1, 2]}


def test_openai_client_disables_qwen_thinking_by_default() -> None:
    response = Mock()
    response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": "</think>\n\nok",
                }
            }
        ]
    }

    with patch("pipecypher.llm.requests.post", return_value=response) as post:
        result = OpenAICompatibleLLM("http://localhost:8000/v1", "Qwen/Qwen3.5-9B").chat(
            system="sys",
            user="user",
        )

    payload = post.call_args.kwargs["json"]
    assert payload["reasoning_effort"] == "none"
    assert payload["include_reasoning"] is False
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert result.text == "ok"
