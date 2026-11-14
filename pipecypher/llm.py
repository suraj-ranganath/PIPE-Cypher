from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

import requests

PROVIDERS = ("vllm", "openai", "openrouter")
HOSTED_PROVIDERS = ("openai", "openrouter")
DEFAULT_BASE_URLS = {
    "vllm": "http://localhost:8000/v1",
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}
_PROVIDER_KEY_ENV = {"openai": "OPENAI_API_KEY", "openrouter": "OPENROUTER_API_KEY"}
_RETRY_STATUS = {429, 500, 502, 503, 504}
_LEDGER_RESYNC_EVERY = 25


class FatalLLMError(BaseException):
    """Unrecoverable endpoint condition (auth, credits, unknown hosted model, budget).

    Deliberately a BaseException: generation and judging code catch ``Exception``
    to fall back to deterministic templates or the rule-based judge, and an
    exhausted account must stop the run instead of silently degrading it.
    """


class BudgetExceededError(FatalLLMError):
    """Raised before a request once the shared spend ledger reaches the USD cap."""


_HOSTED_FATAL_STATUS = {401, 402, 403, 404}


def resolve_api_key(provider: str = "vllm", api_key: str | None = None) -> str:
    """Explicit key > provider key env (OPENAI_API_KEY / OPENROUTER_API_KEY) >
    PIPE_CYPHER_LLM_API_KEY > "EMPTY".

    Keys are read from the environment so they never land in configs, logs, or
    run metadata. A local vLLM endpoint never receives a hosted provider's key.
    """

    if api_key:
        return api_key
    env_name = _PROVIDER_KEY_ENV.get(provider)
    if env_name and os.environ.get(env_name):
        return os.environ[env_name]
    if os.environ.get("PIPE_CYPHER_LLM_API_KEY"):
        return os.environ["PIPE_CYPHER_LLM_API_KEY"]
    return "EMPTY"


def _env_bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def provider_routing_from_env() -> dict[str, Any] | None:
    raw = os.environ.get("PIPE_CYPHER_OPENROUTER_ROUTING", "").strip()
    return json.loads(raw) if raw else None


class SpendLedger:
    """Append-only JSONL ledger of hosted calls with a shared USD cap.

    Several processes may share one ledger file; each re-reads the file total
    every few calls, so the cap holds across parallel workers up to a small
    in-flight overshoot.
    """

    def __init__(self, path: str | None, max_cost_usd: float | None) -> None:
        self.path = path
        self.max_cost_usd = max_cost_usd
        self._local_since_sync = 0.0
        self._calls_since_sync = 0
        self._file_total = self._read_total()

    def _read_total(self) -> float:
        if not self.path or not os.path.exists(self.path):
            return 0.0
        total = 0.0
        with open(self.path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    total += float(json.loads(line).get("cost_usd") or 0.0)
                except (ValueError, AttributeError):
                    continue
        return total

    @property
    def total(self) -> float:
        return self._file_total + self._local_since_sync

    def _cap(self) -> float | None:
        """Cap from ``<ledger>.cap`` when present (raise it to resume a paused run), else the configured cap."""

        if self.path and os.path.exists(f"{self.path}.cap"):
            try:
                with open(f"{self.path}.cap", encoding="utf-8") as handle:
                    return float(handle.read().strip())
            except ValueError:
                pass
        return self.max_cost_usd

    def check(self) -> None:
        cap = self._cap()
        if cap is None or self.total < cap:
            return
        if not _env_bool("PIPE_CYPHER_PAUSE_ON_CAP") or not self.path:
            raise BudgetExceededError(
                f"spend ledger total ${self.total:.4f} reached cap ${cap:.2f} ({self.path})"
            )
        # Pause instead of exiting: a budget stop must never cut a run short.
        # Raising the number in <ledger>.cap resumes every paused worker.
        marker = f"{self.path}.paused"
        while True:
            self._file_total = self._read_total()
            self._local_since_sync = 0.0
            self._calls_since_sync = 0
            cap = self._cap()
            if cap is None or self.total < cap:
                if os.path.exists(marker):
                    try:
                        os.remove(marker)
                    except OSError:
                        pass
                return
            with open(marker, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps({"ts": time.time(), "total_usd": round(self.total, 4), "cap_usd": cap, "pid": os.getpid()})
                    + "\n"
                )
            time.sleep(float(os.environ.get("PIPE_CYPHER_PAUSE_POLL_SEC", "60")))

    def record(self, entry: dict[str, Any]) -> None:
        cost = float(entry.get("cost_usd") or 0.0)
        if self.path:
            line = json.dumps(entry, sort_keys=True) + "\n"
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(line)
        self._local_since_sync += cost
        self._calls_since_sync += 1
        if self.path and self._calls_since_sync >= _LEDGER_RESYNC_EVERY:
            self._file_total = self._read_total()
            self._local_since_sync = 0.0
            self._calls_since_sync = 0


@dataclass
class ChatResponse:
    text: str
    raw: dict[str, Any]


class OpenAICompatibleLLM:
    """Client for local vLLM servers (``provider="vllm"``) or the hosted OpenAI API.

    ``provider="openai"`` drops vLLM-only request fields (``include_reasoning``,
    ``chat_template_kwargs``), sends ``max_completion_tokens``, omits
    ``reasoning_effort`` when it is unset/"none", and can omit ``temperature``
    for models that only accept the default. Hosted models are evaluation
    instruments for public graphs only; see AGENTS.md.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        timeout_sec: int = 120,
        api_key: str | None = None,
        reasoning_effort: str | None = "none",
        include_reasoning: bool | None = False,
        enable_thinking: bool | None = False,
        strip_reasoning: bool = True,
        system_message_mode: str = "separate",
        provider: str = "vllm",
        send_temperature: bool = True,
        max_retries: int = 4,
        provider_routing: dict[str, Any] | None = None,
        usage_ledger: str | None = None,
        max_cost_usd: float | None = None,
        call_label: str | None = None,
        seed: int | None = None,
    ) -> None:
        if system_message_mode not in {"separate", "merge"}:
            raise ValueError("system_message_mode must be 'separate' or 'merge'")
        if provider not in PROVIDERS:
            raise ValueError(f"provider must be one of {PROVIDERS}")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_sec = timeout_sec
        self.provider = provider
        self.api_key = resolve_api_key(provider, api_key)
        self.send_temperature = send_temperature
        self.max_retries = max_retries
        self.provider_routing = (
            provider_routing if provider_routing is not None else (
                provider_routing_from_env() if provider == "openrouter" else None
            )
        )
        if max_cost_usd is None and os.environ.get("PIPE_CYPHER_MAX_COST_USD"):
            max_cost_usd = float(os.environ["PIPE_CYPHER_MAX_COST_USD"])
        self.ledger = SpendLedger(usage_ledger or os.environ.get("PIPE_CYPHER_USAGE_LEDGER"), max_cost_usd)
        self.call_label = call_label or os.environ.get("PIPE_CYPHER_CALL_LABEL")
        self.reasoning_effort = reasoning_effort
        self.include_reasoning = include_reasoning
        self.enable_thinking = enable_thinking
        self.strip_reasoning = strip_reasoning
        self.system_message_mode = system_message_mode
        # Sent as ``seed`` to OpenRouter (honored by providers that support it,
        # e.g. Novita); a reproducibility aid, not a bit-identical guarantee.
        self.seed = seed

    def chat(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        response_format: dict[str, Any] | None = None,
    ) -> ChatResponse:
        messages = _chat_messages(system, user, mode=self.system_message_mode)
        payload = self._payload(messages, temperature, max_tokens, response_format)
        self.ledger.check()
        started = time.time()
        resp = self._post(payload)
        data = resp.json()
        self._record_usage(data, time.time() - started)
        text = data["choices"][0]["message"].get("content") or ""
        if self.strip_reasoning:
            text = strip_reasoning_text(text)
        return ChatResponse(text=text, raw=data)

    def chat_json(self, **kwargs: Any) -> Any:
        text = extract_json_text(self.chat(**kwargs).text)
        return json.loads(text)

    def _payload(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_format: dict[str, Any] | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": self.model, "messages": messages}
        if self.send_temperature:
            payload["temperature"] = temperature
        if response_format:
            payload["response_format"] = response_format
        if self.provider == "openrouter":
            payload["max_tokens"] = max_tokens
            if self.reasoning_effort not in (None, ""):
                # Reasoning text is excluded from responses so traces never reach
                # artifacts; reasoning tokens are still billed as output.
                payload["reasoning"] = {"effort": self.reasoning_effort, "exclude": True}
            if self.provider_routing:
                payload["provider"] = self.provider_routing
            if self.seed is not None:
                payload["seed"] = self.seed
            return payload
        if self.provider == "openai":
            payload["max_completion_tokens"] = max_tokens
            if self.reasoning_effort not in (None, "", "none"):
                payload["reasoning_effort"] = self.reasoning_effort
            return payload
        payload["max_tokens"] = max_tokens
        if self.reasoning_effort is not None:
            payload["reasoning_effort"] = self.reasoning_effort
        if self.include_reasoning is not None:
            payload["include_reasoning"] = self.include_reasoning
        if self.enable_thinking is not None:
            payload["chat_template_kwargs"] = {"enable_thinking": self.enable_thinking}
        return payload

    def _record_usage(self, data: dict[str, Any], latency_s: float) -> None:
        if self.provider == "vllm" and not self.ledger.path:
            return
        usage = data.get("usage") or {}
        details = usage.get("completion_tokens_details") or {}
        prompt_details = usage.get("prompt_tokens_details") or {}
        self.ledger.record(
            {
                "ts": time.time(),
                "label": self.call_label,
                "provider": self.provider,
                "model": self.model,
                "served_by": data.get("provider"),
                "served_model": data.get("model"),
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "reasoning_tokens": details.get("reasoning_tokens"),
                "cached_tokens": prompt_details.get("cached_tokens"),
                "cost_usd": usage.get("cost"),
                "latency_s": round(latency_s, 3),
            }
        )

    def _post(self, payload: dict[str, Any]) -> requests.Response:
        attempt = 0
        while True:
            try:
                resp = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                    timeout=self.timeout_sec,
                )
            except (requests.ConnectionError, requests.Timeout):
                if attempt >= self.max_retries:
                    raise
            else:
                # 404 (unknown model) and other 4xx are configuration errors: never retry.
                if self.provider in HOSTED_PROVIDERS and resp.status_code in _HOSTED_FATAL_STATUS:
                    raise FatalLLMError(
                        f"{self.provider} returned HTTP {resp.status_code} for model {self.model}: "
                        f"{resp.text[:300]}"
                    )
                if resp.status_code not in _RETRY_STATUS or attempt >= self.max_retries:
                    resp.raise_for_status()
                    return resp
            attempt += 1
            time.sleep(min(30.0, 2.0**attempt))


def served_model_ids(
    base_url: str,
    *,
    timeout_sec: int = 30,
    api_key: str | None = None,
    provider: str = "vllm",
) -> list[str]:
    """Return the model ids an OpenAI-compatible endpoint reports via ``/models``."""

    api_key = resolve_api_key(provider, api_key)
    resp = requests.get(
        f"{base_url.rstrip('/')}/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=timeout_sec,
    )
    resp.raise_for_status()
    return [str(row.get("id")) for row in resp.json().get("data", []) if row.get("id")]


def assert_model_served(
    base_url: str,
    model: str,
    *,
    timeout_sec: int = 30,
    api_key: str | None = None,
    provider: str = "vllm",
) -> list[str]:
    """Fail fast when ``model`` is not served at ``base_url``.

    vLLM answers requests for an unknown model name with HTTP 404. Without this
    preflight, a mis-routed downstream run produces empty predictions that look
    like 0.000 model accuracy.
    """

    served = served_model_ids(base_url, timeout_sec=timeout_sec, api_key=api_key, provider=provider)
    if model not in served:
        raise RuntimeError(
            f"Model {model!r} is not served at {base_url}; endpoint reports {served or 'no models'}"
        )
    return served


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


def _chat_messages(system: str, user: str, *, mode: str) -> list[dict[str, str]]:
    if mode == "separate":
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
    if mode == "merge":
        merged = f"Instruction:\n{system.strip()}\n\nRequest:\n{user.strip()}"
        return [{"role": "user", "content": merged}]
    raise ValueError("system_message_mode must be 'separate' or 'merge'")


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
