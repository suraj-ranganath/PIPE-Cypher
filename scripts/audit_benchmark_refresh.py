#!/usr/bin/env python3
"""Benchmark-refresh audit CLI (read-only on every graph).

Subcommands:

``diff``         Diff two introspected schema JSONs, check them against a
                 migration's ``expected_schema_diff``, and optionally compute the
                 static (no-execution) impact plan for a benchmark.
``audit``        Re-execute every reference Cypher of one graph profile on the
                 original graph and on the migrated copy, classify each item,
                 write the incremental-refresh plan, the carried-forward export,
                 and (optionally) per-category regeneration configs. With
                 ``--predictions`` it also computes the accuracy misestimate.
``misestimate``  Score downstream predictions on the migrated graph against stale
                 vs refreshed references.
``assemble``     Build the refreshed package: carried-forward rows keep their split,
                 regenerated rows fill the per-split deficits, other graphs pass through.
``table``        Render the compact paper table from complete audit summaries.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import yaml

from pipecypher.config import collect_unknown_config_keys, load_config
from pipecypher.io import read_jsonl, write_jsonl
from pipecypher.refresh_audit import (
    RefreshAuditOptions,
    accuracy_misestimate,
    assemble_refreshed_rows,
    audit_benchmark_refresh,
    endpoints_match,
    extract_schema_atoms,
    load_benchmark_rows,
    normalize_bolt_endpoint,
    reference_cypher,
    refresh_table_rows,
    render_refresh_table_markdown,
    reusable_seen_records,
    static_action_for,
    summarize_refresh_audit,
)
from pipecypher.schema import load_schema
from pipecypher.schema_diff import check_expected_diff, diff_schemas

DEFAULT_MIGRATIONS_DIR = PROJECT_ROOT / "configs" / "migrations" / "finbench"


def _sha256(path: str | Path) -> str | None:
    p = Path(path)
    if not p.exists() or not p.is_file():
        return None
    digest = hashlib.sha256()
    with p.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_revision() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except Exception:
        return None


def _load_migration_meta(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    path = Path(value)
    if not path.exists():
        for name in (f"{value}.meta.yaml", f"{value}.yaml"):
            candidate = DEFAULT_MIGRATIONS_DIR / name
            if candidate.exists():
                path = candidate
                break
    if not path.exists():
        raise SystemExit(f"migration metadata not found: {value}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data["_path"] = str(path)
    return data


def _benchmark_file(path: str | Path) -> Path:
    p = Path(path)
    return p / "all.jsonl" if p.is_dir() else p


def _client_for(config_path: str) -> Any:
    from pipecypher.cypher_client import Neo4jCypherClient

    overrides = [name for name in ("PIPE_CYPHER_NEO4J_URI", "PIPE_CYPHER_NEO4J_DATABASE") if os.environ.get(name)]
    if overrides:
        # Env overrides would silently point BOTH the original and migrated configs at one graph.
        raise SystemExit("unset " + ", ".join(overrides) + " before running the refresh audit")
    cfg = load_config(config_path, strict=True, validate=True)
    return cfg, Neo4jCypherClient(
        cfg.neo4j.uri,
        cfg.neo4j.user,
        cfg.neo4j.password,
        database=cfg.neo4j.database,
        timeout_sec=cfg.neo4j.query_timeout_sec,
        enforce_read_transactions=True,
    )


# ---------------------------------------------------------------------------
# diff


def cmd_diff(args: argparse.Namespace) -> int:
    before = load_schema(args.before_schema)
    after = load_schema(args.after_schema)
    diff = diff_schemas(
        before,
        after,
        count_change_threshold=args.count_change_threshold,
        rename_min_confidence=args.rename_detect_confidence,
    )
    meta = _load_migration_meta(args.migration)
    problems = check_expected_diff(diff, meta.get("expected_schema_diff"))
    report: dict[str, Any] = {
        "migration_id": meta.get("id"),
        "before_schema": {"path": args.before_schema, "sha256": _sha256(args.before_schema)},
        "after_schema": {"path": args.after_schema, "sha256": _sha256(args.after_schema)},
        "schema_diff": diff.to_dict(),
        "expected_diff_problems": problems,
    }
    if args.benchmark:
        rows, _ = load_benchmark_rows(args.benchmark)
        graph = args.graph_profile or meta.get("graph_profile") or "finbench"
        counts: dict[str, int] = {}
        by_category: dict[str, dict[str, int]] = {}
        for row in rows:
            if str(row.get("graph_profile")) != graph:
                continue
            action, _, _ = static_action_for(
                extract_schema_atoms(reference_cypher(row)),
                diff,
                min_confidence=args.rename_min_confidence,
            )
            counts[action] = counts.get(action, 0) + 1
            cat = by_category.setdefault(str(row.get("category")), {})
            cat[action] = cat.get(action, 0) + 1
        report["static_plan"] = {"graph_profile": graph, "actions": counts, "by_category": by_category}
    text = json.dumps(report, indent=2, sort_keys=True, default=str)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    if problems:
        print("expected_schema_diff mismatches:\n  - " + "\n  - ".join(problems), file=sys.stderr)
        return 0 if args.allow_mismatch else 1
    return 0


# ---------------------------------------------------------------------------
# audit


_SCRIPT_GUARDS = [
    '[[ -f scripts/run_pipeline.py ]] || { echo "run from the PIPE-Cypher repo root" >&2; exit 1; }',
    'if [[ -n "${PIPE_CYPHER_NEO4J_URI:-}${PIPE_CYPHER_NEO4J_DATABASE:-}" ]]; then',
    '  echo "unset PIPE_CYPHER_NEO4J_URI/DATABASE: the generated configs already target the migrated copy" >&2',
    "  exit 1",
    "fi",
]


def emit_regeneration_configs(
    *,
    base_config: str,
    migrated_schema: str,
    targets: dict[str, int],
    out_dir: Path,
    migration_id: str,
    seen_records: Path,
    random_seed: int,
) -> list[dict[str, Any]]:
    """Write one strict-valid run config per category that needs regeneration."""

    raw = yaml.safe_load(Path(base_config).read_text(encoding="utf-8")) or {}
    unknown = collect_unknown_config_keys(raw)
    if unknown:
        raise SystemExit("regeneration base config has unknown keys: " + ", ".join(unknown))
    out_dir.mkdir(parents=True, exist_ok=True)
    emitted: list[dict[str, Any]] = []
    for category, target in sorted(targets.items()):
        data = copy.deepcopy(raw)
        data.setdefault("generation", {})
        data["generation"]["categories"] = [category]
        data["generation"]["target_per_category"] = int(target)
        data.setdefault("paths", {})
        data["paths"]["schema_path"] = migrated_schema
        path = out_dir / f"regen_{migration_id}_{category}.yaml"
        path.write_text(
            f"# Generated by scripts/audit_benchmark_refresh.py for {migration_id}/{category}.\n"
            + yaml.safe_dump(data, sort_keys=False),
            encoding="utf-8",
        )
        load_config(path, strict=True, validate=True)
        emitted.append({"category": category, "target": int(target), "config": str(path)})
    script = out_dir / "regenerate.sh"
    lines = [
        "#!/usr/bin/env bash",
        "# Incremental refresh: regenerate only the categories the audit marked stale.",
        f"# Migration: {migration_id}. Timing rows go to regeneration_timing.tsv.",
        "set -euo pipefail",
        *_SCRIPT_GUARDS,
        'PY="${PY:-python}"',
        f'TIMING="{out_dir / "regeneration_timing.tsv"}"',
        'printf "category\\tstart_epoch\\tend_epoch\\n" > "${TIMING}"',
    ]
    for entry in emitted:
        lines += [
            "start=$(date +%s)",
            f'"${{PY}}" scripts/run_pipeline.py --config {entry["config"]} '
            f"--run-name refresh_{migration_id}_{entry['category']} "
            f"--random-seed {random_seed} --seen-records {seen_records}",
            "end=$(date +%s)",
            f'printf "{entry["category"]}\\t%s\\t%s\\n" "${{start}}" "${{end}}" >> "${{TIMING}}"',
        ]
    script.write_text("\n".join(lines) + "\n", encoding="utf-8")
    script.chmod(0o755)
    return emitted


def emit_full_refresh_config(
    *,
    base_config: str,
    migrated_schema: str,
    categories: list[str],
    target_per_category: int,
    out_dir: Path,
    migration_id: str,
    random_seed: int,
) -> dict[str, Any]:
    """Write the full-regeneration baseline config (every category, original totals)."""

    raw = yaml.safe_load(Path(base_config).read_text(encoding="utf-8")) or {}
    data = copy.deepcopy(raw)
    data.setdefault("generation", {})
    data["generation"]["categories"] = list(categories)
    data["generation"]["target_per_category"] = int(target_per_category)
    data.setdefault("paths", {})
    data["paths"]["schema_path"] = migrated_schema
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"full_refresh_{migration_id}.yaml"
    path.write_text(
        f"# Generated by scripts/audit_benchmark_refresh.py: full-refresh baseline for {migration_id}.\n"
        + yaml.safe_dump(data, sort_keys=False),
        encoding="utf-8",
    )
    load_config(path, strict=True, validate=True)
    script = out_dir / "full_refresh.sh"
    script.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "# Full-refresh baseline: regenerate the whole graph slice on the migrated copy.",
                "set -euo pipefail",
                *_SCRIPT_GUARDS,
                'PY="${PY:-python}"',
                f'TIMING="{out_dir / "full_refresh_timing.tsv"}"',
                'printf "scope\\tstart_epoch\\tend_epoch\\n" > "${TIMING}"',
                "start=$(date +%s)",
                f'"${{PY}}" scripts/run_pipeline.py --config {path} '
                f"--run-name refresh_full_{migration_id} --random-seed {random_seed}",
                "end=$(date +%s)",
                'printf "full\\t%s\\t%s\\n" "${start}" "${end}" >> "${TIMING}"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return {"config": str(path), "categories": list(categories), "target_per_category": int(target_per_category)}


def cmd_assemble(args: argparse.Namespace) -> int:
    audit_dir = Path(args.audit_dir)
    summary = json.loads((audit_dir / "refresh_audit_summary.json").read_text(encoding="utf-8"))
    if summary.get("partial") and not args.allow_incomplete:
        print("error: refusing to assemble from a partial audit", file=sys.stderr)
        return 1
    graph = str(summary["graph_profile"])
    migration_id = str(summary["migration_id"])
    targets = summary["incremental_plan"]["regeneration_targets_by_split"]
    carried = read_jsonl(audit_dir / "carried_forward_export.jsonl")
    regenerated: list[dict[str, Any]] = []
    for source in args.regenerated_export or []:
        rows, _ = load_benchmark_rows(source)
        regenerated.extend(row for row in rows if str(row.get("graph_profile")) == graph)
    splits, report = assemble_refreshed_rows(carried, regenerated, targets)
    for split, rows in splits.items():
        for row in rows:
            if "refresh" not in row:
                row["refresh"] = {"migration_id": migration_id, "action": "regenerated", "split": split}
    original_rows, split_by_id = load_benchmark_rows(args.original_benchmark)
    passthrough = 0
    for row in original_rows:
        if str(row.get("graph_profile")) == graph:
            continue
        splits.setdefault(split_by_id.get(str(row.get("id")), "unknown"), []).append(row)
        passthrough += 1
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    all_rows = sorted((row for rows in splits.values() for row in rows), key=lambda r: str(r.get("id")))
    write_jsonl(out_dir / "all.jsonl", all_rows)
    for split, rows in sorted(splits.items()):
        write_jsonl(out_dir / f"{split}.jsonl", sorted(rows, key=lambda r: str(r.get("id"))))
    manifest = {
        "refreshed_from": {
            "path": str(args.original_benchmark),
            "sha256": _sha256(_benchmark_file(args.original_benchmark)),
        },
        "migration_id": migration_id,
        "graph_profile": graph,
        "audit_summary_sha256": _sha256(audit_dir / "refresh_audit_summary.json"),
        "regenerated_sources": [
            {"path": str(p), "sha256": _sha256(_benchmark_file(p))} for p in args.regenerated_export or []
        ],
        "passthrough_other_graphs": passthrough,
        "total_examples": len(all_rows),
        "split_counts": {split: len(rows) for split, rows in sorted(splits.items())},
        "all_sha256": _sha256(out_dir / "all.jsonl"),
        "assembly": report,
        "git_revision": _git_revision(),
        "note": "Split membership changed: rerun downstream and few-shot evaluation on this package.",
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    if not report["complete"] and not args.allow_incomplete:
        print("error: regeneration did not fill every split deficit (see manifest.assembly)", file=sys.stderr)
        return 1
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    meta = _load_migration_meta(args.migration)
    migration_id = args.migration_id or meta.get("id")
    if not migration_id:
        raise SystemExit("--migration-id (or --migration with an id) is required")
    graph = args.graph_profile or meta.get("graph_profile") or "finbench"
    out_dir = Path(args.output_dir or f"artifacts/refresh/{migration_id}/audit")
    out_dir.mkdir(parents=True, exist_ok=True)

    original_cfg, original_client = _client_for(args.original_config)
    migrated_cfg, migrated_client = _client_for(args.migrated_config)
    if endpoints_match(original_cfg.neo4j.uri, migrated_cfg.neo4j.uri) and (
        original_cfg.neo4j.database == migrated_cfg.neo4j.database
    ):
        if not args.allow_same_endpoint:
            raise SystemExit(
                "original and migrated configs point at the same graph; the audit would be vacuous"
            )
    original_schema_path = args.original_schema or original_cfg.paths.schema_path
    migrated_schema_path = args.migrated_schema or migrated_cfg.paths.schema_path
    if not original_schema_path or not migrated_schema_path:
        raise SystemExit("both original and migrated schema JSON paths are required")
    original_schema = load_schema(original_schema_path)
    migrated_schema = load_schema(migrated_schema_path)
    diff = diff_schemas(
        original_schema,
        migrated_schema,
        count_change_threshold=args.count_change_threshold,
        rename_min_confidence=args.rename_detect_confidence,
    )
    problems = check_expected_diff(diff, meta.get("expected_schema_diff"))
    if problems:
        print("warning: expected_schema_diff mismatches:\n  - " + "\n  - ".join(problems), file=sys.stderr)
        if args.strict_expected_diff:
            return 1

    rows, split_by_id = load_benchmark_rows(args.benchmark)
    audited_rows = [row for row in rows if str(row.get("graph_profile")) == graph]
    partial = False
    if args.limit:
        audited_rows = audited_rows[: args.limit]
        partial = True
    options = RefreshAuditOptions(
        migration_id=str(migration_id),
        graph_profile=graph,
        float_digits=args.float_digits,
        rename_rewrite=not args.no_rename_rewrite,
        rename_min_confidence=args.rename_min_confidence,
        result_sample_limit=args.result_sample_limit,
    )

    def progress(index: int, total: int) -> None:
        if index % 100 == 0:
            print(f"[audit] {index}/{total}", file=sys.stderr, flush=True)

    started = time.perf_counter()
    try:
        items, carried = audit_benchmark_refresh(
            audited_rows,
            original_client=original_client,
            migrated_client=migrated_client,
            original_schema=original_schema,
            migrated_schema=migrated_schema,
            options=options,
            diff=diff,
            split_by_id=split_by_id,
            progress=progress,
        )
    finally:
        original_client.close()
    wall = time.perf_counter() - started

    ledger_summary: dict[str, Any] | None = None
    if args.migration_ledger and Path(args.migration_ledger).exists():
        ledger = json.loads(Path(args.migration_ledger).read_text(encoding="utf-8"))
        ledger_summary = {
            "path": args.migration_ledger,
            "sha256": _sha256(args.migration_ledger),
            "status": ledger.get("status"),
            "parameters": ledger.get("parameters"),
            "affected_total": ledger.get("affected_total"),
            "target_db_info": ledger.get("target_db_info"),
            "git_revision": ledger.get("git_revision"),
        }
    provenance = {
        "benchmark": {"path": str(args.benchmark), "sha256": _sha256(_benchmark_file(args.benchmark))},
        "original_config": args.original_config,
        "migrated_config": args.migrated_config,
        "original_endpoint": "%s:%s" % normalize_bolt_endpoint(original_cfg.neo4j.uri),
        "migrated_endpoint": "%s:%s" % normalize_bolt_endpoint(migrated_cfg.neo4j.uri),
        "original_schema": {"path": original_schema_path, "sha256": _sha256(original_schema_path)},
        "migrated_schema": {"path": migrated_schema_path, "sha256": _sha256(migrated_schema_path)},
        "migration_metadata": meta.get("_path"),
        "migration_ledger": ledger_summary,
        "expected_diff_problems": problems,
        "git_revision": _git_revision(),
        "audit_wall_seconds": round(wall, 3),
    }
    summary = summarize_refresh_audit(
        items,
        options=options,
        diff=diff,
        n_rows_total=len(rows),
        provenance=provenance,
        partial=partial,
    )

    write_jsonl(out_dir / "refresh_audit_items.jsonl", items)
    write_jsonl(out_dir / "carried_forward_export.jsonl", carried)
    seen_path = out_dir / "reusable_seen_records.jsonl"
    write_jsonl(seen_path, reusable_seen_records(carried))
    (out_dir / "schema_diff.json").write_text(
        json.dumps(diff.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    if args.regeneration_base_config:
        plan = summary["incremental_plan"]
        summary["regeneration_configs"] = emit_regeneration_configs(
            base_config=args.regeneration_base_config,
            migrated_schema=str(migrated_schema_path),
            targets=plan["regeneration_targets"],
            out_dir=out_dir / "regeneration",
            migration_id=str(migration_id),
            seen_records=seen_path,
            random_seed=args.regeneration_seed,
        )
        totals = {cat: block["total"] for cat, block in plan["by_category"].items()}
        if totals and not partial:
            summary["full_refresh_config"] = emit_full_refresh_config(
                base_config=args.regeneration_base_config,
                migrated_schema=str(migrated_schema_path),
                categories=sorted(totals),
                target_per_category=max(totals.values()),
                out_dir=out_dir / "regeneration",
                migration_id=str(migration_id),
                random_seed=args.regeneration_seed,
            )

    if args.predictions:
        refreshed_path = Path(args.refreshed_export) if args.refreshed_export else out_dir / "carried_forward_export.jsonl"
        refreshed_rows, _ = load_benchmark_rows(refreshed_path)
        predictions = read_jsonl(args.predictions)
        mis_summary, mis_items = accuracy_misestimate(
            predictions,
            rows,
            refreshed_rows,
            migrated_clients={graph: migrated_client},
            audit_items=items,
        )
        mis_summary["predictions"] = {"path": args.predictions, "sha256": _sha256(args.predictions)}
        mis_summary["refreshed_export"] = {"path": str(refreshed_path), "sha256": _sha256(refreshed_path)}
        write_jsonl(out_dir / "misestimate_items.jsonl", mis_items)
        (out_dir / "misestimate_summary.json").write_text(
            json.dumps(mis_summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
        )
        summary["accuracy_misestimate"] = {
            k: mis_summary[k]
            for k in ("stale_accuracy", "refreshed_accuracy", "paired", "headline_misestimate_pp", "n_retired")
        }
    migrated_client.close()

    (out_dir / "refresh_audit_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    overall = summary["overall"]
    print(json.dumps({"migration_id": migration_id, "partial": partial, **overall}, indent=2))
    print(f"Outputs: {out_dir}")
    return 0


# ---------------------------------------------------------------------------
# misestimate


def cmd_misestimate(args: argparse.Namespace) -> int:
    migrated_cfg, migrated_client = _client_for(args.migrated_config)
    stale_rows, _ = load_benchmark_rows(args.benchmark)
    refreshed_rows, _ = load_benchmark_rows(args.refreshed_export)
    predictions = read_jsonl(args.predictions)
    audit_items = read_jsonl(args.audit_items) if args.audit_items else None
    try:
        summary, items = accuracy_misestimate(
            predictions,
            stale_rows,
            refreshed_rows,
            migrated_clients={args.graph_profile: migrated_client},
            audit_items=audit_items,
        )
    finally:
        migrated_client.close()
    summary["provenance"] = {
        "benchmark": {"path": args.benchmark, "sha256": _sha256(_benchmark_file(args.benchmark))},
        "refreshed_export": {"path": args.refreshed_export, "sha256": _sha256(_benchmark_file(args.refreshed_export))},
        "predictions": {"path": args.predictions, "sha256": _sha256(args.predictions)},
        "migrated_endpoint": "%s:%s" % normalize_bolt_endpoint(migrated_cfg.neo4j.uri),
        "git_revision": _git_revision(),
    }
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(out_dir / "misestimate_items.jsonl", items)
    (out_dir / "misestimate_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: summary[k] for k in ("stale_accuracy", "refreshed_accuracy", "paired")}, indent=2))
    return 0


# ---------------------------------------------------------------------------
# table


def cmd_table(args: argparse.Namespace) -> int:
    summaries = [json.loads(Path(path).read_text(encoding="utf-8")) for path in args.summaries]
    timings = json.loads(Path(args.timings).read_text(encoding="utf-8")) if args.timings else None
    try:
        rows = refresh_table_rows(summaries, timings=timings, allow_partial=args.allow_partial)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    markdown = render_refresh_table_markdown(rows)
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(markdown, encoding="utf-8")
    if args.output_csv:
        Path(args.output_csv).parent.mkdir(parents=True, exist_ok=True)
        with Path(args.output_csv).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else [])
            writer.writeheader()
            writer.writerows(rows)
    print(markdown)
    return 0


# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    diff = sub.add_parser("diff", help="Diff two schema JSONs and check expected migration effects")
    diff.add_argument("--before-schema", required=True)
    diff.add_argument("--after-schema", required=True)
    diff.add_argument("--migration", default="", help="Migration id or *.meta.yaml path")
    diff.add_argument("--benchmark", default="", help="Optional export for the static impact plan")
    diff.add_argument("--graph-profile", default="")
    diff.add_argument("--count-change-threshold", type=float, default=0.0)
    diff.add_argument("--rename-detect-confidence", type=float, default=0.6)
    diff.add_argument("--rename-min-confidence", type=float, default=0.75)
    diff.add_argument("--allow-mismatch", action="store_true")
    diff.add_argument("--output", default="")
    diff.set_defaults(func=cmd_diff)

    audit = sub.add_parser("audit", help="Re-execute references on original vs migrated graphs")
    audit.add_argument("--benchmark", required=True, help="Benchmark package dir or JSONL")
    audit.add_argument("--migration", default="", help="Migration id or *.meta.yaml path")
    audit.add_argument("--migration-id", default="")
    audit.add_argument("--graph-profile", default="")
    audit.add_argument("--original-config", required=True)
    audit.add_argument("--migrated-config", required=True)
    audit.add_argument("--original-schema", default="")
    audit.add_argument("--migrated-schema", default="")
    audit.add_argument("--output-dir", default="")
    audit.add_argument("--migration-ledger", default="")
    audit.add_argument("--count-change-threshold", type=float, default=0.0)
    audit.add_argument("--rename-detect-confidence", type=float, default=0.6)
    audit.add_argument("--rename-min-confidence", type=float, default=0.75)
    audit.add_argument("--no-rename-rewrite", action="store_true")
    audit.add_argument("--float-digits", type=int, default=10)
    audit.add_argument("--result-sample-limit", type=int, default=5)
    audit.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Engineering check only: audit the first N items; the summary is marked partial",
    )
    audit.add_argument("--strict-expected-diff", action="store_true")
    audit.add_argument(
        "--allow-same-endpoint",
        action="store_true",
        help="Permit identical original/migrated endpoints (determinism control only)",
    )
    audit.add_argument("--predictions", default="", help="Downstream predictions JSONL")
    audit.add_argument(
        "--refreshed-export",
        default="",
        help="Refreshed references (default: this audit's carried_forward_export.jsonl)",
    )
    audit.add_argument("--regeneration-base-config", default="")
    audit.add_argument("--regeneration-seed", type=int, default=13)
    audit.set_defaults(func=cmd_audit)

    mis = sub.add_parser("misestimate", help="Accuracy against stale vs refreshed references")
    mis.add_argument("--benchmark", required=True, help="Stale (pre-migration) export")
    mis.add_argument("--refreshed-export", required=True)
    mis.add_argument("--predictions", required=True)
    mis.add_argument("--graph-profile", default="finbench")
    mis.add_argument("--migrated-config", required=True)
    mis.add_argument("--audit-items", default="")
    mis.add_argument("--output-dir", required=True)
    mis.set_defaults(func=cmd_misestimate)

    assemble = sub.add_parser("assemble", help="Build the refreshed benchmark package")
    assemble.add_argument("--original-benchmark", required=True, help="Original package dir (for splits)")
    assemble.add_argument("--audit-dir", required=True, help="Output dir of a complete audit")
    assemble.add_argument(
        "--regenerated-export",
        action="append",
        default=[],
        help="Export dir/JSONL from scripts/export_benchmark.py over the regeneration runs (repeatable)",
    )
    assemble.add_argument("--output-dir", required=True)
    assemble.add_argument("--allow-incomplete", action="store_true")
    assemble.set_defaults(func=cmd_assemble)

    table = sub.add_parser("table", help="Render the paper table from audit summaries")
    table.add_argument("--summaries", nargs="+", required=True)
    table.add_argument(
        "--timings",
        default="",
        help="JSON {migration_id: {full_refresh_gpu_hours, incremental_refresh_gpu_hours, audit_wall_minutes}}",
    )
    table.add_argument("--allow-partial", action="store_true")
    table.add_argument("--output-md", default="")
    table.add_argument("--output-csv", default="")
    table.set_defaults(func=cmd_table)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
