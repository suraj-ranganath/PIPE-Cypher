from pipecypher.graph_profiles import finbench_reference_schema
from pipecypher.llm import ChatResponse
from pipecypher.text2cypher import (
    build_text2cypher_prompt,
    choose_few_shots,
    clean_predicted_cypher,
    predict_text2cypher,
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
