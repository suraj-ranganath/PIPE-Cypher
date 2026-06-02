import subprocess
import sys
import csv
from pathlib import Path

from pipecypher.judge_audit_packet import (
    audit_packet_snapshot,
    load_audit_rows,
    render_audit_html,
    write_annotation_sheets,
)


def _write_audit(path: Path, rows: int = 4) -> None:
    lines = [
        "id,graph_profile,judge_accept,human_accept,category,difficulty,primary_strategy,question,cypher,judge_failure_reason,human_notes"
    ]
    for idx in range(rows):
        graph = "finbench" if idx % 2 == 0 else "snb"
        judge = "true" if idx % 2 == 0 else "false"
        lines.append(
            f"{idx},{graph},{judge},,category_{idx % 2},easy,single_hop,"
            f"Question {idx}?,MATCH (n) RETURN n,reason {idx},"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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


def test_write_annotation_sheets_preserves_rows_without_filling_labels(tmp_path: Path):
    audit = tmp_path / "audit.csv"
    _write_audit(audit, rows=5)

    manifest = write_annotation_sheets(
        audit,
        tmp_path / "sheets",
        prefix="audit_v2",
        annotators=("annotator_a", "annotator_b"),
        seed=3,
    )

    assert manifest["row_count"] == 5
    assert manifest["label_status"] == "unlabeled"
    assert manifest["ready_for_calibration"] is False
    assert len(manifest["annotator_sheets"]) == 2
    assert len(manifest["adjudication_template"]["sha256"]) == 64

    original_ids = {str(idx) for idx in range(5)}
    sheet_path = Path(manifest["annotator_sheets"][0]["path"])
    with sheet_path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    assert {row["id"] for row in rows} == original_ids
    assert all(row["human_accept"] == "" for row in rows)
    assert all(row["human_notes"] == "" for row in rows)
    assert all(row["review_order"] for row in rows[1:])


def test_write_annotation_sheets_can_blind_judge_decisions(tmp_path: Path):
    audit = tmp_path / "audit.csv"
    _write_audit(audit, rows=2)

    manifest = write_annotation_sheets(
        audit,
        tmp_path / "sheets",
        include_judge_accept=False,
    )

    sheet_path = Path(manifest["annotator_sheets"][0]["path"])
    adjudication_path = Path(manifest["adjudication_template"]["path"])
    with sheet_path.open("r", encoding="utf-8", newline="") as f:
        sheet_header = next(csv.reader(f))
    with adjudication_path.open("r", encoding="utf-8", newline="") as f:
        adjudication_header = next(csv.reader(f))

    assert "judge_accept" not in sheet_header
    assert "judge_accept" not in adjudication_header
    assert manifest["include_judge_accept"] is False


def test_create_judge_annotation_sheets_cli_writes_manifest(tmp_path: Path):
    audit = tmp_path / "audit.csv"
    manifest = tmp_path / "manifest.json"
    _write_audit(audit, rows=3)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/create_judge_annotation_sheets.py",
            "--audit",
            str(audit),
            "--output-dir",
            str(tmp_path / "sheets"),
            "--prefix",
            "audit",
            "--manifest-json",
            str(manifest),
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert manifest.exists()
    assert '"row_count": 3' in manifest.read_text(encoding="utf-8")
    assert "wrote" in result.stdout


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
