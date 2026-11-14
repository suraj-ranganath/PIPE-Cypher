from __future__ import annotations

import pytest

from pipecypher.config import RunConfig, validate_config
from pipecypher.llm import OpenAICompatibleLLM, resolve_api_key


class _Resp:
    def __init__(self, status: int, payload: dict | None = None):
        self.status_code = status
        self._payload = payload or {"choices": [{"message": {"content": "MATCH (n) RETURN n"}}]}

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"{self.status_code} error")

    def json(self):
        return self._payload


def test_vllm_payload_keeps_local_reasoning_controls():
    llm = OpenAICompatibleLLM("http://localhost:8000/v1", "Qwen/Qwen3.5-9B")
    payload = llm._payload([{"role": "user", "content": "q"}], 0.2, 64, None)
    assert payload["max_tokens"] == 64
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert payload["include_reasoning"] is False
    assert payload["reasoning_effort"] == "none"


def test_openai_payload_drops_vllm_only_fields(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("PIPE_CYPHER_LLM_API_KEY", raising=False)
    llm = OpenAICompatibleLLM(
        "https://api.openai.com/v1", "gpt-6-luna", provider="openai", send_temperature=False
    )
    payload = llm._payload([{"role": "user", "content": "q"}], 0.2, 64, None)
    assert payload == {
        "model": "gpt-6-luna",
        "messages": [{"role": "user", "content": "q"}],
        "max_completion_tokens": 64,
    }
    assert llm.api_key == "sk-test"


def test_openai_reasoning_effort_sent_only_when_set(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    llm = OpenAICompatibleLLM(
        "https://api.openai.com/v1", "m", provider="openai", reasoning_effort="low"
    )
    assert llm._payload([], 0.0, 8, None)["reasoning_effort"] == "low"


def test_api_key_never_defaults_to_openai_key_for_local_vllm(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("PIPE_CYPHER_LLM_API_KEY", raising=False)
    assert resolve_api_key("vllm") == "EMPTY"
    assert resolve_api_key("openai") == "sk-test"


def test_post_retries_rate_limits_but_not_404(monkeypatch):
    calls: list[int] = []
    statuses = iter([429, 503, 200])

    def fake_post(*_, **__):
        status = next(statuses)
        calls.append(status)
        return _Resp(status)

    monkeypatch.setattr("pipecypher.llm.requests.post", fake_post)
    monkeypatch.setattr("pipecypher.llm.time.sleep", lambda *_: None)
    llm = OpenAICompatibleLLM("http://x/v1", "m")
    assert llm.chat(system="s", user="u").text == "MATCH (n) RETURN n"
    assert calls == [429, 503, 200]

    monkeypatch.setattr("pipecypher.llm.requests.post", lambda *_, **__: _Resp(404))
    with pytest.raises(Exception, match="404"):
        llm.chat(system="s", user="u")


def test_null_content_becomes_empty_string(monkeypatch):
    monkeypatch.setattr(
        "pipecypher.llm.requests.post",
        lambda *_, **__: _Resp(200, {"choices": [{"message": {"content": None}}]}),
    )
    assert OpenAICompatibleLLM("http://x/v1", "m").chat(system="s", user="u").text == ""


def test_config_validates_provider_names():
    cfg = RunConfig()
    cfg.models.provider = "anthropic-ish"
    cfg.models.judge_provider = "bogus"
    errors = validate_config(cfg)
    assert any("models.provider" in e for e in errors)
    assert any("models.judge_provider" in e for e in errors)


def test_openrouter_payload_pins_routing_and_excludes_reasoning(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    routing = {"order": ["z-ai/fp8"], "allow_fallbacks": False, "require_parameters": True}
    llm = OpenAICompatibleLLM(
        "https://openrouter.ai/api/v1",
        "z-ai/glm-5.3-flash",
        provider="openrouter",
        reasoning_effort="low",
        provider_routing=routing,
    )
    payload = llm._payload([{"role": "user", "content": "q"}], 0.2, 256, None)
    assert payload["reasoning"] == {"effort": "low", "exclude": True}
    assert payload["provider"] == routing
    assert payload["max_tokens"] == 256
    assert "chat_template_kwargs" not in payload and "include_reasoning" not in payload
    assert llm.api_key == "or-test"


def test_openrouter_routing_from_env(monkeypatch):
    monkeypatch.setenv("PIPE_CYPHER_OPENROUTER_ROUTING", '{"order": ["z-ai/fp8"], "allow_fallbacks": false}')
    llm = OpenAICompatibleLLM("https://openrouter.ai/api/v1", "m", provider="openrouter")
    assert llm.provider_routing == {"order": ["z-ai/fp8"], "allow_fallbacks": False}


def test_spend_ledger_records_cost_and_enforces_cap(monkeypatch, tmp_path):
    from pipecypher.llm import BudgetExceededError

    ledger = tmp_path / "spend.jsonl"
    payload = {
        "provider": "Z.AI",
        "model": "z-ai/glm-5.3-flash",
        "choices": [{"message": {"content": "MATCH (n) RETURN n"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.6,
                  "completion_tokens_details": {"reasoning_tokens": 3}},
    }
    monkeypatch.setattr("pipecypher.llm.requests.post", lambda *_, **__: _Resp(200, payload))
    llm = OpenAICompatibleLLM(
        "https://openrouter.ai/api/v1", "z-ai/glm-5.3-flash", provider="openrouter",
        usage_ledger=str(ledger), max_cost_usd=1.0, call_label="judge",
    )
    llm.chat(system="s", user="u")
    llm.chat(system="s", user="u")
    import json as _json
    rows = [_json.loads(line) for line in ledger.read_text().splitlines()]
    assert [r["served_by"] for r in rows] == ["Z.AI", "Z.AI"]
    assert rows[0]["reasoning_tokens"] == 3 and rows[0]["label"] == "judge"
    with pytest.raises(BudgetExceededError):
        llm.chat(system="s", user="u")
    # A fresh process sharing the ledger sees the same spend.
    other = OpenAICompatibleLLM(
        "https://openrouter.ai/api/v1", "m", provider="openrouter",
        usage_ledger=str(ledger), max_cost_usd=1.0,
    )
    with pytest.raises(BudgetExceededError):
        other.chat(system="s", user="u")


def test_config_requires_pinned_openrouter_routing():
    cfg = RunConfig()
    cfg.models.provider = "openrouter"
    cfg.models.provider_routing = {"order": ["z-ai/fp8"]}
    assert any("allow_fallbacks" in e for e in validate_config(cfg))
    cfg.models.provider_routing = {"order": ["z-ai/fp8"], "allow_fallbacks": False}
    assert not any("provider_routing" in e for e in validate_config(cfg))
