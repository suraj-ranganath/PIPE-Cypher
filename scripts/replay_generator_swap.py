#!/usr/bin/env python3
"""Generator swap with fixed plans (v3).

Replays identical questions, templates, and slot bindings from a v3 build with
another generator, then applies the same deterministic gates and the same judge
(panel) configuration. Only the generator differs, so judge pass-rate gaps
between generators are not confounded by question composition.

Each output row keeps the original record id fields, the replay generator, the
replayed Cypher, gate/judge outcome, and whether the replayed reference returns
the same answer as the original accepted reference (when there is one).

Example:
  python scripts/replay_generator_swap.py --config configs/finbench_v3.yaml \
      --records artifacts/runs/*naacl_v3_s1*finbench*/records.jsonl --per-category 25 \
      --generator-model qwen/qwen3.5-9b --generator-provider openrouter \
      --generator-routing '{"order":["deepinfra/bf16"],"allow_fallbacks":false}' \
      --output artifacts/naacl_v3/genswap/finbench_qwen35_9b.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipecypher.config import load_config  # noqa: E402
from pipecypher.cypher_client import Neo4jCypherClient  # noqa: E402
from pipecypher.evaluation import projected_answer_scores  # noqa: E402
from pipecypher.llm import OpenAICompatibleLLM  # noqa: E402
from pipecypher.models import TemplateCandidate  # noqa: E402
from pipecypher.pipeline import PipeCypherPipeline  # noqa: E402
from pipecypher.retrieval import ExampleStore  # noqa: E402
from pipecypher.schema import load_schema  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
from run_pipeline import build_judge  # noqa: E402


def _load(paths: list[str]) -> list[dict]:
    rows = []
    for raw in paths:
        for line in Path(raw).open(encoding="utf-8"):
            if line.strip():
                rows.append(json.loads(line))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", required=True)
    parser.add_argument("--records", nargs="+", required=True)
    parser.add_argument("--per-category", type=int, default=25)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--generator-model", required=True)
    parser.add_argument("--generator-provider", default="openrouter")
    parser.add_argument("--generator-base-url", default=None)
    parser.add_argument("--generator-routing", default="", help="OpenRouter provider routing JSON")
    parser.add_argument("--generator-reasoning-effort", default="none")
    parser.add_argument("--neo4j-uri", default=None)
    parser.add_argument("--categories", default="", help="Comma-separated categories to replay (default: all); lets one sample run as parallel shards")
    parser.add_argument("--request-seed", type=int, default=None, help="Request seed for the replay generator (OpenRouter only)")
    parser.add_argument(
        "--exclude-same-signature",
        action="store_true",
        help="Retrieval examples never share the replayed item's query signature (no sibling references in the prompt)",
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    cfg = load_config(args.config, strict=True, validate=True)
    if args.neo4j_uri:
        cfg.neo4j.uri = args.neo4j_uri
    schema = load_schema(cfg.paths.schema_path)
    client = Neo4jCypherClient(cfg.neo4j.uri, cfg.neo4j.user, cfg.neo4j.password, database=cfg.neo4j.database)
    base_urls = {"openrouter": "https://openrouter.ai/api/v1", "openai": "https://api.openai.com/v1"}
    llm = OpenAICompatibleLLM(
        args.generator_base_url or base_urls.get(args.generator_provider, cfg.models.llm_base_url),
        args.generator_model,
        timeout_sec=cfg.models.request_timeout_sec,
        reasoning_effort=args.generator_reasoning_effort,
        provider=args.generator_provider,
        send_temperature=args.generator_provider != "openai",
        provider_routing=json.loads(args.generator_routing) if args.generator_routing else None,
        call_label=f"genswap_replay:{args.generator_model}:generation",
        seed=args.request_seed,
    )
    judge = build_judge(cfg, offline=False)

    graph = cfg.generation.graph_profile
    rows = [
        r for r in _load(args.records)
        if r.get("question") and (r.get("generation_metadata") or {}).get("canonical_question")
        and r.get("graph_profile") == graph  # one config (schema, graph) per replay
    ]
    # Run records carry "accepted"; benchmark-export rows are accepted by definition.
    accepted = [r for r in rows if r.get("accepted", True)]
    examples = ExampleStore()
    for r in accepted:
        examples.add(r["question"], r["cypher"], r["category"], signature=r.get("query_signature"))
    example_pool = list(examples.examples)
    by_category: dict[str, list[dict]] = defaultdict(list)
    for r in accepted:
        by_category[r["category"]].append(r)
    rng = random.Random(args.seed)
    sample: list[dict] = []
    for category in sorted(by_category):
        pool = sorted(by_category[category], key=lambda r: str(r.get("id") or r["question"]))
        picked = rng.sample(pool, min(args.per_category, len(pool)))
        # The draw is identical for every shard and generator; --categories only filters it.
        if not args.categories or category in args.categories.split(","):
            sample.extend(picked)

    pipeline = PipeCypherPipeline(config=cfg, schema=schema, client=client, llm=llm, judge=judge, examples=examples)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for r in sample:
            meta = r.get("generation_metadata") or {}
            bindings = meta.get("bindings") or {}
            template = TemplateCandidate(
                template=r.get("template") or r["question"],
                category=r["category"],
                slots={k: "" for k in bindings},
                metadata=r.get("template_metadata") or {},
            )
            entity_hints = {slot: f"{value} | {slot}" for slot, value in bindings.items()}
            # Leave-one-out retrieval: the item's own reference is not an example. With
            # --exclude-same-signature, no example shares the item's query signature either,
            # so the prompt never shows a sibling item's reference.
            sig = r.get("query_signature")
            examples.examples = [
                e for e in example_pool
                if e["question"] != r["question"] and not (args.exclude_same_signature and sig and e.get("signature") == sig)
            ]
            cypher, _ = pipeline.generate_cypher(
                question=r["question"], category=r["category"], entity_hints=entity_hints,
                fallback_template=template, bindings=bindings,
            )
            cypher, validation, execution, judge_result, _ = pipeline._evaluate_cypher(
                question=r["question"], cypher=cypher, bound_values=list(bindings.values()),
            )
            same_answer = None
            if validation.ok and execution.success:
                original = client.run(r["cypher"], limit_rows=300)
                replay = client.run(validation.normalized_cypher, limit_rows=300)
                if original.success and replay.success:
                    f1, _ = projected_answer_scores(replay.rows, original.rows)
                    b1, _ = projected_answer_scores(original.rows, replay.rows)
                    same_answer = bool(f1.exact or b1.exact)
            handle.write(json.dumps({
                "id": r.get("id"),
                "graph_profile": r.get("graph_profile"),
                "category": r["category"],
                "question": r["question"],
                "original_cypher": r["cypher"],
                "original_generator": r.get("model"),
                "replay_generator": args.generator_model,
                "replay_cypher": validation.normalized_cypher,
                "validation_ok": validation.ok,
                "execution_success": execution.success,
                "judge_passed": judge_result.passed,
                "failure_reason": judge_result.failure_reason,
                "judge_raw": judge_result.raw,
                "same_answer_as_original": same_answer,
                "difficulty_tier": meta.get("difficulty_tier"),
                "exclude_same_signature": bool(args.exclude_same_signature),
            }, default=str) + "\n")
    print(f"replayed {len(sample)} items -> {out}")


if __name__ == "__main__":
    main()
