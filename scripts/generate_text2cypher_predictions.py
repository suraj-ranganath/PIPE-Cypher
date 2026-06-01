#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
    parser.add_argument("--few-shot", default="", help="Optional JSONL examples, usually train.jsonl")
    parser.add_argument("--few-shot-k", type=int, default=0)
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
    )

    out = Path(args.output)
    if out.exists():
        out.unlink()
    for index, row in enumerate(rows, start=1):
        graph = str(row.get("graph_profile"))
        if graph not in schemas:
            raise SystemExit(f"Missing --schema mapping for graph_profile={graph}")
        few_shots = choose_few_shots(few_shot_rows, current=row, k=args.few_shot_k)
        prediction = predict_text2cypher(
            llm=llm,
            example=row,
            schema=schemas[graph],
            few_shot_examples=few_shots,
            schema_max_items=args.schema_max_items,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
        )
        append_jsonl(out, prediction_to_dict(prediction))
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
