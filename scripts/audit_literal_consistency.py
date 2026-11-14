#!/usr/bin/env python3
"""Audit a benchmark export with the question<->Cypher literal-consistency gate.

Writes items.jsonl (flagged items with problems) and summary.json (counts by
problem kind, graph, category, and split). Read-only and offline: no graph or
model calls.

Example:
  python scripts/audit_literal_consistency.py --benchmark artifacts/benchmarks/naacl_v2_random \
      --split-source heldout=artifacts/benchmarks/naacl_v2_heldout \
      --ignore-limit 200 --ignore-limit 300 --output-dir artifacts/naacl_results/literal_consistency
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipecypher.literal_consistency import literal_consistency_problems  # noqa: E402


def _kind(problem: str) -> str:
    for prefix in ("question has an unfilled placeholder", "bound value", "quoted value", "Cypher literal", "LIMIT", "hop bound", "number"):
        if problem.startswith(prefix):
            return prefix
    return "other"


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
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--split-source", action="append", default=[])
    parser.add_argument("--ignore-limit", action="append", type=int, default=[])
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    benchmark = Path(args.benchmark)
    rows = [json.loads(line) for line in (benchmark / "all.jsonl").open() if line.strip()]
    splits = {"split": _split_of(benchmark)}
    for item in args.split_source:
        name, path = item.split("=", 1)
        splits[name] = _split_of(Path(path))
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    flagged = 0
    kinds: Counter[str] = Counter()
    by_graph: dict[str, Counter[str]] = defaultdict(Counter)
    by_category: dict[str, Counter[str]] = defaultdict(Counter)
    by_split: dict[str, Counter[str]] = defaultdict(Counter)
    with (out / "items.jsonl").open("w") as handle:
        for row in rows:
            problems = literal_consistency_problems(
                row.get("question", ""), row.get("cypher", ""), row.get("entity_values") or [], ignore_limits=args.ignore_limit
            )
            status = "flagged" if problems else "ok"
            by_graph[row["graph_profile"]][status] += 1
            by_category[row["category"]][status] += 1
            for name, labels in splits.items():
                by_split[f"{name}:{labels.get(row['id'])}"][status] += 1
            if problems:
                flagged += 1
                item_kinds = sorted({_kind(p) for p in problems})
                kinds.update(item_kinds)
                handle.write(json.dumps({
                    "id": row["id"], "graph_profile": row["graph_profile"], "category": row["category"],
                    **{name: labels.get(row["id"]) for name, labels in splits.items()},
                    "question": row.get("question"), "cypher": row.get("cypher"), "problems": problems, "kinds": item_kinds,
                }) + "\n")
    summary = {
        "benchmark": str(benchmark), "n": len(rows), "flagged": flagged, "flagged_share": flagged / max(1, len(rows)),
        "items_by_problem_kind": dict(kinds.most_common()),
        "by_graph": {k: dict(v) for k, v in sorted(by_graph.items())},
        "by_category": {k: dict(v) for k, v in sorted(by_category.items())},
        "by_split": {k: dict(v) for k, v in sorted(by_split.items())},
        "ignore_limits": args.ignore_limit,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in ("n", "flagged", "flagged_share", "items_by_problem_kind")}, indent=1))


if __name__ == "__main__":
    main()
