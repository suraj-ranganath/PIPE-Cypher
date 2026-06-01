#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.remote_collection import (
    build_remote_find_runs_command,
    build_rsync_run_command,
    build_summary_metadata,
    build_tmux_has_session_command,
    parse_run_log_metadata,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch a completed remote ablation suite from ds-serv6 and summarize it "
            "with local paper-readiness checks."
        )
    )
    parser.add_argument("--host", default="suraj@ds-serv6.ucsd.edu")
    parser.add_argument("--remote-root", default="/home/suraj/PIPE-Cypher")
    parser.add_argument("--run-prefix", required=True)
    parser.add_argument("--target-per-category", type=int)
    parser.add_argument("--category-count", type=int, default=8)
    parser.add_argument("--local-run-root", default="artifacts/runs")
    parser.add_argument("--snapshot-dir")
    parser.add_argument("--log-file")
    parser.add_argument("--generation-model")
    parser.add_argument("--judge-model")
    parser.add_argument("--code-revision")
    parser.add_argument("--python-bin", default=sys.executable)
    parser.add_argument(
        "--wait-session",
        help="Remote tmux session to wait for before fetching artifacts.",
    )
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=0,
        help="Maximum wait time for --wait-session; 0 means no timeout.",
    )
    parser.add_argument(
        "--render-paper",
        action="store_true",
        help="Also render paper ablation tables and figure; guarded by paper-readiness audit.",
    )
    parser.add_argument(
        "--allow-diagnostic-render",
        action="store_true",
        help="Allow table/figure rendering even when the paper-readiness audit fails.",
    )
    parser.add_argument("--paper-dir", default="paper_emnlp2026_industry")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.poll_seconds <= 0:
        raise SystemExit("--poll-seconds must be positive")
    if args.timeout_seconds < 0:
        raise SystemExit("--timeout-seconds cannot be negative")
    if args.wait_session:
        _wait_for_remote_session(
            host=args.host,
            session=args.wait_session,
            poll_seconds=args.poll_seconds,
            timeout_seconds=args.timeout_seconds,
            dry_run=args.dry_run,
        )

    snapshot_dir = Path(args.snapshot_dir or f"experiments/snapshots/{args.run_prefix}")
    log_file = args.log_file or f"logs/{args.run_prefix}.log"
    log_text = _remote_cat(
        host=args.host,
        remote_root=args.remote_root,
        path=log_file,
        dry_run=args.dry_run,
    )
    parsed_log = parse_run_log_metadata(log_text)
    target_per_category = args.target_per_category or _target_from_log(parsed_log)
    metadata = build_summary_metadata(
        run_prefix=args.run_prefix,
        log_file=log_file,
        parsed_log=parsed_log,
        generation_model=args.generation_model,
        judge_model=args.judge_model,
        code_revision=args.code_revision,
    )

    run_names = _remote_run_names(
        host=args.host,
        remote_root=args.remote_root,
        run_prefix=args.run_prefix,
        dry_run=args.dry_run,
    )
    if not run_names and not args.dry_run:
        raise SystemExit(f"no remote run directories matched run_prefix={args.run_prefix!r}")

    Path(args.local_run_root).mkdir(parents=True, exist_ok=True)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    if log_text and not args.dry_run:
        (snapshot_dir / "remote_run.log").write_text(log_text, encoding="utf-8")

    for run_name in run_names:
        _run(
            build_rsync_run_command(
                host=args.host,
                remote_root=args.remote_root,
                run_dir_name=run_name,
                local_run_root=args.local_run_root,
            ),
            dry_run=args.dry_run,
        )

    summary_cmd = [
        args.python_bin,
        "scripts/summarize_live_ablation_suite.py",
        "--glob",
        f"{args.local_run_root}/*{args.run_prefix}*",
        "--target-per-category",
        str(target_per_category),
        "--category-count",
        str(args.category_count),
        "--output-json",
        str(snapshot_dir / "ablation_suite_summary.json"),
        "--output-md",
        str(snapshot_dir / "ablation_suite_summary.md"),
        "--output-csv",
        str(snapshot_dir / "ablation_suite_summary.csv"),
        "--output-audit-json",
        str(snapshot_dir / "ablation_suite_audit.json"),
        "--output-audit-md",
        str(snapshot_dir / "ablation_suite_audit.md"),
    ]
    for key, value in metadata.items():
        if value:
            summary_cmd.extend(["--metadata", f"{key}={value}"])
    if args.render_paper:
        paper_dir = Path(args.paper_dir)
        summary_cmd.extend(
            [
                "--output-tex",
                str(paper_dir / "tables_ablation_results.tex"),
                "--output-quality-tex",
                str(paper_dir / "tables_ablation_quality.tex"),
            ]
        )
        if args.allow_diagnostic_render:
            summary_cmd.append("--allow-incomplete-tex")
    _run(summary_cmd, dry_run=args.dry_run)

    if args.render_paper:
        figure_cmd = [
            args.python_bin,
            "scripts/render_ablation_suite_figure.py",
            "--suite-summary",
            str(snapshot_dir / "ablation_suite_summary.json"),
            "--output",
            str(Path(args.paper_dir) / "figures" / f"ablation_suite_target{target_per_category}.pdf"),
        ]
        if args.allow_diagnostic_render:
            figure_cmd.append("--allow-incomplete")
        _run(figure_cmd, dry_run=args.dry_run)


def _target_from_log(metadata: dict[str, str]) -> int:
    raw = metadata.get("target_per_category")
    if not raw:
        raise SystemExit("--target-per-category is required when the remote log does not contain it")
    return int(raw)


def _wait_for_remote_session(
    *,
    host: str,
    session: str,
    poll_seconds: int,
    timeout_seconds: int,
    dry_run: bool,
) -> None:
    command = build_tmux_has_session_command(session)
    if dry_run:
        print("+ wait-until-missing", "ssh", host, command)
        return

    start = time.monotonic()
    while True:
        result = subprocess.run(
            ["ssh", host, command],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode != 0:
            print(f"remote tmux session ended: {session}")
            return
        elapsed = time.monotonic() - start
        if timeout_seconds and elapsed >= timeout_seconds:
            raise SystemExit(
                f"timed out after {timeout_seconds}s waiting for remote session {session!r}"
            )
        print(f"waiting_for_remote_session={session}", flush=True)
        if timeout_seconds:
            sleep_seconds = min(poll_seconds, max(timeout_seconds - elapsed, 1))
        else:
            sleep_seconds = poll_seconds
        time.sleep(sleep_seconds)


def _remote_cat(*, host: str, remote_root: str, path: str, dry_run: bool) -> str:
    command = f"cd {remote_root!r} && cat {path!r} 2>/dev/null || true"
    if dry_run:
        print("+", "ssh", host, command)
        return ""
    return subprocess.check_output(["ssh", host, command], text=True)


def _remote_run_names(
    *,
    host: str,
    remote_root: str,
    run_prefix: str,
    dry_run: bool,
) -> list[str]:
    command = build_remote_find_runs_command(remote_root=remote_root, run_prefix=run_prefix)
    if dry_run:
        print("+", "ssh", host, command)
        return []
    output = subprocess.check_output(["ssh", host, command], text=True)
    return [line.strip() for line in output.splitlines() if line.strip()]


def _run(command: list[str], *, dry_run: bool) -> None:
    if dry_run:
        print("+", " ".join(command))
        return
    subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
