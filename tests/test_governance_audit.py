import json

from pipecypher.governance_audit import (
    load_jsonl,
    merge_governance_audits,
    summarize_downstream_governance,
    summarize_governance_records,
)


def test_summarize_governance_records_groups_direction_schema_and_safety():
    summary = summarize_governance_records(
        [
            {
                "accepted": False,
                "graph_profile": "finbench",
                "category": "complex_aggregation",
                "question": "q",
                "cypher": "MATCH (a)<-[:TRANSFER_TO]-(b) RETURN a",
                "validation": {
                    "issues": [
                        {"level": "error", "code": "wrong_direction", "message": ""},
                        {"level": "error", "code": "unknown_property", "message": ""},
                    ]
                },
            },
            {
                "accepted": False,
                "graph_profile": "snb",
                "category": "simple_retrieval",
                "validation": {
                    "issues": [{"level": "error", "code": "not_read_only", "message": ""}]
                },
            },
        ]
    )

    assert summary["issue_groups"]["direction"] == 1
    assert summary["issue_groups"]["schema_or_value"] == 1
    assert summary["issue_groups"]["read_only_safety"] == 1
    assert summary["direction_examples"]["wrong_direction"][0]["graph_profile"] == "finbench"


def test_load_jsonl_accepts_run_directory(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "records.jsonl").write_text(
        json.dumps({"graph_profile": "finbench", "accepted": True}) + "\n",
        encoding="utf-8",
    )

    assert load_jsonl([run_dir]) == [{"graph_profile": "finbench", "accepted": True}]


def test_summarize_downstream_governance_collects_nested_issue_counts():
    summary = summarize_downstream_governance(
        {
            "total": 10,
            "incorrect": 8,
            "top_predicted_issue_codes": {},
            "by_category": {
                "ranking": {"top_predicted_issue_codes": {"wrong_direction": 2, "syntax_shape": 3}},
            },
        }
    )

    assert summary["issue_counts"]["wrong_direction"] == 2
    assert summary["issue_counts"]["syntax_shape"] == 3
    assert summary["issue_groups"]["direction"] == 2
    assert summary["issue_groups"]["syntax_or_parser"] == 3


def test_summarize_downstream_governance_uses_top_level_without_double_counting():
    summary = summarize_downstream_governance(
        {
            "top_predicted_issue_codes": {"wrong_direction": 2},
            "by_category": {
                "ranking": {"top_predicted_issue_codes": {"wrong_direction": 2}},
            },
        }
    )

    assert summary["issue_counts"]["wrong_direction"] == 2


def test_merge_governance_audits_combines_issue_groups():
    merged = merge_governance_audits(
        generation_records={"issue_counts": {"wrong_direction": 1}},
        ablation={"issue_counts": {"unknown_property": 2}},
        downstream={"issue_counts": {"not_read_only": 3}},
    )

    assert merged["combined_issue_counts"]["wrong_direction"] == 1
    assert merged["combined_issue_groups"]["direction"] == 1
    assert merged["combined_issue_groups"]["schema_or_value"] == 2
    assert merged["combined_issue_groups"]["read_only_safety"] == 3
