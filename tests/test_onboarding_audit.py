from __future__ import annotations

import json
from pathlib import Path

from pipecypher.onboarding_audit import (
    build_onboarding_collection_manifest,
    redact_runtime_log,
    render_onboarding_summary_markdown,
    summarize_onboarding_records_path,
)


def _record(
    *,
    category: str,
    accepted: bool,
    failure_reason: str = "",
    template_metadata: dict | None = None,
) -> dict:
    return {
        "question": "Which entity has private literal ACME-123?",
        "cypher": "MATCH (n:Entity {name: 'ACME-123'}) RETURN DISTINCT n.name",
        "category": category,
        "graph_profile": "enterprise",
        "accepted": accepted,
        "validation": {
            "read_only": True,
            "syntax_valid": True,
            "schema_valid": True,
            "structural_features": {"difficulty": "complex"},
            "issues": [],
        },
        "execution": {"success": accepted, "rows": [{"name": "ACME-123"}] if accepted else []},
        "judge": {"passed": accepted, "failure_reason": failure_reason},
        "template_metadata": template_metadata or {},
    }


def test_onboarding_summary_is_aggregate_only_and_blocks_incomplete_categories(tmp_path: Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    records = [
        _record(
            category="ranking_topk",
            accepted=True,
            template_metadata={"schema_template_kind": "topk_outgoing"},
        ),
        _record(category="ranking_topk", accepted=False, failure_reason="slot bindings exhausted"),
    ]
    (run_dir / "records.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in records),
        encoding="utf-8",
    )
    (run_dir / "summary.txt").write_text("accepted=1\n", encoding="utf-8")

    summary = summarize_onboarding_records_path(
        run_dir,
        target_per_category=50,
        expected_categories=["ranking_topk", "negation_difference"],
        graph_profile="enterprise",
        metadata={
            "generation_model": "Qwen/Qwen3.5-9B",
            "judge_model": "Qwen/Qwen3.5-9B",
            "code_revision": "abc123",
            "run_seed": "7",
        },
    )
    markdown = render_onboarding_summary_markdown(summary)

    assert summary["accepted_by_category"] == {"ranking_topk": 1}
    assert summary["schema_template_accepts_by_category"] == {"ranking_topk": 1}
    assert not summary["audit"]["ready_for_paper_promotion"]
    assert "categories below target: ranking_topk, negation_difference" in summary["audit"]["issues"]
    assert "ACME-123" not in json.dumps(summary)
    assert "ACME-123" not in markdown


def test_onboarding_collection_manifest_hashes_snapshot_files(tmp_path: Path):
    snapshot_dir = tmp_path / "snapshot"
    run_root = tmp_path / "runs"
    run_name = "20260602_192926_icij_target100"
    run_dir = run_root / run_name
    run_dir.mkdir(parents=True)
    snapshot_dir.mkdir(parents=True)
    (run_dir / "records.jsonl").write_text('{"accepted": true}\n', encoding="utf-8")
    (run_dir / "summary.txt").write_text("accepted=1\n", encoding="utf-8")
    (snapshot_dir / "onboarding_summary.json").write_text("{}\n", encoding="utf-8")
    (snapshot_dir / "onboarding_summary.md").write_text("# Summary\n", encoding="utf-8")
    (snapshot_dir / "remote_run.log").write_text("run_prefix=icij\n", encoding="utf-8")

    manifest = build_onboarding_collection_manifest(
        host="suraj@ds-serv6.ucsd.edu",
        remote_root="/remote",
        run_prefix="icij",
        snapshot_dir=snapshot_dir,
        local_run_root=run_root,
        run_name=run_name,
        metadata={"code_revision": "abc123"},
        log_file="logs/icij.log",
        collected_at="2026-06-02T00:00:00+00:00",
    )

    assert manifest["run_name"] == run_name
    assert manifest["snapshot_files"]["onboarding_summary.json"]["bytes"] == 3
    assert len(manifest["runs"][run_name]["records.jsonl"]["sha256"]) == 64


def test_redact_runtime_log_removes_value_bearing_cypher():
    text = (
        "warning for query: \"MATCH (e:Entity {name: 'PRIVATE CO.'}) "
        "RETURN DISTINCT e.name\" and cypher=\"MATCH (n {id: '123'}) RETURN n\""
    )

    redacted = redact_runtime_log(text)

    assert "PRIVATE CO." not in redacted
    assert "MATCH (e:Entity" not in redacted
    assert "123" not in redacted
    assert "[REDACTED_CYPHER]" in redacted
