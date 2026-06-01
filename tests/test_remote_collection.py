from __future__ import annotations

from pathlib import Path

from pipecypher.remote_collection import (
    build_collection_manifest,
    build_remote_find_runs_command,
    build_rsync_run_command,
    build_summary_metadata,
    build_tmux_has_session_command,
    parse_run_log_metadata,
)


def test_parse_run_log_metadata_reads_first_header_values():
    metadata = parse_run_log_metadata(
        "\n".join(
            [
                "run_prefix=20260601_ablation50_qwen9b",
                "target_per_category=50",
                "generation_model=Qwen/Qwen3.5-9B",
                "judge_model=Qwen/Qwen3.5-9B",
                "code_revision=b5d4898",
                "run graph=finbench variant=reverse_only",
                "code_revision=later_should_not_override",
            ]
        )
    )

    assert metadata == {
        "run_prefix": "20260601_ablation50_qwen9b",
        "target_per_category": "50",
        "generation_model": "Qwen/Qwen3.5-9B",
        "judge_model": "Qwen/Qwen3.5-9B",
        "code_revision": "b5d4898",
    }


def test_build_remote_find_runs_command_quotes_prefix():
    command = build_remote_find_runs_command(
        remote_root="/home/suraj/PIPE-Cypher",
        run_prefix="20260601_ablation50_qwen9b",
    )

    assert command.startswith("cd /home/suraj/PIPE-Cypher && find artifacts/runs")
    assert "-name '*20260601_ablation50_qwen9b*'" in command


def test_build_tmux_has_session_command_quotes_session():
    assert (
        build_tmux_has_session_command("pipecypher_ablation50_qwen9b")
        == "tmux has-session -t pipecypher_ablation50_qwen9b"
    )
    assert (
        build_tmux_has_session_command("session with spaces")
        == "tmux has-session -t 'session with spaces'"
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
