#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.ablation_suite import DEFAULT_GRAPHS, DEFAULT_VARIANTS
from pipecypher.remote_collection import (
    build_remote_ablation_status_command,
    build_tmux_has_session_command,
    parse_remote_ablation_status_rows,
)
from scripts.monitor_remote_ablation_suite import build_progress_report, format_progress_text


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only monitor for multiple remote PIPE-Cypher ablation suites."
    )
    parser.add_argument(
        "--queue",
        default="experiments/remote_ablation_queue.yaml",
        help="YAML file with a top-level suites list.",
    )
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    suites = load_queue_config(args.queue)
    reports = [
        monitor_suite_from_config(suite, dry_run=args.dry_run)
        for suite in suites
    ]
    queue_report = build_queue_report(reports)
    if args.format == "json":
        print(json.dumps(queue_report, indent=2, sort_keys=True))
        return
    print(format_queue_text(queue_report))


def load_queue_config(path: str | Path) -> list[dict[str, Any]]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    suites = data.get("suites")
    if not isinstance(suites, list) or not suites:
        raise SystemExit(f"{path} must contain a non-empty suites list")
    normalized: list[dict[str, Any]] = []
    for index, suite in enumerate(suites):
        if not isinstance(suite, dict):
            raise SystemExit(f"suite #{index + 1} must be a mapping")
        missing = [
            key
            for key in ("name", "run_prefix", "target_per_category", "remote_root", "session")
            if key not in suite
        ]
        if missing:
            raise SystemExit(f"suite #{index + 1} is missing required keys: {', '.join(missing)}")
        normalized.append(dict(suite))
    return normalized


def monitor_suite_from_config(suite: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    host = str(suite.get("host", "suraj@ds-serv6.ucsd.edu"))
    session = str(suite.get("session", ""))
    rows_text = _remote_status(
        host=host,
        remote_root=str(suite["remote_root"]),
        run_prefix=str(suite["run_prefix"]),
        dry_run=dry_run,
    )
    session_running = None
    if session:
        session_running = _remote_session_running(host=host, session=session, dry_run=dry_run)
    rows = parse_remote_ablation_status_rows(rows_text)
    report = build_progress_report(
        rows,
        run_prefix=str(suite["run_prefix"]),
        target_per_category=int(suite["target_per_category"]),
        category_count=int(suite.get("category_count", 8)),
        expected_graphs=list(suite.get("expected_graphs") or DEFAULT_GRAPHS),
        expected_variants=list(suite.get("expected_variants") or DEFAULT_VARIANTS),
        session=session,
        session_running=session_running,
    )
    report["name"] = str(suite["name"])
    report["host"] = host
    report["remote_root"] = str(suite["remote_root"])
    report["configured_status"] = str(suite.get("status", ""))
    report["generation_model"] = str(suite.get("generation_model", ""))
    report["judge_model"] = str(suite.get("judge_model", ""))
    report["run_seed"] = str(suite.get("run_seed", ""))
    report["code_revision"] = str(suite.get("code_revision", ""))
    report["notes"] = str(suite.get("notes", ""))
    report["suite_state"] = infer_suite_state(report)
    report["next_action"] = infer_next_action(report)
    report["collection_command"] = build_collection_command(report)
    return report


def infer_suite_state(report: dict[str, Any]) -> str:
    if report["completed_cells"] == report["expected_cells"] and report["expected_cells"]:
        if is_configured_collected(report):
            return "complete_collected"
        return "complete"
    if report["observed_cells"] == 0 and report.get("session_running"):
        return "queued_or_waiting"
    if report.get("session_running"):
        return "running"
    if report["observed_cells"] == 0:
        return "not_started_or_missing"
    return "incomplete_session_stopped"


def infer_next_action(report: dict[str, Any]) -> str:
    state = report["suite_state"]
    if state == "complete_collected":
        return "no_action_required_already_collected"
    if state == "complete":
        return "collect_and_run_readiness_audit"
    if state == "running":
        if report.get("over_target_incomplete_cells"):
            return "investigate_over_target_incomplete_cell"
        return "wait_for_active_session_then_collect"
    if state == "queued_or_waiting":
        return "wait_for_dependency_or_session_start"
    if state == "incomplete_session_stopped":
        return "investigate_stopped_incomplete_suite"
    return "verify_remote_root_or_launch_session"


def is_configured_collected(report: dict[str, Any]) -> bool:
    configured_status = str(report.get("configured_status", "")).lower()
    return "collected" in configured_status or "paper_ready" in configured_status


def build_collection_command(report: dict[str, Any]) -> str:
    if report.get("next_action") == "no_action_required_already_collected":
        return ""
    parts = [
        "python",
        "scripts/collect_remote_ablation_suite.py",
        "--remote-root",
        str(report["remote_root"]),
        "--run-prefix",
        str(report["run_prefix"]),
        "--target-per-category",
        str(report["target_per_category"]),
    ]
    if report.get("session"):
        parts.extend(["--wait-session", str(report["session"])])
    parts.extend(["--poll-seconds", "60"])
    return " ".join(parts)


def build_queue_report(reports: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "suite_count": len(reports),
        "complete_suites": sum(
            1 for report in reports if report["suite_state"] in {"complete", "complete_collected"}
        ),
        "running_suites": sum(1 for report in reports if report["suite_state"] == "running"),
        "queued_or_waiting_suites": sum(
            1 for report in reports if report["suite_state"] == "queued_or_waiting"
        ),
        "reports": reports,
    }


def format_queue_text(queue_report: dict[str, Any]) -> str:
    lines = [
        "remote_ablation_queue",
        "suites={suite_count} complete={complete_suites} running={running_suites} "
        "queued_or_waiting={queued_or_waiting_suites}".format(**queue_report),
        "",
    ]
    for report in queue_report["reports"]:
        lines.extend(
            [
                f"## {report['name']}",
                f"state={report['suite_state']} configured_status={report['configured_status']}",
                f"next_action={report['next_action']}",
                f"remote_root={report['remote_root']}",
            ]
        )
        if report.get("code_revision"):
            lines.append(f"code_revision={report['code_revision']}")
        if report.get("generation_model"):
            lines.append(
                f"generation_model={report['generation_model']} judge_model={report['judge_model']}"
            )
        if report.get("run_seed"):
            lines.append(f"run_seed={report['run_seed']}")
        if report.get("notes"):
            lines.append(f"notes={report['notes']}")
        if report.get("collection_command"):
            lines.append(f"collection_command={report['collection_command']}")
        else:
            lines.append("collection_command=not_applicable")
        lines.append(format_progress_text(report))
        lines.append("")
    return "\n".join(lines).rstrip()


def _remote_status(*, host: str, remote_root: str, run_prefix: str, dry_run: bool) -> str:
    command = build_remote_ablation_status_command(
        remote_root=remote_root,
        run_prefix=run_prefix,
    )
    if dry_run:
        print("+", "ssh", host, command)
        return ""
    return subprocess.check_output(["ssh", host, command], text=True)


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


if __name__ == "__main__":
    main()
