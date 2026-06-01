from __future__ import annotations

from pathlib import Path

from pipecypher.remote_collection import (
    build_remote_ablation_status_command,
    build_collection_manifest,
    build_remote_find_runs_command,
    build_rsync_run_command,
    build_summary_metadata,
    build_tmux_has_session_command,
    parse_run_log_metadata,
    parse_remote_ablation_status_rows,
)
from scripts.monitor_remote_ablation_suite import build_progress_report, format_progress_text
from scripts.monitor_remote_ablation_queue import (
    build_collection_command,
    build_queue_report,
    format_queue_text,
    infer_next_action,
    infer_suite_state,
    load_queue_config,
)


def test_parse_run_log_metadata_reads_first_header_values():
    metadata = parse_run_log_metadata(
        "\n".join(
            [
                "run_prefix=20260601_ablation50_qwen9b",
                "target_per_category=50",
                "generation_model=Qwen/Qwen3.5-9B",
                "judge_model=Qwen/Qwen3.5-9B",
                "run_seed=101",
                "code_revision=b5d4898",
                "run graph=finbench variant=reverse_only",
                "run_seed=later_should_not_override",
                "code_revision=later_should_not_override",
            ]
        )
    )

    assert metadata == {
        "run_prefix": "20260601_ablation50_qwen9b",
        "target_per_category": "50",
        "generation_model": "Qwen/Qwen3.5-9B",
        "judge_model": "Qwen/Qwen3.5-9B",
        "run_seed": "101",
        "code_revision": "b5d4898",
    }


def test_build_remote_find_runs_command_quotes_prefix():
    command = build_remote_find_runs_command(
        remote_root="/home/suraj/PIPE-Cypher",
        run_prefix="20260601_ablation50_qwen9b",
    )

    assert command.startswith("cd /home/suraj/PIPE-Cypher || exit 2;")
    assert "[ -d artifacts/runs ] || exit 0" in command
    assert "-name '*20260601_ablation50_qwen9b*'" in command


def test_build_remote_ablation_status_command_counts_records_and_summary():
    command = build_remote_ablation_status_command(
        remote_root="/home/suraj/PIPE-Cypher",
        run_prefix="20260601_ablation50_qwen9b",
    )

    assert "[ -d artifacts/runs ] || exit 0" in command
    assert "wc -l < \"$d/records.jsonl\"" in command
    assert "summary=yes" in command
    assert "-name '*20260601_ablation50_qwen9b*'" in command


def test_parse_remote_ablation_status_rows_skips_bad_lines():
    rows = parse_remote_ablation_status_rows(
        "run_a\t400\tyes\nbad line\nrun_b\t17\tno\n"
    )

    assert rows == [
        {"run": "run_a", "records": 400, "summary_present": True},
        {"run": "run_b", "records": 17, "summary_present": False},
    ]


def test_build_tmux_has_session_command_quotes_session():
    assert (
        build_tmux_has_session_command("pipecypher_ablation50_qwen9b")
        == "tmux has-session -t =pipecypher_ablation50_qwen9b"
    )
    assert (
        build_tmux_has_session_command("session with spaces")
        == "tmux has-session -t '=session with spaces'"
    )


def test_build_rsync_run_command_targets_local_run_root():
    command = build_rsync_run_command(
        host="suraj@ds-serv6.ucsd.edu",
        remote_root="/home/suraj/PIPE-Cypher",
        run_dir_name="20260601_220247_20260601_ablation50_qwen9b_finbench_reverse_only",
        local_run_root="artifacts/runs",
    )

    assert command == [
        "rsync",
        "-a",
        "suraj@ds-serv6.ucsd.edu:/home/suraj/PIPE-Cypher/artifacts/runs/20260601_220247_20260601_ablation50_qwen9b_finbench_reverse_only/",
        "artifacts/runs/20260601_220247_20260601_ablation50_qwen9b_finbench_reverse_only",
    ]


def test_build_summary_metadata_prefers_explicit_over_log():
    metadata = build_summary_metadata(
        run_prefix="run",
        log_file="logs/run.log",
        parsed_log={
            "generation_model": "Qwen/Old",
            "judge_model": "Qwen/Old",
            "run_seed": "19",
            "code_revision": "old",
        },
        generation_model="Qwen/New",
        judge_model=None,
        code_revision="new",
    )

    assert metadata == {
        "run_prefix": "run",
        "generation_model": "Qwen/New",
        "judge_model": "Qwen/Old",
        "run_seed": "19",
        "code_revision": "new",
        "log_file": "logs/run.log",
    }


def test_build_collection_manifest_hashes_snapshot_and_run_files(tmp_path: Path):
    snapshot_dir = tmp_path / "snapshots" / "suite"
    run_root = tmp_path / "runs"
    paper_dir = tmp_path / "paper"
    run_dir = run_root / "20260601_ablation50_finbench_full_pipe_cypher"
    run_dir.mkdir(parents=True)
    snapshot_dir.mkdir(parents=True)
    (paper_dir / "figures").mkdir(parents=True)
    (run_dir / "records.jsonl").write_text('{"accepted": true}\n', encoding="utf-8")
    (run_dir / "summary.txt").write_text("accepted=1\n", encoding="utf-8")
    (snapshot_dir / "remote_run.log").write_text("run_prefix=run\n", encoding="utf-8")
    (snapshot_dir / "ablation_suite_summary.json").write_text("{}\n", encoding="utf-8")
    (paper_dir / "tables_ablation_results.tex").write_text("% table\n", encoding="utf-8")
    (paper_dir / "figures" / "ablation_suite_target50.pdf").write_bytes(b"%PDF-1.4\n")

    manifest = build_collection_manifest(
        host="suraj@ds-serv6.ucsd.edu",
        remote_root="/home/suraj/PIPE-Cypher",
        run_prefix="20260601_ablation50",
        target_per_category=50,
        category_count=8,
        snapshot_dir=snapshot_dir,
        local_run_root=run_root,
        run_names=["20260601_ablation50_finbench_full_pipe_cypher"],
        metadata={"code_revision": "abc123"},
        log_file="logs/run.log",
        render_paper=True,
        paper_dir=paper_dir,
        collected_at="2026-06-01T00:00:00+00:00",
    )

    assert manifest["collected_at"] == "2026-06-01T00:00:00+00:00"
    assert manifest["run_count"] == 1
    run_files = manifest["runs"]["20260601_ablation50_finbench_full_pipe_cypher"]
    assert len(run_files["records.jsonl"]["sha256"]) == 64
    assert manifest["snapshot_files"]["remote_run.log"]["bytes"] == len("run_prefix=run\n")
    assert "tables_ablation_results.tex" in manifest["paper_files"]
    assert "figures/ablation_suite_target50.pdf" in manifest["paper_files"]


def test_build_progress_report_marks_missing_and_active_cells():
    report = build_progress_report(
        [
            {
                "run": "20260601_ablation50_qwen9b_finbench_reverse_only",
                "records": 400,
                "summary_present": True,
            },
            {
                "run": "20260601_ablation50_qwen9b_snb_full_pipe_cypher",
                "records": 17,
                "summary_present": False,
            },
        ],
        run_prefix="20260601_ablation50_qwen9b",
        target_per_category=50,
        category_count=8,
        expected_graphs=["finbench", "snb"],
        expected_variants=["reverse_only", "full_pipe_cypher"],
        session="suite",
        session_running=True,
    )
    text = format_progress_text(report)

    assert report["observed_cells"] == 2
    assert report["completed_cells"] == 1
    assert report["active_or_incomplete_cells"] == 1
    assert {"graph": "finbench", "variant": "full_pipe_cypher"} in report["missing"]
    assert "session=suite running=true" in text
    assert "| snb | Full PIPE-Cypher | 17 | 400 | 0.043 | no |" in text


def test_load_queue_config_validates_required_fields(tmp_path: Path):
    queue = tmp_path / "queue.yaml"
    queue.write_text(
        "\n".join(
            [
                "suites:",
                "  - name: target100",
                "    run_prefix: 20260601_ablation100_qwen9b",
                "    target_per_category: 100",
                "    remote_root: /home/suraj/PIPE-Cypher-target100",
                "    session: pipecypher_ablation100_qwen9b",
            ]
        ),
        encoding="utf-8",
    )

    suites = load_queue_config(queue)

    assert suites == [
        {
            "name": "target100",
            "run_prefix": "20260601_ablation100_qwen9b",
            "target_per_category": 100,
            "remote_root": "/home/suraj/PIPE-Cypher-target100",
            "session": "pipecypher_ablation100_qwen9b",
        }
    ]


def test_queue_report_marks_queued_and_running_suites():
    queued = build_progress_report(
        [],
        run_prefix="20260601_ablation100_qwen9b",
        target_per_category=100,
        category_count=8,
        expected_graphs=["finbench"],
        expected_variants=["full_pipe_cypher"],
        session="target100",
        session_running=True,
    )
    queued.update(
        {
            "name": "target100",
            "remote_root": "/remote/target100",
            "configured_status": "queued",
            "generation_model": "Qwen/Qwen3.5-9B",
            "judge_model": "Qwen/Qwen3.5-9B",
            "run_seed": "17",
            "code_revision": "abc123",
            "notes": "waiting",
        }
    )
    queued["suite_state"] = infer_suite_state(queued)
    queued["next_action"] = infer_next_action(queued)
    queued["collection_command"] = build_collection_command(queued)
    running = build_progress_report(
        [
            {
                "run": "20260601_ablation50_qwen9b_snb_full_pipe_cypher",
                "records": 17,
                "summary_present": False,
            }
        ],
        run_prefix="20260601_ablation50_qwen9b",
        target_per_category=50,
        category_count=8,
        expected_graphs=["snb"],
        expected_variants=["full_pipe_cypher"],
        session="target50",
        session_running=True,
    )
    running.update(
        {
            "name": "target50",
            "remote_root": "/remote/target50",
            "configured_status": "running",
            "generation_model": "Qwen/Qwen3.5-9B",
            "judge_model": "Qwen/Qwen3.5-9B",
            "run_seed": "",
            "code_revision": "def456",
            "notes": "",
        }
    )
    running["suite_state"] = infer_suite_state(running)
    running["next_action"] = infer_next_action(running)
    running["collection_command"] = build_collection_command(running)

    report = build_queue_report([queued, running])
    text = format_queue_text(report)

    assert report["queued_or_waiting_suites"] == 1
    assert report["running_suites"] == 1
    assert queued["next_action"] == "wait_for_dependency_or_session_start"
    assert running["next_action"] == "wait_for_active_session_then_collect"
    assert "--remote-root /remote/target100" in queued["collection_command"]
    assert "--wait-session target100" in queued["collection_command"]
    assert "## target100" in text
    assert "state=queued_or_waiting configured_status=queued" in text
    assert "run_seed=17" in text
    assert "next_action=wait_for_dependency_or_session_start" in text
    assert "collection_command=python scripts/collect_remote_ablation_suite.py" in text
    assert "remote_root=/remote/target50" in text


def test_queue_report_marks_already_collected_suite_without_collection_action():
    collected = build_progress_report(
        [
            {
                "run": "20260601_ablation50_qwen9b_snb_full_pipe_cypher",
                "records": 400,
                "summary_present": True,
            }
        ],
        run_prefix="20260601_ablation50_qwen9b",
        target_per_category=50,
        category_count=8,
        expected_graphs=["snb"],
        expected_variants=["full_pipe_cypher"],
        session="target50",
        session_running=False,
    )
    collected.update(
        {
            "name": "target50",
            "remote_root": "/remote/target50",
            "configured_status": "complete_collected_paper_ready",
            "generation_model": "Qwen/Qwen3.5-9B",
            "judge_model": "Qwen/Qwen3.5-9B",
            "run_seed": "",
            "code_revision": "abc123",
            "notes": "already audited",
        }
    )
    collected["suite_state"] = infer_suite_state(collected)
    collected["next_action"] = infer_next_action(collected)
    collected["collection_command"] = build_collection_command(collected)

    report = build_queue_report([collected])
    text = format_queue_text(report)

    assert report["complete_suites"] == 1
    assert collected["suite_state"] == "complete_collected"
    assert collected["next_action"] == "no_action_required_already_collected"
    assert collected["collection_command"] == ""
    assert "state=complete_collected configured_status=complete_collected_paper_ready" in text
    assert "collection_command=not_applicable" in text
