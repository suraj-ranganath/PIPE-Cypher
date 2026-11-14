#!/usr/bin/env python3
"""Audit benchmark references for ties at the ORDER BY ... LIMIT boundary.

Writes one JSON line per item (id, graph, category, split, status, detail) and a
summary with counts by status, graph, category, and split. Read-only: every
query runs through the read-only client after a single LIMIT-literal rewrite.

Example:
  python scripts/audit_limit_ties.py --benchmark artifacts/benchmarks/naacl_v2_random \
      --config finbench=configs/finbench_full.yaml --config snb=configs/snb_full.yaml \
      --output-dir artifacts/naacl_results/limit_ties
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipecypher.config import load_config  # noqa: E402
from pipecypher.cypher_client import Neo4jCypherClient  # noqa: E402
from pipecypher.limit_ties import check_limit_tie  # noqa: E402


def _clients(items: list[str]) -> dict[str, Neo4jCypherClient]:
    clients = {}
    for item in items:
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


def _split_of(benchmark: Path) -> dict[str, str]:
    split = {}
    for name in ("train", "dev", "test"):
        path = benchmark / f"{name}.jsonl"
        if path.exists():
            for line in path.open():
                if line.strip():
                    split[json.loads(line)["id"]] = name
    return split


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--benchmark", required=True, help="Benchmark export directory (reads all.jsonl)")
    parser.add_argument("--split-source", action="append", default=[], help="Extra export dirs whose split labels to record, as NAME=DIR")
    parser.add_argument("--config", action="append", required=True, help="graph_profile=config.yaml")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    benchmark = Path(args.benchmark)
    rows = [json.loads(line) for line in (benchmark / "all.jsonl").open() if line.strip()]
    clients = _clients(args.config)
    split_sources = {"split": _split_of(benchmark)}
    for item in args.split_source:
        name, path = item.split("=", 1)
        split_sources[name] = _split_of(Path(path))

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    by_status: Counter[str] = Counter()
    by_graph: dict[str, Counter[str]] = defaultdict(Counter)
    by_category: dict[str, Counter[str]] = defaultdict(Counter)
    by_split: dict[str, Counter[str]] = defaultdict(Counter)
    with (out_dir / "items.jsonl").open("w") as handle:
        for row in rows:
            graph = row["graph_profile"]
            if graph not in clients:
                raise SystemExit(f"Missing --config for graph_profile={graph}")
            client = clients[graph]
            result = check_limit_tie(row["cypher"], lambda q: client.run(q, limit_rows=None))
            record = {
                "id": row["id"],
                "graph_profile": graph,
                "category": row["category"],
                "difficulty": row.get("difficulty"),
                **{name: labels.get(row["id"]) for name, labels in split_sources.items()},
                **result.to_dict(),
            }
            handle.write(json.dumps(record) + "\n")
            by_status[result.status] += 1
            by_graph[graph][result.status] += 1
            by_category[row["category"]][result.status] += 1
            for name, labels in split_sources.items():
                by_split[f"{name}:{labels.get(row['id'])}"][result.status] += 1

    summary = {
        "benchmark": str(benchmark),
        "n": len(rows),
        "by_status": dict(by_status),
        "by_graph": {k: dict(v) for k, v in sorted(by_graph.items())},
        "by_category": {k: dict(v) for k, v in sorted(by_category.items())},
        "by_split": {k: dict(v) for k, v in sorted(by_split.items())},
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary["by_status"]))
    if by_status.get("error"):
        print(f"warning: {by_status['error']} items failed to execute", file=sys.stderr)


if __name__ == "__main__":
    main()
