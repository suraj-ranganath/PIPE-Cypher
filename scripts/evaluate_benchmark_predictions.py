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
from pipecypher.evaluation import evaluate_prediction, summarize_evaluation_rows
from pipecypher.io import read_jsonl, write_jsonl
from pipecypher.schema import load_schema


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate Text2Cypher predictions for exported benchmark examples"
    )
    parser.add_argument("--benchmark", required=True, help="Benchmark JSONL or package directory")
    parser.add_argument("--split", default="all", choices=["all", "train", "dev", "test"])
    parser.add_argument("--predictions", required=True)
    parser.add_argument(
        "--config",
        action="append",
        required=True,
        help="Graph config mapping as graph_profile=config.yaml",
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary-output", default="")
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

    examples = read_jsonl(_benchmark_records_path(args.benchmark, args.split))
    predictions = read_jsonl(args.predictions)
    gold_by_id = {str(row["id"]): row for row in examples}
    graph_contexts = _open_graph_contexts(args.config)
    outputs = []

    try:
        for prediction in predictions:
            example_id = str(prediction["id"])
            if example_id not in gold_by_id:
                raise SystemExit(f"Prediction id not found in benchmark: {example_id}")
            gold = gold_by_id[example_id]
            graph = str(gold.get("graph_profile"))
            if graph not in graph_contexts:
                raise SystemExit(f"Missing --config mapping for graph_profile={graph}")
            schema, client = graph_contexts[graph]
            row = evaluate_prediction(
                question=gold["question"],
                gold_cypher=gold["cypher"],
                predicted_cypher=prediction.get("predicted_cypher", ""),
                schema=schema,
                client=client,
                include_text_metrics=not args.disable_text_metrics,
                include_optional_text_metrics=args.optional_text_metrics,
            )
            row.update(
                {
                    "id": example_id,
                    "graph_profile": graph,
                    "category": gold.get("category"),
                    "difficulty": gold.get("difficulty"),
                    "model": prediction.get("model"),
                    "predicted_cypher": prediction.get("predicted_cypher", ""),
                    "gold_cypher": gold.get("cypher", ""),
                    "prediction_error": prediction.get("error"),
                }
            )
            outputs.append(row)
    finally:
        for _, client in graph_contexts.values():
            client.close()

    write_jsonl(args.output, outputs)
    summary = summarize_evaluation_rows(outputs)
    if args.summary_output:
        out = Path(args.summary_output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    overall = summary["overall"]
    print(
        "evaluated={n} execution_accuracy={execution_accuracy:.3f} "
        "answer_f1={answer_f1:.3f} execution_success={execution_success:.3f}".format(**overall)
    )


def _open_graph_contexts(items: list[str]):
    contexts = {}
    for item in items:
        if "=" not in item:
            raise SystemExit("--config entries must use graph_profile=path")
        graph, path = item.split("=", 1)
        cfg = load_config(path)
        if not cfg.paths.schema_path:
            raise SystemExit(f"Config for {graph} must set paths.schema_path")
        schema = load_schema(cfg.paths.schema_path)
        client = Neo4jCypherClient(
            cfg.neo4j.uri,
            cfg.neo4j.user,
            cfg.neo4j.password,
            database=cfg.neo4j.database,
            timeout_sec=cfg.neo4j.query_timeout_sec,
            enforce_read_transactions=cfg.neo4j.enforce_read_transactions,
        )
        contexts[graph] = (schema, client)
    return contexts


def _benchmark_records_path(path: str, split: str) -> Path:
    candidate = Path(path)
    if candidate.is_dir():
        return candidate / f"{split}.jsonl"
    return candidate


if __name__ == "__main__":
    main()
