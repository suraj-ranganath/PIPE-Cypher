#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.llm import OpenAICompatibleLLM


def main() -> None:
    parser = argparse.ArgumentParser(description="Check an OpenAI-compatible local LLM endpoint")
    parser.add_argument("--base-url", default="http://localhost:8000/v1")
    parser.add_argument("--model", default="Qwen/Qwen3.5-9B")
    parser.add_argument("--timeout-sec", type=int, default=60)
    parser.add_argument("--max-tokens", type=int, default=32)
    parser.add_argument(
        "--system-message-mode",
        choices=["separate", "merge"],
        default="separate",
        help="Use 'merge' for chat templates that reject the system role.",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    models_resp = requests.get(f"{base_url}/models", timeout=args.timeout_sec)
    models_resp.raise_for_status()
    models_payload = models_resp.json()

    llm = OpenAICompatibleLLM(
        base_url,
        args.model,
        timeout_sec=args.timeout_sec,
        reasoning_effort="none",
        include_reasoning=False,
        enable_thinking=False,
        strip_reasoning=True,
        system_message_mode=args.system_message_mode,
    )
    chat = llm.chat(
        system="You are a terse API. Return only the requested answer.",
        user="Return the word ok only.",
        temperature=0,
        max_tokens=args.max_tokens,
    )
    content = chat.text.strip()
    result = {
        "base_url": base_url,
        "model": args.model,
        "models": [row.get("id") for row in models_payload.get("data", [])],
        "chat_text": content,
        "ok": content == "ok",
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
