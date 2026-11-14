#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.io import append_jsonl, read_jsonl
from pipecypher.schema import load_schema
from pipecypher.text2cypher import (
    TEXT2CYPHER_SYSTEM,
    Text2CypherPrediction,
    build_text2cypher_prompt,
    choose_few_shots,
    clean_predicted_cypher,
    prediction_to_dict,
    selection_metadata,
    stable_question_id,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Text2Cypher predictions with a local Transformers model."
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
    parser.add_argument("--model", required=True)
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
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--schema-max-items", type=int, default=70)
    parser.add_argument("--device-map", default="auto")
    parser.add_argument("--load-in-8bit", action="store_true")
    parser.add_argument(
        "--prompt-mode",
        choices=["auto_chat", "merged_plain"],
        default="auto_chat",
        help="Use tokenizer chat template when available, otherwise merge instructions into plain text.",
    )
    args = parser.parse_args()

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    quantization_config = None
    if args.load_in_8bit:
        from transformers import BitsAndBytesConfig

        quantization_config = BitsAndBytesConfig(load_in_8bit=True)

    device_map: str | dict[str, int] = args.device_map
    if args.device_map == "single_cuda":
        device_map = {"": 0}

    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    if tokenizer.pad_token_id is None and tokenizer.eos_token_id is not None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        trust_remote_code=True,
        device_map=device_map,
        quantization_config=quantization_config,
        torch_dtype="auto",
    )
    model.eval()

    schemas = _load_schema_map(args.schema)
    benchmark_path = _benchmark_records_path(args.benchmark, args.split)
    rows = read_jsonl(benchmark_path)
    if args.limit:
        rows = rows[: args.limit]
    few_shot_rows = read_jsonl(args.few_shot) if args.few_shot else []

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
        prompt = build_text2cypher_prompt(
            question=str(row["question"]),
            schema=schemas[graph],
            schema_max_items=args.schema_max_items,
            few_shot_examples=few_shots,
        )
        try:
            raw_text = generate_text(
                model=model,
                tokenizer=tokenizer,
                system=TEXT2CYPHER_SYSTEM,
                user=prompt,
                prompt_mode=args.prompt_mode,
                temperature=args.temperature,
                max_new_tokens=args.max_tokens,
            )
            predicted = clean_predicted_cypher(raw_text)
            error = None
        except Exception as exc:  # pragma: no cover - live model path
            raw_text = ""
            predicted = ""
            error = str(exc)
        prediction = Text2CypherPrediction(
            id=str(row.get("id") or stable_question_id(row)),
            question=str(row["question"]),
            graph_profile=str(row.get("graph_profile", "")),
            category=str(row.get("category", "")),
            difficulty=str(row.get("difficulty", "")),
            predicted_cypher=predicted,
            raw_text=raw_text,
            model=args.model,
            gold_cypher=row.get("cypher"),
            error=error,
            few_shot_selection=selection_metadata(current=row, selected=few_shots)
            if few_shots
            else None,
        )
        prediction_row = prediction_to_dict(prediction)
        append_jsonl(out, prediction_row)
        if few_shot_log and prediction_row.get("few_shot_selection"):
            append_jsonl(few_shot_log, prediction_row["few_shot_selection"])
        status = "error" if error else "ok"
        print(f"{index}/{len(rows)} {row.get('id')} {graph} {status}", flush=True)

    print(f"wrote_predictions={len(rows)} output={out}")


def generate_text(
    *,
    model: Any,
    tokenizer: Any,
    system: str,
    user: str,
    prompt_mode: str,
    temperature: float,
    max_new_tokens: int,
) -> str:
    prompt = render_prompt(tokenizer, system=system, user=user, prompt_mode=prompt_mode)
    inputs = tokenizer(prompt, return_tensors="pt")
    device = next(model.parameters()).device
    inputs = {key: value.to(device) for key, value in inputs.items()}
    do_sample = temperature > 0
    kwargs: dict[str, Any] = {
        "max_new_tokens": max_new_tokens,
        "do_sample": do_sample,
        "pad_token_id": tokenizer.pad_token_id or tokenizer.eos_token_id,
        "eos_token_id": tokenizer.eos_token_id,
    }
    if do_sample:
        kwargs["temperature"] = temperature
    with __import__("torch").inference_mode():
        generated = model.generate(**inputs, **kwargs)
    new_tokens = generated[0, inputs["input_ids"].shape[1] :]
    return tokenizer.decode(new_tokens, skip_special_tokens=True).strip()


def render_prompt(tokenizer: Any, *, system: str, user: str, prompt_mode: str) -> str:
    if prompt_mode == "auto_chat" and getattr(tokenizer, "chat_template", None):
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        try:
            return tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )
        except Exception:
            pass
    return f"Instruction:\n{system.strip()}\n\nRequest:\n{user.strip()}\n\nCypher:"


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
