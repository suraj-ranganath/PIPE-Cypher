#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.ablation_suite import DEFAULT_GRAPHS, DEFAULT_VARIANTS, infer_graph, infer_variant, variant_label
from pipecypher.remote_collection import (
    build_remote_ablation_status_command,
    build_tmux_has_session_command,
    parse_remote_ablation_status_rows,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only progress monitor for a remote live ablation suite."
    )
    parser.add_argument("--host", default="suraj@ds-serv6.ucsd.edu")
    parser.add_argument("--remote-root", default="/home/suraj/PIPE-Cypher")
    parser.add_argument("--run-prefix", required=True)
    parser.add_argument("--target-per-category", type=int, default=50)
    parser.add_argument("--category-count", type=int, default=8)
    parser.add_argument("--session", default="")
    parser.add_argument("--expected-graph", action="append")
    parser.add_argument("--expected-variant", action="append")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    graphs = args.expected_graph or list(DEFAULT_GRAPHS)
    variants = args.expected_variant or list(DEFAULT_VARIANTS)
    session_running = None
    if args.session:
        session_running = _remote_session_running(
            host=args.host,
            session=args.session,
            dry_run=args.dry_run,
        )
    status_text = _remote_status(
        host=args.host,
        remote_root=args.remote_root,
        run_prefix=args.run_prefix,
        dry_run=args.dry_run,
    )
    rows = parse_remote_ablation_status_rows(status_text)
    report = build_progress_report(
        rows,
        run_prefix=args.run_prefix,
        target_per_category=args.target_per_category,
        category_count=args.category_count,
        expected_graphs=graphs,
        expected_variants=variants,
        session=args.session,
        session_running=session_running,
    )
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
        return
    print(format_progress_text(report))


def build_progress_report(
    rows: list[dict],
    *,
    run_prefix: str,
    target_per_category: int,
    category_count: int,
    expected_graphs: list[str],
    expected_variants: list[str],
    session: str = "",
    session_running: bool | None = None,
) -> dict:
    enriched = []
    for row in rows:
        graph = infer_graph(str(row["run"]))
        variant = infer_variant(str(row["run"]))
        records = int(row["records"])
        target_records = target_per_category * category_count
        enriched.append(
            {
                **row,
                "graph": graph,
                "variant": variant,
                "variant_label": variant_label(variant),
                "record_target": target_records,
                "record_progress": min(records / target_records, 1.0) if target_records else 0.0,
                "over_target_without_summary": bool(
                    target_records and records >= target_records and not row["summary_present"]
                ),
            }
        )
    seen = {(row["graph"], row["variant"]) for row in enriched}
    missing = [
        {"graph": graph, "variant": variant}
        for graph in expected_graphs
        for variant in expected_variants
        if (graph, variant) not in seen
    ]
    completed = [row for row in enriched if row["summary_present"]]
    active = [row for row in enriched if not row["summary_present"]]
    over_target_incomplete = [row for row in active if row["over_target_without_summary"]]
    return {
        "run_prefix": run_prefix,
        "target_per_category": target_per_category,
        "category_count": category_count,
        "expected_cells": len(expected_graphs) * len(expected_variants),
        "observed_cells": len(enriched),
        "completed_cells": len(completed),
        "active_or_incomplete_cells": len(active),
        "over_target_incomplete_cells": len(over_target_incomplete),
        "over_target_incomplete": [
            {
                "graph": row["graph"],
                "variant": row["variant"],
                "records": row["records"],
                "record_target": row["record_target"],
                "run": row["run"],
            }
            for row in sorted(
                over_target_incomplete,
                key=lambda item: (item["graph"], item["variant"], item["run"]),
            )
        ],
        "session": session,
        "session_running": session_running,
        "rows": sorted(enriched, key=lambda row: (row["graph"], row["variant"], row["run"])),
        "missing": missing,
    }


def format_progress_text(report: dict) -> str:
    lines = [
        f"run_prefix={report['run_prefix']}",
        f"target_per_category={report['target_per_category']}",
        f"cells={report['observed_cells']}/{report['expected_cells']} observed, "
        f"{report['completed_cells']} complete, "
        f"{report['active_or_incomplete_cells']} active/incomplete",
    ]
    if report.get("session"):
        lines.append(
            f"session={report['session']} running={str(report.get('session_running')).lower()}"
        )
    lines.extend(
        [
            "",
            "| Graph | Variant | Records | Target records | Progress | Summary | Run |",
            "| --- | --- | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for row in report["rows"]:
        summary = "yes" if row["summary_present"] else "no"
        if row.get("over_target_without_summary"):
            summary = "no-over-target"
        lines.append(
            "| {graph} | {variant} | {records} | {target} | {progress:.3f} | {summary} | `{run}` |".format(
                graph=row["graph"],
                variant=row["variant_label"],
                records=row["records"],
                target=row["record_target"],
                progress=row["record_progress"],
                summary=summary,
                run=row["run"],
            )
        )
    if report.get("over_target_incomplete"):
        lines.extend(["", "Over-target incomplete cells:"])
        for item in report["over_target_incomplete"]:
            lines.append(
                "- {graph} / {variant}: {records}/{target} records without summary (`{run}`)".format(
                    graph=item["graph"],
                    variant=variant_label(str(item["variant"])),
                    records=item["records"],
                    target=item["record_target"],
                    run=item["run"],
                )
            )
    if report["missing"]:
        lines.extend(["", "Missing cells:"])
        for item in report["missing"]:
            lines.append(f"- {item['graph']} / {item['variant']}")
    return "\n".join(lines)


def _remote_session_running(*, host: str, session: str, dry_run: bool) -> bool | None:
    command = build_tmux_has_session_command(session)
    if dry_run:
        print("+", "ssh", host, command)
        return None
    result = subprocess.run(
        ["ssh", host, command],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def _remote_status(*, host: str, remote_root: str, run_prefix: str, dry_run: bool) -> str:
    command = build_remote_ablation_status_command(
        remote_root=remote_root,
        run_prefix=run_prefix,
    )
    if dry_run:
        print("+", "ssh", host, command)
        return ""
    return subprocess.check_output(["ssh", host, command], text=True)


if __name__ == "__main__":
    main()
