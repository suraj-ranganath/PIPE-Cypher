import subprocess
import sys
from pathlib import Path

from pipecypher.judge_audit_packet import audit_packet_snapshot, load_audit_rows, render_audit_html


def test_audit_packet_snapshot_hashes_and_summarizes_csv(tmp_path: Path):
    audit = tmp_path / "audit.csv"
    audit.write_text(
        "id,graph_profile,judge_accept,human_accept,category,difficulty,primary_strategy,question,cypher,judge_failure_reason,human_notes\n"
        "0,finbench,true,true,simple,easy,single_hop,Question?,MATCH (n) RETURN n,,ok\n"
        "1,snb,false,,ranking,medium,order_rank,Question 2?,MATCH (n) RETURN n,bad,\n",
        encoding="utf-8",
    )

    rows = load_audit_rows(audit)
    snapshot = audit_packet_snapshot(audit, html_path="audit.html")

    assert len(rows) == 2
    assert len(snapshot["audit_sha256"]) == 64
    assert snapshot["html_packet"] == "audit.html"
    assert snapshot["coverage"]["total_rows"] == 2
    assert snapshot["coverage"]["labeled_rows"] == 1
    assert snapshot["label_completion_rate"] == 0.5
    assert snapshot["metrics"]["total_labeled"] == 1
    assert snapshot["ready_for_calibration"] is False
    assert snapshot["partial_labels_present"] is True
    assert snapshot["label_status"] == "partial"


def test_audit_packet_snapshot_requires_complete_labels_for_calibration(tmp_path: Path):
    audit = tmp_path / "audit.csv"
    audit.write_text(
        "id,graph_profile,judge_accept,human_accept,category,difficulty,primary_strategy,question,cypher,judge_failure_reason,human_notes\n"
        "0,finbench,true,true,simple,easy,single_hop,Question?,MATCH (n) RETURN n,,ok\n"
        "1,snb,false,false,ranking,medium,order_rank,Question 2?,MATCH (n) RETURN n,bad,ok\n",
        encoding="utf-8",
    )

    snapshot = audit_packet_snapshot(audit)

    assert snapshot["coverage"]["labeled_rows"] == 2
    assert snapshot["coverage"]["unlabeled_rows"] == 0
    assert snapshot["label_completion_rate"] == 1.0
    assert snapshot["ready_for_calibration"] is True
    assert snapshot["partial_labels_present"] is False
    assert snapshot["label_status"] == "complete"


def test_render_audit_html_escapes_values_and_includes_download(tmp_path: Path):
    audit = tmp_path / "audit.csv"
    audit.write_text(
        "id,graph_profile,judge_accept,human_accept,category,difficulty,primary_strategy,question,cypher,judge_failure_reason,human_notes\n"
        "0,finbench,true,,simple,easy,single_hop,<Question?>,MATCH (n) RETURN n,<bad>,\n",
        encoding="utf-8",
    )

    html = render_audit_html(audit, title="Audit <Packet>")

    assert "Audit &lt;Packet&gt;" in html
    assert "&lt;Question?&gt;" in html
    assert "&lt;bad&gt;" in html
    assert "Download labels CSV" in html
    assert "human_accept_0" in html
    assert "--require-complete-labels" in html


def test_render_audit_html_uses_safe_dom_id_without_losing_original_id(tmp_path: Path):
    audit = tmp_path / "audit.csv"
    audit.write_text(
        "id,graph_profile,judge_accept,human_accept,category,difficulty,primary_strategy,question,cypher,judge_failure_reason,human_notes\n"
        '"row[1]",finbench,true,,simple,easy,single_hop,Question?,MATCH (n) RETURN n,,\n',
        encoding="utf-8",
    )

    html = render_audit_html(audit)

    assert '"id": "row[1]"' in html
    assert "human_accept_row[1]" not in html
    assert "human_accept_row_" in html


def test_analyze_judge_audit_cli_can_require_complete_labels(tmp_path: Path):
    audit = tmp_path / "audit.csv"
    audit.write_text(
        "id,graph_profile,judge_accept,human_accept,category,difficulty,primary_strategy,question,cypher,judge_failure_reason,human_notes\n"
        "0,finbench,true,true,simple,easy,single_hop,Question?,MATCH (n) RETURN n,,ok\n"
        "1,snb,false,,ranking,medium,order_rank,Question 2?,MATCH (n) RETURN n,bad,\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/analyze_judge_audit.py",
            "--audit",
            str(audit),
            "--require-complete-labels",
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "1/2 rows labeled" in result.stderr
