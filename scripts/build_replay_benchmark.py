#!/usr/bin/env python3
"""Build matched benchmarks from generator-swap replays (fixed plans).

Each replay row (scripts/replay_generator_swap.py) holds an export item id, the
same question, and a reference written by another generator. For every replay
file this writes a benchmark whose rows are the export rows with ``cypher`` /
``normalized_cypher`` replaced by the replayed reference, keeping only items
whose replay passed every gate and the judge panel. ``--common`` restricts all
outputs (and an ``original`` benchmark with the export's own references) to the
items every replay passed, so model scores on the outputs differ only in who
wrote the reference. Downstream predictions are re-scored against these files
with scripts/evaluate_benchmark_predictions.py; no new model calls are needed.

Example:
  python scripts/build_replay_benchmark.py --export artifacts/benchmarks/naacl_v3_full \
      --replay gpt6luna=artifacts/naacl_v3/genswap/gpt6luna_*.jsonl \
      --replay qwen9b=artifacts/naacl_v3/genswap/qwen9b_*.jsonl \
      --common --output-root artifacts/benchmarks/naacl_v3_genswap
"""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path


def _read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--export", required=True, help="Benchmark export directory (all.jsonl)")
    parser.add_argument("--replay", action="append", required=True, help="NAME=GLOB of replay JSONL files")
    parser.add_argument("--common", action="store_true", help="Keep only items every replay passed")
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()

    export = {str(r["id"]): r for r in _read(Path(args.export) / "all.jsonl")}
    replays: dict[str, dict[str, dict]] = {}
    sampled: dict[str, set[str]] = {}
    for spec in args.replay:
        name, pattern = spec.split("=", 1)
        rows = [row for path in sorted(glob.glob(pattern)) for row in _read(Path(path))]
        sampled[name] = {str(r["id"]) for r in rows}
        replays[name] = {
            str(r["id"]): r for r in rows
            if r.get("validation_ok") and r.get("execution_success") and r.get("judge_passed") and str(r["id"]) in export
        }
    keep = set.intersection(*(set(v) for v in replays.values())) if args.common else None
    root = Path(args.output_root)
    summary = {"export": args.export, "common": bool(args.common), "sets": {}}
    outputs = dict(replays)
    if args.common:
        outputs["original"] = {item_id: {"replay_cypher": export[item_id]["cypher"]} for item_id in keep}
    for name, passed in outputs.items():
        ids = sorted(keep if keep is not None else passed)
        out_dir = root / name
        out_dir.mkdir(parents=True, exist_ok=True)
        with (out_dir / "all.jsonl").open("w", encoding="utf-8") as handle:
            for item_id in ids:
                row = dict(export[item_id])
                row["cypher"] = passed[item_id]["replay_cypher"]
                row["normalized_cypher"] = passed[item_id]["replay_cypher"]
                row["reference_generator"] = name
                handle.write(json.dumps(row, default=str) + "\n")
        summary["sets"][name] = {
            "sampled": len(sampled.get(name, ids)),
            "passed": len(passed) if name != "original" else len(ids),
            "written": len(ids),
        }
    (root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
