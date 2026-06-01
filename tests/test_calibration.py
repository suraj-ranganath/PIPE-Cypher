import csv
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


def test_sample_for_audit_covers_graph_category_judge_strata():
    records = []
    for graph in ["finbench", "snb"]:
        for category in ["simple", "ranking"]:
            for accepted in [True, False]:
                records.append(
                    {
                        "accepted": accepted,
                        "graph_profile": graph,
                        "category": category,
                        "question": f"{graph}-{category}-{accepted}",
                        "cypher": "MATCH (n) RETURN n",
                    }
                )

    sample = sample_for_audit(records, n=8, seed=1)
    strata = {
        (row["graph_profile"], row["category"], row["accepted"])
        for row in sample
    }

    assert len(sample) == 8
    assert len(strata) == 8


def test_sample_for_audit_preserves_accept_reject_balance_when_stratified():
    records = []
    for idx in range(80):
        records.append(
            {
                "accepted": True,
                "graph_profile": "finbench" if idx % 2 else "snb",
                "category": f"cat{idx % 4}",
                "question": f"a{idx}",
                "cypher": "MATCH (n) RETURN n",
            }
        )
    for idx in range(30):
        records.append(
            {
                "accepted": False,
                "graph_profile": "finbench" if idx % 2 else "snb",
                "category": f"cat{idx % 4}",
                "question": f"r{idx}",
                "cypher": "MATCH (n) RETURN n",
            }
        )

    sample = sample_for_audit(records, n=40, seed=3)

    assert len(sample) == 40
    assert sum(1 for row in sample if row["accepted"]) == 20
    assert sum(1 for row in sample if not row["accepted"]) == 20


def test_analyze_audit_csv(tmp_path: Path):
    records = [
        {"accepted": True, "question": "q1", "cypher": "MATCH (n) RETURN n"},
        {"accepted": False, "question": "q2", "cypher": "MATCH (n) RETURN n"},
    ]
    path = tmp_path / "audit.csv"
    write_audit_csv(records, path)
    rows = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames
    rows[0]["human_accept"] = "true"
    rows[1]["human_accept"] = "true"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    metrics = analyze_audit_csv(path)
    assert metrics.total_labeled == 2
    assert metrics.false_rejects == 1
    assert metrics.true_accepts == 1
    assert metrics.true_rejects == 0
    assert metrics.judge_precision == 1.0
    assert metrics.judge_recall == 0.5
    assert metrics.balanced_accuracy == 0.0


def test_summarize_audit_csv_reports_label_coverage(tmp_path: Path):
    path = tmp_path / "audit.csv"
    path.write_text(
        "id,graph_profile,judge_accept,human_accept,category,difficulty,primary_strategy,question,cypher,judge_failure_reason,human_notes\n"
        "0,finbench,true,true,simple,easy,single_hop,q,c,,\n"
        "1,snb,false,,negation,medium,negation,q,c,failed,\n",
        encoding="utf-8",
    )

    coverage = summarize_audit_csv(path)

    assert coverage.total_rows == 2
    assert coverage.labeled_rows == 1
    assert coverage.unlabeled_rows == 1
    assert coverage.judge_accepts == 1
    assert coverage.judge_rejects == 1
    assert coverage.by_graph == {"finbench": 1, "snb": 1}
    assert coverage.by_category == {"negation": 1, "simple": 1}
