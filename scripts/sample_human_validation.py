#!/usr/bin/env python3
"""Sample benchmark items for human validation and write the labeling page data.

Writes, under --output-dir:
  items.json     page data: per-annotator queues and the fields annotators see
                 (id, graph, question, reference Cypher, first result rows,
                 schema slice). No category, tier, verdicts, or model results.
  key.jsonl      PRIVATE key: strata, inclusion weights, focus reasons, solve
                 counts, judge verdicts, shared flag, annotator assignment.
  summary.json   sample composition.
  manifest.json  inputs, seed, and checksums.

Example (v2 placeholder set):
  python scripts/sample_human_validation.py \
      --export artifacts/benchmarks/naacl_v2_heldout \
      --solve-glob 'artifacts/evaluations/naacl_v2_heldout_downstream_*/zero_shot_evaluation.jsonl' \
      --verdicts gpt6_luna=artifacts/judges/naacl_v2/rejudge_gpt6_luna.jsonl \
      --verdicts qwen35_9b=artifacts/judges/naacl_v2/rejudge_qwen35_9b.jsonl \
      --config finbench=configs/finbench_v2_glm.yaml --config snb=configs/snb_v2_glm.yaml \
      --set-id v2-placeholder --output-dir artifacts/human_validation_v3/v2_placeholder
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipecypher.config import load_config  # noqa: E402
from pipecypher.human_validation import (  # noqa: E402
    PRIVATE_NOTICE,
    assign_annotators,
    build_key,
    build_page_data,
    load_conventions,
    load_export,
    load_solve_counts,
    load_verdicts,
    sample_items,
    sample_summary,
)
from pipecypher.schema import load_schema  # noqa: E402


def _pairs(values: list[str], flag: str) -> dict[str, str]:
    pairs = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"{flag} expects NAME=PATH, got {value!r}")
        name, path = value.split("=", 1)
        pairs[name.strip()] = path.strip()
    return pairs


def _schemas(configs: dict[str, str], schema_files: dict[str, str], symmetric: dict[str, str]) -> dict:
    schemas = {}
    for graph, path in configs.items():
        cfg = load_config(path)
        if not cfg.paths.schema_path:
            raise SystemExit(f"config {path} has no paths.schema_path")
        schema = load_schema(ROOT / cfg.paths.schema_path if not Path(cfg.paths.schema_path).is_absolute() else cfg.paths.schema_path)
        extra = [rel for rel in cfg.generation.symmetric_relationships if rel not in schema.symmetric_relationships]
        schema.symmetric_relationships.extend(extra)
        schema.graph_name = graph
        schemas[graph] = schema
    for graph, path in schema_files.items():
        schema = load_schema(path)
        schema.graph_name = graph
        schemas[graph] = schema
    for graph, rels in symmetric.items():
        if graph in schemas:
            for rel in rels.split(","):
                if rel and rel not in schemas[graph].symmetric_relationships:
                    schemas[graph].symmetric_relationships.append(rel)
    return schemas


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--export", required=True, help="Benchmark export directory")
    parser.add_argument("--split", default="all", help="Which split file to sample from (default: all)")
    parser.add_argument("--n", type=int, default=200)
    parser.add_argument("--annotators", default="A,B")
    parser.add_argument("--per-annotator", type=int, default=130)
    parser.add_argument("--shared", type=int, default=60)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--hard-boost", type=float, default=2.0)
    parser.add_argument("--focus-boost", type=float, default=2.0, help="Oversampling factor for unsolved / judge-disagreement items")
    parser.add_argument("--min-per-stratum", type=int, default=1)
    parser.add_argument("--max-strata", type=int, default=None, help="Collapse focus/regular strata within a graph x category x tier cell, smallest first, until at most this many remain (use when n is below the number of strata)")
    parser.add_argument("--tier-field", default=None, help="Row field holding the difficulty tier (default: difficulty_tier, tier, difficulty)")
    parser.add_argument("--solve-glob", action="append", default=[], help="Glob of downstream evaluation JSONL files, one model per file")
    parser.add_argument("--verdicts", action="append", default=[], help="Judge verdicts as NAME=PATH (JSONL)")
    parser.add_argument("--export-judge", default=None, help="Also count the export's own gates.judge_pass as a verdict under this name (e.g. glm)")
    parser.add_argument("--config", action="append", default=[], help="graph=config.yaml (schema path and symmetric relationships)")
    parser.add_argument("--schema", action="append", default=[], help="graph=schema.json (alternative to --config)")
    parser.add_argument("--symmetric", action="append", default=[], help="graph=REL1,REL2 (adds symmetric relationship types)")
    parser.add_argument("--conventions-json", default=None, help="Convention sheet JSON; default tries pipecypher.conventions")
    parser.add_argument("--preview-rows", type=int, default=5)
    parser.add_argument("--set-id", default=None, help="Label-set id stored with every label (default: <export name>-s<seed>)")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    export = Path(args.export)
    rows = load_export(export, args.split)
    solve_paths = sorted({path for pattern in args.solve_glob for path in glob.glob(pattern)})
    solved, evaluated = load_solve_counts(solve_paths) if solve_paths else ({}, {})
    verdict_specs = _pairs(args.verdicts, "--verdicts")
    verdicts = load_verdicts(verdict_specs) if verdict_specs else {}
    if args.export_judge:
        for row in rows:
            gate = (row.get("gates") or {}).get("judge_pass")
            if gate is not None:
                verdicts.setdefault(str(row.get("id")), {})[args.export_judge] = bool(gate)
    schemas = _schemas(_pairs(args.config, "--config"), _pairs(args.schema, "--schema"), _pairs(args.symmetric, "--symmetric"))
    missing = sorted({str(row.get("graph_profile")) for row in rows} - set(schemas))
    if missing:
        print(f"warning: no schema for graph(s) {missing}; their items get no schema slice", file=sys.stderr)
    annotators = tuple(name.strip() for name in args.annotators.split(",") if name.strip())
    set_id = args.set_id or f"{export.name}-s{args.seed}"

    items = sample_items(
        rows,
        n=args.n,
        seed=args.seed,
        hard_boost=args.hard_boost,
        focus_boost=args.focus_boost,
        min_per_stratum=args.min_per_stratum,
        max_strata=args.max_strata,
        tier_field=args.tier_field,
        solved=solved,
        evaluated=evaluated,
        verdicts=verdicts,
    )
    assignment = assign_annotators(
        items, annotators=annotators, per_annotator=args.per_annotator, shared=args.shared, seed=args.seed
    )
    conventions = load_conventions(args.conventions_json)
    page = build_page_data(
        items, assignment, schemas=schemas, set_id=set_id, conventions=conventions, preview_rows=args.preview_rows
    )
    key_rows = build_key(items, assignment, set_id=set_id)
    summary = sample_summary(items, assignment, rows, tier_field=args.tier_field)
    summary.update(
        {
            "set_id": set_id,
            "solve_files": len(solve_paths),
            "items_with_solve_counts": sum(1 for item in items if item.evaluated),
            "verdict_judges": sorted(verdict_specs) + ([args.export_judge] if args.export_judge else []),
            "conventions": len(conventions),
        }
    )

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    items_path = out / "items.json"
    items_path.write_text(json.dumps(page, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    key_path = out / "key.jsonl"
    with key_path.open("w", encoding="utf-8") as handle:
        for row in key_rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "privacy": PRIVATE_NOTICE + " items.json and key.jsonl are PRIVATE/internal; publish items.json only to the private labeling page.",
        "set_id": set_id,
        "export": str(export),
        "split": args.split,
        "seed": args.seed,
        "n": args.n,
        "annotators": list(annotators),
        "per_annotator": args.per_annotator,
        "shared": args.shared,
        "hard_boost": args.hard_boost,
        "focus_boost": args.focus_boost,
        "max_strata": args.max_strata,
        "solve_files": solve_paths,
        "verdicts": verdict_specs,
        "files": {
            "items.json": _sha256(items_path),
            "key.jsonl": _sha256(key_path),
        },
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
