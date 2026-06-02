#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.config import load_config
from pipecypher.cypher_client import Neo4jCypherClient
from pipecypher.evaluation import evaluate_prediction
from pipecypher.schema import load_schema


def load_jsonl(path: str) -> list[dict]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate predicted Cypher against PIPE-Cypher records"
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--gold", required=True, help="PIPE-Cypher records JSONL")
    parser.add_argument(
        "--predictions",
        required=True,
        help="JSONL with question and predicted_cypher",
    )
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--disable-text-metrics",
        action="store_true",
        help="Skip supplementary ROUGE/BLEU/METEOR/cosine/Jaro-Winkler/exact-match metrics",
    )
    parser.add_argument(
        "--optional-text-metrics",
        action="store_true",
        help="Also attempt optional BERTScore and FrugalScore integrations when installed",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    if not cfg.paths.schema_path:
        raise SystemExit("Config must set paths.schema_path for live evaluation")
    schema = load_schema(cfg.paths.schema_path)
    client = Neo4jCypherClient(
        cfg.neo4j.uri,
        cfg.neo4j.user,
        cfg.neo4j.password,
        database=cfg.neo4j.database,
        timeout_sec=cfg.neo4j.query_timeout_sec,
    )
    gold_by_question = {row["question"]: row for row in load_jsonl(args.gold)}
    outputs = []
    for pred in load_jsonl(args.predictions):
        question = pred["question"]
        gold = gold_by_question[question]
        outputs.append(
            evaluate_prediction(
                question=question,
                gold_cypher=gold["cypher"],
                predicted_cypher=pred["predicted_cypher"],
                schema=schema,
                client=client,
                include_text_metrics=not args.disable_text_metrics,
                include_optional_text_metrics=args.optional_text_metrics,
            )
        )
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for row in outputs:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    exact = sum(1 for row in outputs if row["execution_accuracy"])
    print(f"evaluated={len(outputs)} execution_accuracy={exact / max(1, len(outputs)):.3f}")
    client.close()


if __name__ == "__main__":
    main()
