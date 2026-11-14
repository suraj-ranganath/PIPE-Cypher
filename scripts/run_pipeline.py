#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.config import load_config
from pipecypher.cypher_client import Neo4jCypherClient, SmokeCypherClient
from pipecypher.graph_profiles import reference_schema
from pipecypher.judge import DeterministicJudge, LLMJudge
from pipecypher.llm import NullLLM, OpenAICompatibleLLM
from pipecypher.io import read_jsonl
from pipecypher.pipeline import PipeCypherPipeline, question_key
from pipecypher.retrieval import ExampleStore
from pipecypher.schema import load_schema


def main() -> None:
    parser = argparse.ArgumentParser(description="Run PIPE-Cypher generation pipeline")
    parser.add_argument("--config", required=True)
    parser.add_argument("--run-name", default="")
    parser.add_argument(
        "--random-seed",
        type=int,
        default=None,
        help="Optional deterministic seed for template reuse and other pipeline RNG choices.",
    )
    parser.add_argument("--offline-smoke", action="store_true", help="Use built-in schema, null LLM, and mock execution")
    parser.add_argument(
        "--seen-records",
        nargs="*",
        default=[],
        help="Existing run directories or records.jsonl files whose accepted questions should be rejected as duplicates.",
    )
    parser.add_argument(
        "--categories",
        default="",
        help="Comma-separated subset of the config's categories (for per-category parallel runs).",
    )
    parser.add_argument(
        "--binding-offset",
        type=int,
        default=0,
        help="Start reverse-binding rows at this offset (distinct per shard of one category).",
    )
    parser.add_argument(
        "--max-examples-per-signature",
        type=int,
        default=None,
        help="Override generation.max_examples_per_signature (per-shard quota when sharding).",
    )
    parser.add_argument(
        "--target-per-category",
        type=int,
        default=None,
        help="Override generation.target_per_category (e.g. a small pilot).",
    )
    parser.add_argument(
        "--request-seed",
        type=int,
        default=None,
        help="Override models.request_seed (sent as `seed` to hosted providers that support it).",
    )
    parser.add_argument(
        "--neo4j-uri",
        default=None,
        help="Override neo4j.uri (e.g. an SSH-tunnelled bolt port).",
    )
    args = parser.parse_args()

    cfg = load_config(args.config, strict=True, validate=True)
    if args.random_seed is not None:
        cfg.generation.random_seed = args.random_seed
    if args.request_seed is not None:
        cfg.models.request_seed = args.request_seed
    if args.neo4j_uri:
        cfg.neo4j.uri = args.neo4j_uri
    if args.categories:
        wanted = [c.strip() for c in args.categories.split(",") if c.strip()]
        unknown = sorted(set(wanted) - set(cfg.generation.categories))
        if unknown:
            raise SystemExit(f"--categories not in config: {unknown}")
        cfg.generation.categories = wanted
    if args.target_per_category is not None:
        cfg.generation.target_per_category = args.target_per_category
    if args.max_examples_per_signature is not None:
        cfg.generation.max_examples_per_signature = args.max_examples_per_signature
    run_label = args.run_name.strip().replace(" ", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = f"{timestamp}_{run_label}" if run_label else timestamp
    run_dir = Path(cfg.paths.artifact_dir) / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    if cfg.paths.schema_path:
        schema = load_schema(cfg.paths.schema_path)
    else:
        schema = reference_schema(cfg.generation.graph_profile)

    if args.offline_smoke:
        client = SmokeCypherClient()
        llm = NullLLM()
    else:
        client = Neo4jCypherClient(
            cfg.neo4j.uri,
            cfg.neo4j.user,
            cfg.neo4j.password,
            database=cfg.neo4j.database,
            timeout_sec=cfg.neo4j.query_timeout_sec,
            enforce_read_transactions=cfg.neo4j.enforce_read_transactions,
        )
        llm = OpenAICompatibleLLM(
            cfg.models.llm_base_url,
            cfg.models.generation_model,
            timeout_sec=cfg.models.request_timeout_sec,
            reasoning_effort=cfg.models.generation_reasoning_effort or cfg.models.reasoning_effort,
            include_reasoning=cfg.models.include_reasoning,
            enable_thinking=cfg.models.enable_thinking,
            strip_reasoning=cfg.models.strip_reasoning,
            provider=cfg.models.provider,
            send_temperature=cfg.models.send_temperature,
            provider_routing=cfg.models.generation_provider_routing or cfg.models.provider_routing,
            call_label=_label("generation"),
            seed=None if cfg.models.generation_provider_routing else cfg.models.request_seed,
        )

    judge = build_judge(cfg, offline=args.offline_smoke)

    examples = ExampleStore()
    if cfg.paths.seed_examples_path:
        examples = ExampleStore.from_jsonl(cfg.paths.seed_examples_path)

    pipeline = PipeCypherPipeline(
        config=cfg,
        schema=schema,
        client=client,
        llm=llm,
        judge=judge,
        examples=examples,
        seen_question_keys=load_seen_question_keys(args.seen_records),
    )
    pipeline.binding_offset_base = max(0, args.binding_offset)
    output_path = run_dir / "records.jsonl"
    result = pipeline.run(output_path)
    accepted = sum(1 for record in result.records if record.accepted)
    summary_path = run_dir / "summary.txt"
    summary_path.write_text(
        "\n".join(
            [
                f"run_id={run_id}",
                f"graph_profile={cfg.generation.graph_profile}",
                f"random_seed={cfg.generation.random_seed if cfg.generation.random_seed is not None else ''}",
                f"request_seed={cfg.models.request_seed if cfg.models.request_seed is not None else ''}",
                f"provider_routing={json.dumps(cfg.models.provider_routing, sort_keys=True)}",
                f"generation_model={cfg.models.generation_model}",
                f"judge_model={cfg.models.judge_model}",
                f"records={len(result.records)}",
                f"accepted={accepted}",
                "attempt_summary=" + json.dumps(result.attempt_summary, sort_keys=True),
                f"output={output_path}",
            ]
        ),
        encoding="utf-8",
    )
    print(f"PIPE-Cypher run complete: {accepted}/{len(result.records)} accepted")
    print(f"Records: {output_path}")
    print(f"Summary: {summary_path}")


def build_judge(cfg, *, offline: bool = False):
    """Judge used by generation runs and replays (one place, so both use the same gate).

    Online construction lives in ``pipecypher.judge.build_judge``: ``judge.mode: v2``
    with no panel reproduces the v2 ``LLMJudge``; v3 configs use the checklist
    judge and a cross-family panel.
    """

    if offline or not cfg.judge.enabled:
        return DeterministicJudge(
            min_semantic_alignment=cfg.judge.min_semantic_alignment,
            min_schema_use=cfg.judge.min_schema_use,
            max_ambiguity=cfg.judge.max_ambiguity,
        )
    from pipecypher.judge import build_judge as build_configured_judge

    return build_configured_judge(cfg, label_for=_label)


def _label(role: str) -> str:
    prefix = os.environ.get("PIPE_CYPHER_CALL_LABEL", "").strip()
    return f"{prefix}:{role}" if prefix else role


def load_seen_question_keys(paths: list[str]) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for raw_path in paths:
        records_path = _records_path(raw_path)
        if not records_path.exists():
            raise SystemExit(f"seen records file not found: {records_path}")
        for record in read_jsonl(records_path):
            if record.get("accepted") and record.get("category") and record.get("question"):
                keys.add(question_key(str(record["category"]), str(record["question"])))
    return keys


def _records_path(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_dir():
        return candidate / "records.jsonl"
    return candidate


if __name__ == "__main__":
    main()
