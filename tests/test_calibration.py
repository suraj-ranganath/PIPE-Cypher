from pathlib import Path

from pipecypher.calibration import (
    analyze_audit_csv,
    sample_for_audit,
    summarize_audit_csv,
    write_audit_csv,
)


def test_sample_for_audit_balances_when_possible():
    records = [{"accepted": True, "question": f"a{i}"} for i in range(5)] + [
        {"accepted": False, "question": f"r{i}"} for i in range(5)
    ]
    sample = sample_for_audit(records, n=6, seed=1)
    assert len(sample) == 6
    assert any(row["accepted"] for row in sample)
    assert any(not row["accepted"] for row in sample)


def test_sample_for_audit_dedupes_repeated_candidates():
    records = [
        {"accepted": False, "category": "simple", "question": "q", "cypher": "MATCH (n) RETURN n"}
        for _ in range(5)
    ]
    records.append(
        {"accepted": True, "category": "simple", "question": "q2", "cypher": "MATCH (n) RETURN n"}
    )

    sample = sample_for_audit(records, n=6, seed=1)

    assert len(sample) == 2


def test_analyze_audit_csv(tmp_path: Path):
    records = [
        {"accepted": True, "question": "q1", "cypher": "MATCH (n) RETURN n"},
        {"accepted": False, "question": "q2", "cypher": "MATCH (n) RETURN n"},
    ]
    path = tmp_path / "audit.csv"
    write_audit_csv(records, path)
    text = path.read_text(encoding="utf-8")
    text = text.replace("true,", "true,true,", 1)
    text = text.replace("false,", "false,true,", 1)
    path.write_text(text, encoding="utf-8")
    metrics = analyze_audit_csv(path)
    assert metrics.total_labeled == 2
    assert metrics.false_rejects == 1
    assert metrics.judge_precision == 1.0


def test_summarize_audit_csv_reports_label_coverage(tmp_path: Path):
    path = tmp_path / "audit.csv"
    path.write_text(
        "id,judge_accept,human_accept,category,difficulty,primary_strategy,question,cypher,judge_failure_reason,human_notes\n"
        "0,true,true,simple,easy,single_hop,q,c,,\n"
        "1,false,,negation,medium,negation,q,c,failed,\n",
        encoding="utf-8",
    )

    coverage = summarize_audit_csv(path)

    assert coverage.total_rows == 2
    assert coverage.labeled_rows == 1
    assert coverage.unlabeled_rows == 1
    assert coverage.judge_accepts == 1
    assert coverage.judge_rejects == 1
    assert coverage.by_category == {"negation": 1, "simple": 1}
