from pipecypher.fewshot_audit import (
    audit_fewshot_leakage,
    build_fewshot_leakage_control_report,
    render_fewshot_leakage_control_latex,
    render_fewshot_leakage_latex,
)
from pipecypher.text2cypher import choose_few_shots, selection_metadata


def test_fewshot_leakage_audit_counts_signature_and_similarity_risks():
    train = [
        {
            "id": "train_same_sig",
            "graph_profile": "finbench",
            "category": "simple_retrieval",
            "question": "List accounts owned by Alice.",
            "cypher": "MATCH (a:Account) RETURN DISTINCT a.accountId",
        },
        {
            "id": "train_near",
            "graph_profile": "finbench",
            "category": "simple_retrieval",
            "question": "Which account has the most transfers?",
            "cypher": "MATCH (a:Account) RETURN DISTINCT a.status",
        },
    ]
    test = [
        {
            "id": "test_1",
            "graph_profile": "finbench",
            "category": "simple_retrieval",
            "question": "Which account has the most transfers",
            "cypher": "MATCH (x:Account) RETURN DISTINCT x.accountId",
        }
    ]
    selected = choose_few_shots(train, current=test[0], k=2, mode="ordered_same_category")
    report = audit_fewshot_leakage(
        train_rows=train,
        test_rows=test,
        selection_rows=[selection_metadata(current=test[0], selected=selected)],
        high_similarity_threshold=0.90,
    )

    assert report["train_test_overlap"]["query_signature_count"] == 1
    assert report["selected_examples"]["query_signature_match_count"] == 1
    assert report["selected_examples"]["high_question_similarity_count"] == 1
    assert report["risk_examples"][0]["id"] == "test_1"

    tex = render_fewshot_leakage_latex(report)
    assert r"\label{tab:fewshot_leakage_audit}" in tex
    assert "Selected signature matches" in tex


def test_fewshot_leakage_control_report_renders_modes():
    base_report = {
        "selection_rows": 2,
        "high_similarity_threshold": 0.90,
        "train_test_overlap": {
            "exact_question_count": 0,
            "query_signature_count": 1,
        },
        "selected_examples": {
            "total_selected": 10,
            "query_signature_match_rate": 0.5,
            "high_question_similarity_rate": 0.2,
            "mean_question_similarity": 0.7,
            "max_question_similarity": 0.9,
        },
    }
    report = build_fewshot_leakage_control_report(
        {
            "ordered": base_report,
            "scored no-sig": {
                **base_report,
                "selected_examples": {
                    **base_report["selected_examples"],
                    "query_signature_match_rate": 0.0,
                },
            },
        }
    )

    assert report["modes"][0]["mode"] == "ordered"
    assert report["modes"][1]["signature_match_rate"] == 0.0
    tex = render_fewshot_leakage_control_latex(report)
    assert r"\label{tab:fewshot_leakage_controls}" in tex
    assert "scored no-sig" in tex
