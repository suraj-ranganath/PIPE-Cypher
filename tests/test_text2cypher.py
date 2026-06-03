from pipecypher.graph_profiles import finbench_reference_schema
from pipecypher.llm import ChatResponse
from pipecypher.text2cypher import (
    build_text2cypher_prompt,
    choose_few_shots,
    clean_predicted_cypher,
    predict_text2cypher,
    selection_metadata,
)


class FakeLLM:
    model = "fake-model"

    def chat(self, **kwargs):
        assert "Question:" in kwargs["user"]
        return ChatResponse(
            text="```cypher\nMATCH (p:Person) RETURN DISTINCT p.personName AS PersonName;\n```",
            raw={},
        )


def test_clean_predicted_cypher_strips_fences_prefix_and_semicolon():
    assert (
        clean_predicted_cypher("Cypher: ```cypher\nMATCH (n) RETURN n;\n```")
        == "MATCH (n) RETURN n"
    )


def test_clean_predicted_cypher_strips_inline_response_marker():
    assert (
        clean_predicted_cypher(
            "- Do not include markdown or explanations.\n\nResponse: MATCH (n) RETURN n;"
        )
        == "MATCH (n) RETURN n"
    )


def test_build_prompt_includes_schema_and_rules():
    prompt = build_text2cypher_prompt(
        question="Which accounts are owned by person 'Alice'?",
        schema=finbench_reference_schema(),
        schema_max_items=20,
    )
    assert "Graph schema:" in prompt
    assert "RETURN DISTINCT" in prompt
    assert "Alice" in prompt


def test_build_prompt_includes_few_shot_examples_when_supplied():
    prompt = build_text2cypher_prompt(
        question="List blocked accounts.",
        schema=finbench_reference_schema(),
        schema_max_items=20,
        few_shot_examples=[
            {
                "question": "Which accounts does person 'Alice' own?",
                "cypher": "MATCH (p:Person {personName: 'Alice'})-[:OWN_ACCOUNT]->(a:Account) RETURN DISTINCT a.accountId AS AccountId",
            }
        ],
    )

    assert "Examples:" in prompt
    assert "Which accounts does person" in prompt
    assert "OWN_ACCOUNT" in prompt


def test_choose_few_shots_prefers_same_graph_and_category():
    current = {"id": "c", "graph_profile": "finbench", "category": "ranking_topk"}
    examples = [
        {"id": "a", "graph_profile": "finbench", "category": "simple_retrieval"},
        {"id": "b", "graph_profile": "finbench", "category": "ranking_topk"},
        {"id": "c", "graph_profile": "finbench", "category": "ranking_topk"},
    ]
    shots = choose_few_shots(examples, current=current, k=2)
    assert [shot["id"] for shot in shots] == ["b", "a"]
    assert shots[0]["few_shot_mode"] == "ordered_same_category"


def test_choose_few_shots_random_mode_is_seeded():
    current = {"id": "c", "graph_profile": "finbench", "category": "ranking_topk"}
    examples = [
        {"id": str(idx), "graph_profile": "finbench", "category": "ranking_topk"}
        for idx in range(8)
    ]

    first = choose_few_shots(examples, current=current, k=3, mode="random_same_category", seed=17)
    second = choose_few_shots(examples, current=current, k=3, mode="random_same_category", seed=17)

    assert [row["id"] for row in first] == [row["id"] for row in second]
    assert all(row["few_shot_seed"] == 17 for row in first)


def test_choose_few_shots_scored_mode_excludes_signature_and_near_question():
    current = {
        "id": "c",
        "graph_profile": "finbench",
        "category": "ranking_topk",
        "question": "Which account has the most transfers?",
        "cypher": "MATCH (a:Account)-[:TRANSFER]->() RETURN DISTINCT a.accountId LIMIT 1",
    }
    examples = [
        {
            "id": "same_sig",
            "graph_profile": "finbench",
            "category": "ranking_topk",
            "question": "Which account has the most outgoing transfers?",
            "cypher": "MATCH (x:Account)-[:TRANSFER]->() RETURN DISTINCT x.accountId LIMIT 1",
        },
        {
            "id": "near_question",
            "graph_profile": "finbench",
            "category": "ranking_topk",
            "question": "Which account has the most transfers",
            "cypher": "MATCH (a:Account) RETURN DISTINCT a.accountId",
        },
        {
            "id": "kept",
            "graph_profile": "finbench",
            "category": "simple_retrieval",
            "question": "List blocked accounts.",
            "cypher": "MATCH (a:Account) WHERE a.isBlocked = true RETURN DISTINCT a.accountId",
        },
    ]

    shots = choose_few_shots(
        examples,
        current=current,
        k=3,
        mode="scored_no_signature",
        max_question_similarity=0.90,
        exclude_signature_match=True,
    )

    assert [shot["id"] for shot in shots] == ["kept"]
    assert shots[0]["few_shot_mode"] == "scored_no_signature"
    metadata = selection_metadata(current=current, selected=shots)
    assert metadata["selected"][0]["id"] == "kept"
    assert metadata["selected"][0]["query_signature_match"] is False


def test_predict_text2cypher_returns_prediction_dataclass():
    prediction = predict_text2cypher(
        llm=FakeLLM(),
        example={
            "id": "ex1",
            "question": "List people",
            "graph_profile": "finbench",
            "category": "simple_retrieval",
            "difficulty": "easy",
            "cypher": "MATCH (p:Person) RETURN DISTINCT p.personName AS PersonName",
        },
        schema=finbench_reference_schema(),
    )
    assert prediction.id == "ex1"
    assert prediction.model == "fake-model"
    assert prediction.predicted_cypher == "MATCH (p:Person) RETURN DISTINCT p.personName AS PersonName"
