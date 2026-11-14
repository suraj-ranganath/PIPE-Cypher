#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.io import append_jsonl, read_jsonl
from pipecypher.llm import PROVIDERS, OpenAICompatibleLLM, assert_model_served
from pipecypher.prompt_formats import (
    COMPLETION,
    DEFAULT_PROMPT_FORMAT,
    allowed_prompt_formats,
    get_prompt_format,
)
from pipecypher.schema import load_schema
from pipecypher.text2cypher import choose_few_shots, predict_text2cypher, prediction_to_dict

# Hosted (non-local) providers may only see public graphs (AGENTS.md owner
# decision 2026-11-11): LDBC FinBench/SNB, ICIJ Offshore Leaks, and the public
# Neo4j example graphs used by Text2Cypher-2024. Private tenant graphs never
# leave local weights.
HOSTED_ALLOWED_GRAPH_PROFILES = frozenset(
    {
        "finbench",
        "snb",
        "icij_offshoreleaks",
        "t2c_fincen",
        "t2c_northwind",
        "t2c_recommendations",
    }
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate local-model Text2Cypher predictions for an exported benchmark"
    )
    parser.add_argument("--benchmark", required=True, help="Benchmark JSONL or package directory")
    parser.add_argument("--split", default="all", choices=["all", "train", "dev", "test"])
    parser.add_argument(
        "--schema",
        action="append",
        required=True,
        help="Graph schema mapping as graph_profile=path, e.g. finbench=configs/schema_finbench.json",
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--base-url", default="http://localhost:8000/v1")
    parser.add_argument("--model", default="Qwen/Qwen3.5-9B")
    parser.add_argument("--timeout-sec", type=int, default=180)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--schema-max-items", type=int, default=70)
    parser.add_argument(
        "--system-message-mode",
        choices=["separate", "merge"],
        default=os.getenv("PIPE_CYPHER_SYSTEM_MESSAGE_MODE", "separate"),
        help="Use 'merge' for chat templates that reject the system role.",
    )
    parser.add_argument("--few-shot", default="", help="Optional JSONL examples, usually train.jsonl")
    parser.add_argument("--few-shot-k", type=int, default=0)
    parser.add_argument(
        "--few-shot-mode",
        choices=["ordered_same_category", "random_same_category", "scored_no_signature"],
        default="ordered_same_category",
    )
    parser.add_argument("--few-shot-seed", type=int, default=13)
    parser.add_argument("--few-shot-max-question-sim", type=float, default=0.90)
    parser.add_argument("--few-shot-exclude-signature-match", action="store_true")
    parser.add_argument(
        "--few-shot-log",
        default="",
        help="Optional JSONL file recording selected few-shot example IDs and overlap diagnostics.",
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--skip-model-preflight",
        action="store_true",
        help="Do not check that --model is listed by the endpoint's /models route.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=int(os.getenv("PIPE_CYPHER_PRED_CONCURRENCY", "1")),
        help="Parallel requests (default from PIPE_CYPHER_PRED_CONCURRENCY, else 1). Output order is preserved.",
    )
    parser.add_argument(
        "--max-consecutive-errors",
        type=int,
        default=5,
        help="Abort (exit 3) after this many consecutive request failures.",
    )
    parser.add_argument(
        "--prompt-format",
        choices=allowed_prompt_formats(),
        default=DEFAULT_PROMPT_FORMAT,
        help=(
            "Prompt format from pipecypher.prompt_formats. pipe_standard reproduces the "
            "historical prompt; native_* formats reproduce a checkpoint's documented template "
            "(zero-shot only)."
        ),
    )
    parser.add_argument(
        "--provider",
        choices=list(PROVIDERS),
        default="vllm",
        help=(
            "vllm: local weights on a vLLM/OpenAI-compatible endpoint (default). openai: hosted "
            "reference model, public graphs only; the key is read from OPENAI_API_KEY or "
            "PIPE_CYPHER_LLM_API_KEY and is never accepted on the command line."
        ),
    )
    parser.add_argument(
        "--no-temperature",
        action="store_true",
        help="Omit the temperature field (hosted models that only accept their default).",
    )
    parser.add_argument(
        "--reasoning-effort",
        default=None,
        help=(
            "Reasoning effort to request. Defaults to 'none' for vllm (Qwen thinking off); "
            "omitted for openai unless set."
        ),
    )
    args = parser.parse_args()

    prompt_format = get_prompt_format(args.prompt_format)
    if args.few_shot_k > 0 and not prompt_format.supports_few_shot:
        raise SystemExit(
            f"--prompt-format {args.prompt_format} is a documented zero-shot template; "
            "run few-shot conditions with pipe_standard."
        )
    if args.provider != "vllm" and prompt_format.transport == COMPLETION:
        raise SystemExit(
            f"--prompt-format {args.prompt_format} needs a local /completions route; "
            f"provider {args.provider} is not supported."
        )

    schemas = _load_schema_map(args.schema)
    benchmark_path = _benchmark_records_path(args.benchmark, args.split)
    rows = read_jsonl(benchmark_path)
    if args.limit:
        rows = rows[: args.limit]
    few_shot_rows = read_jsonl(args.few_shot) if args.few_shot else []
    if args.provider != "vllm":
        graphs = {str(row.get("graph_profile")) for row in [*rows, *few_shot_rows]}
        private = sorted(graphs - HOSTED_ALLOWED_GRAPH_PROFILES)
        if private:
            raise SystemExit(
                f"provider {args.provider} is a hosted model and may only see public graphs "
                f"({', '.join(sorted(HOSTED_ALLOWED_GRAPH_PROFILES))}); refusing graph_profile(s): "
                + ", ".join(private)
            )

    if not args.skip_model_preflight:
        try:
            served = assert_model_served(args.base_url, args.model, provider=args.provider)
        except Exception as exc:
            raise SystemExit(f"Model preflight failed: {exc}") from exc
        print(f"preflight_ok model={args.model} served={served}", flush=True)
    print(
        f"prompt_format={args.prompt_format} provider={args.provider} "
        f"system_message_mode={args.system_message_mode}",
        flush=True,
    )

    if args.provider == "vllm":
        llm = OpenAICompatibleLLM(
            args.base_url,
            args.model,
            timeout_sec=args.timeout_sec,
            reasoning_effort=args.reasoning_effort if args.reasoning_effort is not None else "none",
            include_reasoning=False,
            enable_thinking=False,
            strip_reasoning=True,
            system_message_mode=args.system_message_mode,
            send_temperature=not args.no_temperature,
        )
    else:
        llm = OpenAICompatibleLLM(
            args.base_url,
            args.model,
            timeout_sec=args.timeout_sec,
            reasoning_effort=args.reasoning_effort,
            include_reasoning=None,
            enable_thinking=None,
            strip_reasoning=True,
            system_message_mode=args.system_message_mode,
            provider=args.provider,
            send_temperature=not args.no_temperature,
        )

    out = Path(args.output)
    # Opt-in reuse of an interrupted zero-shot run (PIPE_CYPHER_REUSE_PREDICTIONS=1): a stored
    # row is reused only if its id, question text, model, and prompt format equal the current
    # ones and it has no error, so the prompt it answered is the prompt this run would send.
    reuse: dict[str, dict] = {}
    if out.exists() and os.environ.get("PIPE_CYPHER_REUSE_PREDICTIONS") == "1" and args.few_shot_k == 0:
        current = {str(row.get("id")): row for row in rows}
        for line in out.read_text(encoding="utf-8").splitlines():
            try:
                old_row = json.loads(line)
            except json.JSONDecodeError:
                continue
            item = current.get(str(old_row.get("id")))
            if (
                item is not None
                and old_row.get("question") == item.get("question")
                and old_row.get("model") == args.model
                and old_row.get("prompt_format") == args.prompt_format
                and not old_row.get("error")
            ):
                reuse[str(old_row["id"])] = old_row
        print(f"reusing {len(reuse)} stored predictions from an interrupted run", flush=True)
    if out.exists():
        out.unlink()
    few_shot_log = Path(args.few_shot_log) if args.few_shot_log else None
    if few_shot_log:
        few_shot_log.parent.mkdir(parents=True, exist_ok=True)
        few_shot_log.write_text("", encoding="utf-8")
    for row in rows:
        if str(row.get("graph_profile")) not in schemas:
            raise SystemExit(f"Missing --schema mapping for graph_profile={row.get('graph_profile')}")

    def _predict(row):
        graph = str(row.get("graph_profile"))
        few_shots = choose_few_shots(
            few_shot_rows,
            current=row,
            k=args.few_shot_k,
            mode=args.few_shot_mode,
            seed=args.few_shot_seed,
            max_question_similarity=args.few_shot_max_question_sim,
            exclude_signature_match=args.few_shot_exclude_signature_match,
        )
        return predict_text2cypher(
            llm=llm,
            example=row,
            schema=schemas[graph],
            few_shot_examples=few_shots,
            schema_max_items=args.schema_max_items,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            prompt_format=args.prompt_format,
        )

    # Requests may run concurrently, but results are consumed and written in
    # benchmark order, so outputs and the consecutive-failure abort are the
    # same as a sequential run.
    concurrency = max(1, args.concurrency)
    executor = ThreadPoolExecutor(max_workers=concurrency) if concurrency > 1 else None
    todo = [row for row in rows if str(row.get("id")) not in reuse]
    fresh = iter(executor.map(_predict, todo) if executor else map(_predict, todo))
    consecutive_errors = 0
    total_errors = 0
    try:
        for index, row in enumerate(rows, start=1):
            graph = str(row.get("graph_profile"))
            stored = reuse.get(str(row.get("id")))
            if stored is not None:
                append_jsonl(out, stored)
                print(f"{index}/{len(rows)} {row.get('id')} {graph} reused", flush=True)
                continue
            prediction = next(fresh)
            prediction_row = prediction_to_dict(prediction)
            append_jsonl(out, prediction_row)
            if few_shot_log and prediction_row.get("few_shot_selection"):
                append_jsonl(few_shot_log, prediction_row["few_shot_selection"])
            status = "error" if prediction.error else "ok"
            print(f"{index}/{len(rows)} {row.get('id')} {graph} {status}", flush=True)
            if prediction.error:
                consecutive_errors += 1
                total_errors += 1
                if consecutive_errors >= args.max_consecutive_errors:
                    print(
                        f"Aborting after {consecutive_errors} consecutive request failures "
                        f"(last error: {prediction.error}). Partial output at {out} is not a "
                        "model result.",
                        file=sys.stderr,
                        flush=True,
                    )
                    raise SystemExit(3)
            else:
                consecutive_errors = 0
    finally:
        if executor:
            executor.shutdown(wait=False, cancel_futures=True)

    print(f"wrote_predictions={len(rows)} request_errors={total_errors} output={out}")


def _load_schema_map(items: list[str]):
    schemas = {}
    for item in items:
        if "=" not in item:
            raise SystemExit("--schema entries must use graph_profile=path")
        graph, path = item.split("=", 1)
        schemas[graph] = load_schema(path)
    return schemas


def _benchmark_records_path(path: str, split: str) -> Path:
    candidate = Path(path)
    if candidate.is_dir():
        return candidate / f"{split}.jsonl"
    return candidate


if __name__ == "__main__":
    main()
