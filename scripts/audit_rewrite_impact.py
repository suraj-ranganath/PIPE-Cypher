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
from pipecypher.paper_tables import render_rewrite_audit_table
from pipecypher.rewrite_audit import (
    classify_rewrite,
    compare_execution_results,
    load_records,
    record_normalized_cypher,
    summarize_execution_comparisons,
    summarize_rewrite_audit,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit Cypher normalization and optional original-vs-normalized execution impact."
    )
    parser.add_argument("--records", nargs="+", required=True)
    parser.add_argument(
        "--config-by-graph",
        action="append",
        default=[],
        metavar="GRAPH=CONFIG",
        help="Optional live graph config for semantic re-execution, e.g. finbench=configs/finbench_full.yaml.",
    )
    parser.add_argument("--max-executions", type=int, default=0)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-tex", default="")
    args = parser.parse_args()

    records = load_records(args.records)
    summary = summarize_rewrite_audit(records)
    comparisons = _execute_changed_records(records, args.config_by_graph, args.max_executions)
    summary["execution_comparison"] = summarize_execution_comparisons(comparisons)
    summary["execution_comparisons_sample"] = comparisons[:10]

    out = Path(args.output_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out}")

    if args.output_tex:
        tex = Path(args.output_tex)
        tex.parent.mkdir(parents=True, exist_ok=True)
        tex.write_text(render_rewrite_audit_table(summary), encoding="utf-8")
        print(f"wrote {tex}")


def _execute_changed_records(
    records: list[dict],
    config_by_graph_args: list[str],
    max_executions: int,
) -> list[dict]:
    if max_executions <= 0 or not config_by_graph_args:
        return []
    clients = _clients_by_graph(config_by_graph_args)
    comparisons: list[dict] = []
    try:
        for record in records:
            if len(comparisons) >= max_executions:
                break
            original = str(record.get("cypher") or "")
            normalized = record_normalized_cypher(record)
            if classify_rewrite(original, normalized) == ["unchanged"]:
                continue
            graph = str(record.get("graph_profile") or "unknown")
            client = clients.get(graph)
            if client is None:
                continue
            original_result = client.run(original, limit_rows=500)
            normalized_result = client.run(normalized, limit_rows=500)
            row = compare_execution_results(original_result, normalized_result)
            row.update(
                {
                    "id": record.get("id", ""),
                    "graph_profile": graph,
                    "category": record.get("category", ""),
                    "rewrite_classes": classify_rewrite(original, normalized),
                }
            )
            comparisons.append(row)
    finally:
        for client in clients.values():
            client.close()
    return comparisons


def _clients_by_graph(items: list[str]) -> dict[str, Neo4jCypherClient]:
    clients: dict[str, Neo4jCypherClient] = {}
    for item in items:
        if "=" not in item:
            raise SystemExit(f"--config-by-graph must be GRAPH=CONFIG, got {item!r}")
        graph, path = item.split("=", 1)
        cfg = load_config(path)
        clients[graph] = Neo4jCypherClient(
            cfg.neo4j.uri,
            cfg.neo4j.user,
            cfg.neo4j.password,
            database=cfg.neo4j.database,
            timeout_sec=cfg.neo4j.query_timeout_sec,
            enforce_read_transactions=cfg.neo4j.enforce_read_transactions,
        )
    return clients


if __name__ == "__main__":
    main()
