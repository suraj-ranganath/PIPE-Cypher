from pipecypher.evaluation import answer_rows_to_text, answer_set_scores, summarize_evaluation_rows


def test_answer_set_scores_exact():
    scores = answer_set_scores([{"a": 1}], [{"a": 1}])
    assert scores.exact
    assert scores.f1 == 1.0


def test_answer_set_scores_partial():
    scores = answer_set_scores([{"a": 1}, {"a": 2}], [{"a": 1}, {"a": 3}])
    assert not scores.exact
    assert scores.precision == 0.5
    assert scores.recall == 0.5
    assert scores.f1 == 0.5


def test_answer_set_scores_ignores_single_scalar_alias():
    scores = answer_set_scores([{"count": 3}], [{"PostCount": 3}])
    assert scores.exact
    assert scores.f1 == 1.0


def test_answer_rows_to_text_serializes_result_sets_stably():
    text = answer_rows_to_text([{"b": 2, "a": 1}, {"count": 3}])
    assert text == "_scalar=3 | a=1; b=2"


def test_summarize_evaluation_rows_groups_core_metrics():
    rows = [
        {
            "graph_profile": "finbench",
            "category": "simple_retrieval",
            "difficulty": "easy",
            "parse_valid": True,
            "schema_valid": True,
            "read_only": True,
            "execution_success": True,
            "execution_accuracy": True,
            "answer_f1": 1.0,
            "answer_text_rougeL_f1": 1.0,
            "query_text_bleu": 0.8,
        },
        {
            "graph_profile": "finbench",
            "category": "ranking_topk",
            "difficulty": "medium",
            "parse_valid": True,
            "schema_valid": False,
            "read_only": True,
            "execution_success": False,
            "execution_accuracy": False,
            "answer_f1": 0.0,
            "answer_text_rougeL_f1": 0.0,
            "query_text_bleu": 0.2,
        },
    ]
    summary = summarize_evaluation_rows(rows)
    assert summary["overall"]["n"] == 2
    assert summary["overall"]["execution_accuracy"] == 0.5
    assert summary["by_graph"]["finbench"]["answer_f1"] == 0.5
    assert summary["overall"]["answer_text_rougeL_f1"] == 0.5
    assert summary["overall"]["query_text_bleu"] == 0.5
    assert summary["by_category"]["ranking_topk"]["schema_valid"] == 0.0
