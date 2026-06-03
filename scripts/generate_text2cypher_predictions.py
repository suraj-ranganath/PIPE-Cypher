#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.io import append_jsonl, read_jsonl
from pipecypher.llm import OpenAICompatibleLLM
from pipecypher.schema import load_schema
from pipecypher.text2cypher import choose_few_shots, predict_text2cypher, prediction_to_dict


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
    args = parser.parse_args()

    schemas = _load_schema_map(args.schema)
    benchmark_path = _benchmark_records_path(args.benchmark, args.split)
    rows = read_jsonl(benchmark_path)
    if args.limit:
        rows = rows[: args.limit]
    few_shot_rows = read_jsonl(args.few_shot) if args.few_shot else []

    llm = OpenAICompatibleLLM(
        args.base_url,
        args.model,
        timeout_sec=args.timeout_sec,
        reasoning_effort="none",
        include_reasoning=False,
        enable_thinking=False,
        strip_reasoning=True,
        system_message_mode=args.system_message_mode,
    )

    out = Path(args.output)
    if out.exists():
        out.unlink()
    few_shot_log = Path(args.few_shot_log) if args.few_shot_log else None
    if few_shot_log:
        few_shot_log.parent.mkdir(parents=True, exist_ok=True)
        few_shot_log.write_text("", encoding="utf-8")
    for index, row in enumerate(rows, start=1):
        graph = str(row.get("graph_profile"))
        if graph not in schemas:
            raise SystemExit(f"Missing --schema mapping for graph_profile={graph}")
        few_shots = choose_few_shots(
            few_shot_rows,
            current=row,
            k=args.few_shot_k,
            mode=args.few_shot_mode,
            seed=args.few_shot_seed,
            max_question_similarity=args.few_shot_max_question_sim,
            exclude_signature_match=args.few_shot_exclude_signature_match,
        )
        prediction = predict_text2cypher(
            llm=llm,
            example=row,
            schema=schemas[graph],
            few_shot_examples=few_shots,
            schema_max_items=args.schema_max_items,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
        )
        prediction_row = prediction_to_dict(prediction)
        append_jsonl(out, prediction_row)
        if few_shot_log and prediction_row.get("few_shot_selection"):
            append_jsonl(few_shot_log, prediction_row["few_shot_selection"])
        status = "error" if prediction.error else "ok"
        print(f"{index}/{len(rows)} {row.get('id')} {graph} {status}", flush=True)

    print(f"wrote_predictions={len(rows)} output={out}")


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
