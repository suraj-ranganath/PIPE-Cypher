#!/usr/bin/env python3
"""Fetch Neo4j Text2Cypher-2024 and convert it into PIPE-Cypher benchmark packages.

Subcommands:

  list          per-database row counts (and read-only drops) for a split
  download      download the pinned parquet files and verify sha256
  convert       filter by database + split, drop non-read-only rows, write a
                train/dev/test/all.jsonl package (+ optional derived schemas)
  audit-gold    execute every reference query on the local graph(s) and write
                a NEW package that keeps only references that execute (and,
                by default, return rows); every drop is logged
  oracle        write gold-as-prediction rows (harness self-check: scoring them
                must give execution accuracy 1.0 on audited rows)
  subset        filter prediction/evaluation rows to the ids of a slice file
  schema-drift  compare a derived (dataset) schema with a live-introspected one

The package layout matches scripts/export_benchmark.py, so
scripts/generate_text2cypher_predictions.py and
scripts/evaluate_benchmark_predictions.py consume it unchanged:

  python scripts/fetch_text2cypher2024.py convert \
      --download-dir external/text2cypher-2024v1 \
      --output-dir artifacts/external_benchmarks/t2c2024_recommended \
      --databases recommended --derived-schema-dir configs

Only ``download`` and ``convert`` without ``--input`` touch the network; only
``audit-gold`` opens Neo4j connections (read-only transactions).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.external_benchmarks import (
    EXAMPLE_GRAPHS,
    PACKAGE_SPLITS,
    T2C2024_DATASET,
    T2C2024_FILES,
    T2C2024_REVISION,
    T2C2024_SHA256,
    UPSTREAM_SPLITS,
    annotate_upstream_train_overlap,
    apply_gold_audit,
    assign_external_splits,
    audit_gold_execution,
    canonical_database_name,
    convert_t2c_rows,
    derived_schemas_by_profile,
    find_split_file,
    graph_spec_records,
    hf_resolve_url,
    load_t2c_rows,
    oracle_predictions,
    question_overlap,
    read_external_package,
    resolve_database_filter,
    schema_drift,
    sha256_file,
    write_external_benchmark_package,
)
from pipecypher.io import read_jsonl, write_jsonl
from pipecypher.models import SchemaSummary

DEFAULT_DOWNLOAD_DIR = "external/text2cypher-2024v1"
USER_AGENT = "pipe-cypher-fetch/0.1"


def _download(url: str, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=300) as response, tmp.open("wb") as handle:
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            handle.write(chunk)
    tmp.replace(out)


def download_splits(
    download_dir: str | Path,
    splits: list[str],
    *,
    revision: str,
    allow_hash_mismatch: bool = False,
) -> dict[str, Path]:
    """Download pinned parquet files (skipping ones already present) and verify sha256."""

    paths: dict[str, Path] = {}
    for split in splits:
        out = Path(download_dir) / T2C2024_FILES[split]
        if not out.exists():
            url = hf_resolve_url(T2C2024_FILES[split], revision=revision)
            print(f"downloading {url} -> {out}", flush=True)
            _download(url, out)
        digest = sha256_file(out)
        expected = T2C2024_SHA256.get(split) if revision == T2C2024_REVISION else None
        if expected and digest != expected:
            message = f"{out}: sha256 {digest} != pinned {expected} for revision {revision}"
            if not allow_hash_mismatch:
                raise SystemExit(message + " (pass --allow-hash-mismatch to override)")
            print("WARNING " + message, file=sys.stderr)
        paths[split] = out
    return paths


def _split_list(raw: str) -> list[str]:
    splits = [item.strip() for item in raw.split(",") if item.strip()]
    unknown = sorted(set(splits) - set(UPSTREAM_SPLITS))
    if unknown:
        raise SystemExit(f"unknown upstream split(s): {unknown}; choose from {UPSTREAM_SPLITS}")
    return splits


def _resolve_inputs(args: argparse.Namespace, splits: list[str]) -> dict[str, Path]:
    explicit: dict[str, Path] = {}
    for item in args.split_file or []:
        if "=" not in item:
            raise SystemExit("--split-file entries must use split=PATH")
        split, path = item.split("=", 1)
        explicit[split.strip()] = Path(path)
    if explicit:
        missing = [split for split in splits if split not in explicit]
        if missing:
            raise SystemExit(f"--split-file missing split(s): {missing}")
        return {split: explicit[split] for split in splits}
    if args.input:
        return {split: find_split_file(args.input, split) for split in splits}
    return download_splits(
        args.download_dir,
        splits,
        revision=args.revision,
        allow_hash_mismatch=args.allow_hash_mismatch,
    )


def _ensure_empty_output(path: Path, overwrite: bool) -> None:
    if path.exists() and any(path.iterdir()) and not overwrite:
        raise SystemExit(
            f"{path} is not empty; choose a new --output-dir or pass --overwrite "
            "(never mix packages from different filters or revisions)"
        )


def cmd_list(args: argparse.Namespace) -> int:
    splits = _split_list(args.splits)
    inputs = _resolve_inputs(args, splits)
    registry = {spec.database_alias: spec for spec in EXAMPLE_GRAPHS.values()}
    for split, path in inputs.items():
        rows = load_t2c_rows(path)
        result = convert_t2c_rows(rows, split=split, databases=None, revision=args.revision)
        total_with_db = sum(result.counts["by_database_input"].values())
        print(f"split={split} rows={len(rows)} rows_with_database={total_with_db} file={path}")
        aliases = Counter(str(row.get("database_reference_alias")) for row in rows)
        for alias, n in aliases.most_common():
            name = canonical_database_name(alias)
            spec = registry.get(alias)
            kept = result.counts["by_database_kept"].get(name or "", 0)
            status = spec.status if spec else ("no_alias" if name is None else "not_registered")
            print(f"  {alias:<40} rows={n:<6} read_only_unique={kept:<6} status={status}")
    return 0


def cmd_download(args: argparse.Namespace) -> int:
    paths = download_splits(
        args.download_dir,
        _split_list(args.splits),
        revision=args.revision,
        allow_hash_mismatch=args.allow_hash_mismatch,
    )
    for split, path in paths.items():
        print(f"{split}: {path} sha256={sha256_file(path)}")
    return 0


def _write_derived_schemas(
    rows: list[dict[str, Any]],
    databases: set[str] | None,
    out_dir: Path,
    revision: str,
) -> list[str]:
    written: list[str] = []
    for profile, info in derived_schemas_by_profile(rows, databases=databases, revision=revision).items():
        schema: SchemaSummary = info["schema"]
        payload = schema.to_dict()
        payload["provenance"] = {
            "kind": "derived_from_dataset_schema_text",
            "dataset": T2C2024_DATASET,
            "revision": revision,
            "schema_text_sha256": info["schema_sha256"],
            "schema_text_variants": info["variants"],
            "rows_with_selected_variant": info["rows_with_selected_variant"],
            "rows_total": info["rows_total"],
            "note": (
                "Parsed from the dataset's `schema` field (most frequent variant), not "
                "introspected from a live graph. Categorical values are intentionally "
                "omitted. Use only for offline checks and schema-drift comparison; runs "
                "must use the live schema written by scripts/inspect_schema.py."
            ),
        }
        out = out_dir / f"schema_{profile}_derived.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(str(out))
    return written


def cmd_convert(args: argparse.Namespace) -> int:
    splits = _split_list(args.splits)
    databases = resolve_database_filter(args.databases.split(",") if args.databases else None)
    output_dir = Path(args.output_dir)
    _ensure_empty_output(output_dir, args.overwrite)
    inputs = _resolve_inputs(args, splits)

    upstream: dict[str, list[dict[str, Any]]] = {split: [] for split in UPSTREAM_SPLITS}
    dropped: list[dict[str, Any]] = []
    counts: dict[str, Any] = {}
    raw_rows: list[dict[str, Any]] = []
    for split, path in inputs.items():
        rows = load_t2c_rows(path)
        raw_rows.extend(rows)
        result = convert_t2c_rows(
            rows,
            split=split,
            databases=databases,
            revision=args.revision,
            category_mode=args.category_mode,
        )
        upstream[split] = result.examples
        dropped.extend(result.dropped)
        counts[split] = result.counts

    if upstream["train"]:
        annotate_upstream_train_overlap(upstream["test"], upstream["train"])
    package_splits = assign_external_splits(
        upstream["train"],
        upstream["test"],
        dev_fraction=args.dev_fraction,
        seed=args.dev_seed,
    )
    overlap = question_overlap(upstream["train"], upstream["test"]) if upstream["train"] else {}
    manifest_extra = {
        "source": {
            "dataset": T2C2024_DATASET,
            "revision": args.revision,
            "files": {
                split: {"path": str(path), "sha256": sha256_file(path)} for split, path in inputs.items()
            },
            "dataset_card": f"https://huggingface.co/datasets/{T2C2024_DATASET}",
        },
        "filters": {
            "databases": sorted(databases) if databases is not None else "all_with_alias",
            "upstream_splits": splits,
            "read_only_gate": "pipecypher.validator.validate_cypher(...).read_only",
            "category_mode": args.category_mode,
        },
        "split_mapping": {
            "test": "upstream test (unchanged)",
            "train": f"upstream train minus dev ({1 - args.dev_fraction:.2f})",
            "dev": f"hash-ordered {args.dev_fraction:.2f} of upstream train per graph_profile",
            "dev_seed": args.dev_seed,
        },
        "conversion_counts": counts,
        "train_test_question_overlap": overlap,
        "example_graphs": [
            record
            for record in graph_spec_records()
            if databases is None or record["name"] in databases
        ],
    }
    written = write_external_benchmark_package(
        output_dir, package_splits, dropped=dropped, manifest_extra=manifest_extra
    )
    derived_paths: list[str] = []
    if args.derived_schema_dir:
        derived_paths = _write_derived_schemas(raw_rows, databases, Path(args.derived_schema_dir), args.revision)
    for split in splits:
        c = counts[split]
        print(
            f"upstream_split={split} input={c['input_rows']} kept={c['kept']} "
            f"drops={json.dumps(c['drop_reasons'], sort_keys=True)} "
            f"not_read_only_by_db={json.dumps(c['by_database_not_read_only'], sort_keys=True)}"
        )
    print(f"package_split_counts={json.dumps(written['manifest']['split_counts'], sort_keys=True)}")
    print(f"by_graph={json.dumps(written['stats']['by_graph'], sort_keys=True)}")
    if overlap:
        print(f"train_test_question_overlap={json.dumps(overlap, sort_keys=True)}")
    for path in derived_paths:
        print(f"derived_schema={path}")
    print(f"output_dir={output_dir}")
    return 0


def _open_clients(items: list[str]) -> dict[str, Any]:
    from pipecypher.config import load_config
    from pipecypher.cypher_client import Neo4jCypherClient

    clients: dict[str, Any] = {}
    for item in items:
        if "=" not in item:
            raise SystemExit("--config entries must use graph_profile=path")
        profile, path = item.split("=", 1)
        cfg = load_config(path, strict=True, validate=True)
        if cfg.generation.graph_profile != profile:
            raise SystemExit(
                f"{path}: generation.graph_profile={cfg.generation.graph_profile} != {profile}"
            )
        clients[profile] = Neo4jCypherClient(
            cfg.neo4j.uri,
            cfg.neo4j.user,
            cfg.neo4j.password,
            database=cfg.neo4j.database,
            timeout_sec=cfg.neo4j.query_timeout_sec,
            enforce_read_transactions=cfg.neo4j.enforce_read_transactions,
        )
    return clients


def cmd_audit_gold(args: argparse.Namespace) -> int:
    source_dir = Path(args.benchmark)
    output_dir = Path(args.output_dir)
    if output_dir.resolve() == source_dir.resolve():
        raise SystemExit("--output-dir must differ from --benchmark (packages are immutable)")
    _ensure_empty_output(output_dir, args.overwrite)
    audit_splits = [item.strip() for item in args.splits.split(",") if item.strip()]
    package = read_external_package(source_dir)
    profiles = sorted({row["graph_profile"] for split in audit_splits for row in package[split]})
    clients = _open_clients(args.config)
    missing = [profile for profile in profiles if profile not in clients]
    if missing:
        raise SystemExit(f"missing --config for graph_profile(s): {missing}")

    audit_rows: list[dict[str, Any]] = []
    try:
        for split in audit_splits:
            for profile in profiles:
                subset = [row for row in package[split] if row["graph_profile"] == profile]
                rows = audit_gold_execution(subset, clients[profile], max_rows=args.max_rows)
                for row in rows:
                    row["split"] = split
                audit_rows.extend(rows)
                ok = sum(1 for row in rows if row["gold_execution_success"])
                non_empty = sum(1 for row in rows if row["gold_row_count"] > 0)
                print(f"split={split} graph={profile} audited={len(rows)} executed={ok} non_empty={non_empty}")
    finally:
        for client in clients.values():
            client.close()

    new_splits: dict[str, list[dict[str, Any]]] = {}
    gold_drops: list[dict[str, Any]] = []
    for split in PACKAGE_SPLITS:
        if split in audit_splits:
            kept, dropped = apply_gold_audit(
                package[split], audit_rows, require_non_empty=not args.allow_empty_gold
            )
            for row in dropped:
                row["split"] = split
            new_splits[split] = kept
            gold_drops.extend(dropped)
        else:
            new_splits[split] = package[split]
    parent_manifest = json.loads((source_dir / "manifest.json").read_text(encoding="utf-8"))
    summary = {
        split: dict(Counter(row["reason"] for row in gold_drops if row.get("split") == split))
        for split in audit_splits
    }
    manifest_extra = {
        "parent_package": str(source_dir),
        "parent_sha256": parent_manifest.get("sha256"),
        "source": parent_manifest.get("source"),
        "filters": {
            **(parent_manifest.get("filters") or {}),
            "gold_audit": {
                "audited_splits": audit_splits,
                "require_non_empty": not args.allow_empty_gold,
                "max_rows": args.max_rows,
                "configs": args.config,
                "execution": "reference executed as written (clean_cypher), read-only transaction",
            },
        },
        "gold_audit_drop_summary": summary,
        "evidence_status": "external_curated_input_gold_audited",
    }
    written = write_external_benchmark_package(
        output_dir,
        new_splits,
        dropped=list(read_jsonl(source_dir / "dropped.jsonl")) + gold_drops,
        manifest_extra=manifest_extra,
    )
    write_jsonl(output_dir / "gold_audit.jsonl", audit_rows)
    print(f"gold_audit_drops={json.dumps(summary, sort_keys=True)}")
    print(f"package_split_counts={json.dumps(written['manifest']['split_counts'], sort_keys=True)}")
    print(f"output_dir={output_dir}")
    return 0


def cmd_oracle(args: argparse.Namespace) -> int:
    path = Path(args.benchmark)
    rows = read_jsonl(path / f"{args.split}.jsonl" if path.is_dir() else path)
    write_jsonl(args.output, oracle_predictions(rows, model=args.model))
    print(f"wrote_oracle_predictions={len(rows)} output={args.output}")
    return 0


def cmd_subset(args: argparse.Namespace) -> int:
    """Keep rows (predictions or evaluation rows) whose id is in a benchmark file.

    The evaluator rejects prediction ids missing from --benchmark, so slices
    (unseen-question, per-graph, no-unordered-limit) are scored post hoc by
    filtering one full-test evaluation file instead of re-running models.
    """

    keep = {str(row["id"]) for row in read_jsonl(args.benchmark)}
    rows = read_jsonl(args.rows)
    subset = [row for row in rows if str(row.get("id")) in keep]
    found = {str(row.get("id")) for row in subset}
    missing = sorted(keep - found)
    if missing and not args.allow_missing:
        raise SystemExit(
            f"{len(missing)} benchmark ids have no row in {args.rows} (e.g. {missing[:3]}); "
            "a slice must be a subset of the scored rows"
        )
    write_jsonl(args.output, subset)
    print(f"kept={len(subset)} of {len(rows)} rows; benchmark_ids={len(keep)} output={args.output}")
    return 0


def cmd_schema_drift(args: argparse.Namespace) -> int:
    reference = SchemaSummary.from_dict(json.loads(Path(args.derived).read_text(encoding="utf-8")))
    live = SchemaSummary.from_dict(json.loads(Path(args.live).read_text(encoding="utf-8")))
    drift = schema_drift(reference, live)
    print(json.dumps(drift, indent=2, sort_keys=True))
    return 0 if drift["compatible"] or not args.fail_on_drift else 4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    source = argparse.ArgumentParser(add_help=False)
    source.add_argument("--input", default="", help="Local mirror directory (parquet or JSONL per split)")
    source.add_argument(
        "--split-file", action="append", help="Explicit split=PATH input (parquet/JSONL/JSON); repeatable"
    )
    source.add_argument("--download-dir", default=DEFAULT_DOWNLOAD_DIR)
    source.add_argument("--revision", default=T2C2024_REVISION, help="Hub commit to pin downloads to")
    source.add_argument("--allow-hash-mismatch", action="store_true")

    listing = sub.add_parser("list", parents=[source], help="Per-database counts")
    listing.add_argument("--splits", default="test")
    listing.set_defaults(func=cmd_list)

    download = sub.add_parser("download", parents=[source], help="Download pinned parquet files")
    download.add_argument("--splits", default="train,test")
    download.set_defaults(func=cmd_download)

    convert = sub.add_parser("convert", parents=[source], help="Convert to a PIPE-Cypher package")
    convert.add_argument("--output-dir", required=True)
    convert.add_argument(
        "--databases",
        default="recommended",
        help="Comma list: short names, dataset aliases, t2c_ profiles, 'recommended', or 'all'",
    )
    convert.add_argument("--splits", default="train,test", help="Upstream splits to convert")
    convert.add_argument("--dev-fraction", type=float, default=0.1)
    convert.add_argument("--dev-seed", default="t2c2024-dev-v1")
    convert.add_argument(
        "--category-mode",
        choices=["external", "derived"],
        default="external",
        help="category field: 'external' (default) or the structural derived_category",
    )
    convert.add_argument(
        "--derived-schema-dir",
        default="",
        help="Also write schema_t2c_<name>_derived.json parsed from the dataset schema text",
    )
    convert.add_argument("--overwrite", action="store_true")
    convert.set_defaults(func=cmd_convert)

    audit = sub.add_parser("audit-gold", help="Execute references on local graphs; write a filtered package")
    audit.add_argument("--benchmark", required=True, help="Package written by 'convert'")
    audit.add_argument("--config", action="append", required=True, help="graph_profile=config.yaml")
    audit.add_argument("--output-dir", required=True)
    audit.add_argument("--splits", default="test", help="Package splits to audit (others copied)")
    audit.add_argument("--max-rows", type=int, default=1000)
    audit.add_argument(
        "--allow-empty-gold",
        action="store_true",
        help="Keep references that execute but return no rows (default drops them, matching "
        "PIPE-Cypher's require_non_empty gate)",
    )
    audit.add_argument("--overwrite", action="store_true")
    audit.set_defaults(func=cmd_audit_gold)

    oracle = sub.add_parser("oracle", help="Write gold-as-prediction rows for a harness self-check")
    oracle.add_argument("--benchmark", required=True)
    oracle.add_argument("--split", default="test", choices=list(PACKAGE_SPLITS) + ["all"])
    oracle.add_argument("--output", required=True)
    oracle.add_argument("--model", default="oracle_gold_reference")
    oracle.set_defaults(func=cmd_oracle)

    subset = sub.add_parser("subset", help="Filter prediction/evaluation rows to a slice's ids")
    subset.add_argument("--rows", required=True, help="Predictions or evaluation JSONL")
    subset.add_argument("--benchmark", required=True, help="Slice JSONL, e.g. PKG/slices/test_unseen_question.jsonl")
    subset.add_argument("--output", required=True)
    subset.add_argument("--allow-missing", action="store_true")
    subset.set_defaults(func=cmd_subset)

    drift = sub.add_parser("schema-drift", help="Compare derived vs live schema JSON")
    drift.add_argument("--derived", required=True)
    drift.add_argument("--live", required=True)
    drift.add_argument("--fail-on-drift", action="store_true")
    drift.set_defaults(func=cmd_schema_drift)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
