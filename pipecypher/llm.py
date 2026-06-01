from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import requests


@dataclass
class ChatResponse:
    text: str
    raw: dict[str, Any]


class OpenAICompatibleLLM:
    """Minimal client for vLLM/OpenAI-compatible local model servers."""

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        timeout_sec: int = 120,
        api_key: str = "EMPTY",
        reasoning_effort: str | None = "none",
        include_reasoning: bool | None = False,
        enable_thinking: bool | None = False,
        strip_reasoning: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_sec = timeout_sec
        self.api_key = api_key
        self.reasoning_effort = reasoning_effort
        self.include_reasoning = include_reasoning
        self.enable_thinking = enable_thinking
        self.strip_reasoning = strip_reasoning

    def chat(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        response_format: dict[str, Any] | None = None,
    ) -> ChatResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format
        if self.reasoning_effort is not None:
            payload["reasoning_effort"] = self.reasoning_effort
        if self.include_reasoning is not None:
            payload["include_reasoning"] = self.include_reasoning
        if self.enable_thinking is not None:
            payload["chat_template_kwargs"] = {"enable_thinking": self.enable_thinking}
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
            timeout=self.timeout_sec,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        if self.strip_reasoning:
            text = strip_reasoning_text(text)
        return ChatResponse(text=text, raw=data)

    def chat_json(self, **kwargs: Any) -> Any:
        text = extract_json_text(self.chat(**kwargs).text)
        return json.loads(text)


class NullLLM:
    """LLM stub used for offline tests and deterministic smoke runs."""

    model = "null-llm"

    def chat(self, **_: Any) -> ChatResponse:
        raise RuntimeError("No LLM configured")

    def chat_json(self, **_: Any) -> Any:
        raise RuntimeError("No LLM configured")


def strip_reasoning_text(text: str) -> str:
    """Remove common reasoning preambles emitted by local Qwen-style models."""

    cleaned = text.strip()
    if "</think>" in cleaned:
        cleaned = cleaned.split("</think>", 1)[1].strip()
    if cleaned.startswith("<think>") and "</think>" in cleaned:
        cleaned = cleaned.split("</think>", 1)[1].strip()
    return cleaned


def extract_json_text(text: str) -> str:
    cleaned = strip_reasoning_text(text).strip()
    if cleaned.startswith("```"):
        parts = cleaned.split("```")
        if len(parts) >= 3:
            cleaned = parts[1].strip()
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()
    try:
        json.loads(cleaned)
        return cleaned
    except json.JSONDecodeError:
        pass

    extracted = _first_balanced_json(cleaned)
    if extracted is None:
        raise json.JSONDecodeError("No JSON object or array found", cleaned, 0)
    return extracted


def _first_balanced_json(text: str) -> str | None:
    for start, opener in enumerate(text):
        if opener not in "{[":
            continue
        closer = "}" if opener == "{" else "]"
        stack = [closer]
        in_string = False
        escaped = False
        for idx in range(start + 1, len(text)):
            char = text[idx]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char in "{[":
                stack.append("}" if char == "{" else "]")
            elif stack and char == stack[-1]:
                stack.pop()
                if not stack:
                    candidate = text[start : idx + 1]
                    try:
                        json.loads(candidate)
                    except json.JSONDecodeError:
                        break
                    return candidate
        continue
    return None
