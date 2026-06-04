#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.random_seed is not None:
        cfg.generation.random_seed = args.random_seed
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
            reasoning_effort=cfg.models.reasoning_effort,
            include_reasoning=cfg.models.include_reasoning,
            enable_thinking=cfg.models.enable_thinking,
            strip_reasoning=cfg.models.strip_reasoning,
        )

    fallback_judge = DeterministicJudge(
        min_semantic_alignment=cfg.judge.min_semantic_alignment,
        min_schema_use=cfg.judge.min_schema_use,
        max_ambiguity=cfg.judge.max_ambiguity,
    )
    if args.offline_smoke or not cfg.judge.enabled:
        judge = fallback_judge
    else:
        judge_llm = OpenAICompatibleLLM(
            cfg.models.llm_base_url,
            cfg.models.judge_model,
            timeout_sec=cfg.models.request_timeout_sec,
            reasoning_effort=cfg.models.reasoning_effort,
            include_reasoning=cfg.models.include_reasoning,
            enable_thinking=cfg.models.enable_thinking,
            strip_reasoning=cfg.models.strip_reasoning,
        )
        judge = LLMJudge(judge_llm, fallback_judge)

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
