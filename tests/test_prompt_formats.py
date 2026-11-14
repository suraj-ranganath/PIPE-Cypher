from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from pipecypher import prompt_formats as pf
from pipecypher.llm import ChatResponse, OpenAICompatibleLLM
from pipecypher.models import SchemaSummary
from pipecypher.text2cypher import (
    TEXT2CYPHER_SYSTEM,
    build_text2cypher_prompt,
    predict_text2cypher,
    prediction_to_dict,
)
from pipecypher.validator import CONTEXTUAL_RETURN_PROPERTIES, RESERVED_VARIABLES, WRITE_TOKENS

ROOT = Path(__file__).resolve().parents[1]
FINBENCH = SchemaSummary.from_dict(
    json.loads((ROOT / "configs/schema_finbench.json").read_text(encoding="utf-8"))
)
SNB = SchemaSummary.from_dict(json.loads((ROOT / "configs/schema_snb.json").read_text(encoding="utf-8")))
FEW_SHOTS = [
    {
        "id": "ex_a",
        "question": "Which accounts does person 'Alice' own?",
        "cypher": "MATCH (p:Person {personName: 'Alice'})-[:OWN_ACCOUNT]->(a:Account) RETURN DISTINCT a.accountId",
    }
]
EXAMPLE = {
    "id": "q1",
    "question": "Which accounts does person 'Bob' own?",
    "graph_profile": "finbench",
    "category": "simple_retrieval",
    "difficulty": "easy",
    "cypher": "MATCH (p:Person {personName: 'Bob'})-[:OWN_ACCOUNT]->(a:Account) RETURN DISTINCT a.accountId",
}

# Frozen copy of the historical prompt so any edit to TEXT2CYPHER_PROMPT that
# would silently change old runs fails here.
HISTORICAL_PIPE_STANDARD_USER = """Graph schema:
(:A)-[:R]->(:B)

Examples:
Question: Which accounts does person 'Alice' own?
Cypher: MATCH (p:Person {personName: 'Alice'})-[:OWN_ACCOUNT]->(a:Account) RETURN DISTINCT a.accountId


Question:
Who?

Rules:
- Use only labels, relationship types, properties, and relationship directions in the schema.
- Preserve relationship direction exactly as listed.
- Use exact equality for quoted values.
- All set-returning RETURN clauses must use RETURN DISTINCT.
- For counts, use COUNT(DISTINCT variable).
- For top-k/ranking, use ORDER BY plus LIMIT.
- For yes/no questions, return a boolean expression with a clear alias.
- Do not use CREATE, MERGE, DELETE, SET, REMOVE, LOAD CSV, APOC writes, or admin calls.
- Return only the Cypher query."""


def _render(name: str, *, schema: SchemaSummary = FINBENCH, few_shots=None, question="Who owns 'X'?"):
    return pf.render_prompt(
        name,
        schema_text=schema.to_prompt(max_items=70),
        question=question,
        few_shot_examples=few_shots,
        schema=schema,
    )


class RecordingLLM:
    model = "fake-model"
    system_message_mode = "separate"

    def __init__(self):
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return ChatResponse(text="MATCH (a:Account) RETURN DISTINCT a.accountId", raw={})


# ---------------------------------------------------------------------------
# pipe_standard reproduces the historical prompt byte for byte
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("few_shots", [None, FEW_SHOTS])
def test_pipe_standard_is_byte_identical_to_build_text2cypher_prompt(few_shots):
    for schema in (FINBENCH, SNB):
        rendered = _render("pipe_standard", schema=schema, few_shots=few_shots)
        expected = build_text2cypher_prompt(
            question="Who owns 'X'?",
            schema=schema,
            schema_max_items=70,
            few_shot_examples=few_shots,
        )
        assert rendered.user == expected
        assert rendered.system == TEXT2CYPHER_SYSTEM
        assert rendered.transport == "chat"
        assert tuple(rendered) == (TEXT2CYPHER_SYSTEM, expected)


def test_pipe_standard_matches_frozen_historical_text():
    rendered = pf.render_prompt(
        "pipe_standard",
        schema_text="(:A)-[:R]->(:B)",
        question="Who?",
        few_shot_examples=FEW_SHOTS,
    )
    assert rendered.user == HISTORICAL_PIPE_STANDARD_USER
    assert rendered.system == (
        "You are an expert Text2Cypher system for enterprise property graphs. "
        "Return only one read-only Cypher query. Do not include markdown or explanations."
    )


def test_predict_pipe_standard_sends_historical_chat_and_hashes_sent_messages():
    llm = RecordingLLM()
    prediction = predict_text2cypher(llm=llm, example=EXAMPLE, schema=FINBENCH, schema_max_items=70)
    expected_user = build_text2cypher_prompt(
        question=EXAMPLE["question"], schema=FINBENCH, schema_max_items=70
    )
    assert llm.calls == [
        {"system": TEXT2CYPHER_SYSTEM, "user": expected_user, "temperature": 0.0, "max_tokens": 512}
    ]
    messages = [
        {"role": "system", "content": TEXT2CYPHER_SYSTEM},
        {"role": "user", "content": expected_user},
    ]
    canonical = json.dumps({"messages": messages}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert prediction.prompt_sha256 == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    row = prediction_to_dict(prediction)
    assert row["prompt_format"] == "pipe_standard"
    assert row["prompt_transport"] == "chat"
    assert row["system_message_mode"] == "separate"


def test_prompt_hash_tracks_system_message_merging():
    rendered = _render("pipe_standard")
    assert rendered.sha256("separate") != rendered.sha256("merge")
    merged = rendered.messages("merge")
    assert len(merged) == 1 and merged[0]["role"] == "user"
    assert TEXT2CYPHER_SYSTEM in merged[0]["content"]


# ---------------------------------------------------------------------------
# pipe_governed is derived from validator constants, not hand-copied
# ---------------------------------------------------------------------------


def test_pipe_governed_extends_standard_with_contextual_rules_from_validator():
    standard = _render("pipe_standard")
    governed = _render("pipe_governed")
    assert governed.system == standard.system
    assert governed.user.startswith(standard.user)
    added = governed.user[len(standard.user) :]
    assert pf.GOVERNED_CONVENTIONS_HEADER in added
    for label, rules in CONTEXTUAL_RETURN_PROPERTIES.items():
        props = FINBENCH.properties_for_label(label)
        for trigger, required in rules.items():
            if trigger not in props:
                assert f":{label}.{trigger}" not in added
                continue
            assert f"RETURN projects :{label}.{trigger}" in added
            for prop in required:
                if prop in props:
                    assert f":{label}.{prop}" in added
                else:
                    assert f":{label}.{prop}" not in added
    for token in WRITE_TOKENS:
        assert token in added
    for variable in RESERVED_VARIABLES:
        assert variable in added
    for key in FINBENCH.categorical_properties:
        assert f":{key}" in added
    assert "explicit direction" in added
    assert "character for character" in added


def test_pipe_governed_follows_validator_constant_changes(monkeypatch):
    monkeypatch.setitem(pf.CONTEXTUAL_RETURN_PROPERTIES, "Account", {"accountId": ("nickname",)})
    monkeypatch.setattr(pf, "WRITE_TOKENS", (*WRITE_TOKENS, "CALL SNEAKY.WRITE"))
    text = pf.governed_conventions_block(None)
    assert ":Account.nickname" in text
    assert "CALL SNEAKY.WRITE" in text
    assert ":Account.accountType" not in text


def test_pipe_governed_direction_rule_respects_symmetric_relationships():
    data = json.loads((ROOT / "configs/schema_snb.json").read_text(encoding="utf-8"))
    knows = next(rel["type"] for rel in data["relationships"] if rel["type"] == "KNOWS")
    data["symmetric_relationships"] = [knows]
    schema = SchemaSummary.from_dict(data)
    if not getattr(schema, "symmetric_relationships", None):
        pytest.skip("SchemaSummary has no symmetric_relationships support")
    text = pf.governed_conventions_block(schema)
    assert "undirected patterns only for the symmetric relationship types :KNOWS" in text
    assert "e.g. (:" in text and "[:KNOWS]->" not in text
    assert "never write undirected (--)" in pf.governed_conventions_block(SNB)


def test_pipe_governed_drops_rules_for_labels_absent_from_schema():
    text = pf.governed_conventions_block(SNB)
    assert "Contextual return columns" not in text  # SNB has no FinBench-style trigger properties
    assert "(:" in text  # direction example comes from the SNB schema
    assert "Account" not in text


# ---------------------------------------------------------------------------
# Native formats reproduce documented templates verbatim
# ---------------------------------------------------------------------------


def test_native_formats_are_documented_with_sources():
    natives = [name for name in pf.allowed_prompt_formats() if name.startswith("native_")]
    assert set(natives) == {
        "native_neo4j_gemma2_2024",
        "native_neo4j_gemma3_2025",
        "native_tomasonjo_llama3",
        "native_azzedde_alpaca",
        "native_stable_cypher",
    }
    for name in natives:
        fmt = pf.get_prompt_format(name)
        assert fmt.documented
        assert fmt.source_url and fmt.source_url.startswith("https://")
        assert fmt.model_hf_ids
        assert not fmt.supports_few_shot


def test_native_neo4j_gemma2_template_is_verbatim_single_user_turn():
    rendered = pf.render_prompt("native_neo4j_gemma2_2024", schema_text="S", question="Q?")
    assert rendered.system is None
    assert rendered.user == (
        "Generate Cypher statement to query a graph database. Use only the provided relationship "
        "types and properties in the schema. \nSchema: S \n Question: Q?  \n Cypher output: "
    )
    assert rendered.messages("merge") == [{"role": "user", "content": rendered.user}]


def test_native_neo4j_gemma3_template_is_verbatim_single_user_turn():
    rendered = pf.render_prompt("native_neo4j_gemma3_2025", schema_text="S", question="Q?")
    assert rendered.system is None
    assert rendered.user.endswith("####Schema:\nS\n####Question:\nQ?")
    assert rendered.user.startswith("Generate a Cypher query for the Question below.\n")
    assert pf.native_formats_for_model("neo4j/text-to-cypher-Gemma-3-27B-Instruct-2025.04.0") == [
        "native_neo4j_gemma3_2025"
    ]


def test_native_tomasonjo_and_stable_cypher_templates():
    tomasonjo = pf.render_prompt("native_tomasonjo_llama3", schema_text="S", question="Q?")
    assert tomasonjo.system == "Given an input question, convert it to a Cypher query. No pre-amble."
    assert tomasonjo.user == (
        "Based on the Neo4j graph schema below, write a Cypher query that would answer the "
        "user's question:\nS\n\nQuestion: Q?\nCypher query:"
    )
    stable = pf.render_prompt("native_stable_cypher", schema_text="S", question="Q?")
    assert stable.system == "Create a Cypher statement to answer the following question:"
    assert stable.user == "Q?"  # documented format carries no schema


def test_native_azzedde_is_a_raw_completion_prompt():
    rendered = pf.render_prompt("native_azzedde_alpaca", schema_text="S", question="Q?")
    assert rendered.transport == "completion"
    assert rendered.user == (
        "Below is a database Neo4j schema and a question related to that database. Write a "
        "Cypher query to answer the question.\n\n### Schema:\nS\n\n### Question:\nQ?\n\n### Cypher:\n"
    )
    body = rendered.request_body()
    assert body == {"prompt": rendered.user, "stop": ["\n###"]}
    with pytest.raises(pf.PromptFormatUsageError):
        rendered.messages()


# ---------------------------------------------------------------------------
# Registry errors
# ---------------------------------------------------------------------------


def test_unknown_prompt_format_raises():
    with pytest.raises(pf.UnknownPromptFormatError, match="unknown prompt format"):
        pf.get_prompt_format("native_made_up")
    assert issubclass(pf.UnknownPromptFormatError, ValueError)


def test_native_format_rejects_few_shot_examples():
    with pytest.raises(pf.PromptFormatUsageError, match="few-shot"):
        _render("native_tomasonjo_llama3", few_shots=FEW_SHOTS)


def test_predict_does_not_swallow_prompt_format_errors():
    with pytest.raises(pf.UnknownPromptFormatError):
        predict_text2cypher(llm=RecordingLLM(), example=EXAMPLE, schema=FINBENCH, prompt_format="nope")


# ---------------------------------------------------------------------------
# Transport: user-only chat and raw completions
# ---------------------------------------------------------------------------


def test_user_only_format_sends_no_system_message(monkeypatch):
    llm = OpenAICompatibleLLM("http://localhost:9/v1", "neo4j-gemma3", system_message_mode="merge")
    sent = {}

    class FakeResponse:
        def json(self):
            return {"choices": [{"message": {"content": "MATCH (n:Person) RETURN DISTINCT n.personId"}}]}

    def fake_post(payload):
        sent.update(payload)
        return FakeResponse()

    monkeypatch.setattr(llm, "_post", fake_post)
    prediction = predict_text2cypher(
        llm=llm, example=EXAMPLE, schema=FINBENCH, prompt_format="native_neo4j_gemma3_2025"
    )
    assert prediction.error is None
    assert [message["role"] for message in sent["messages"]] == ["user"]
    assert sent["messages"][0]["content"].startswith("Generate a Cypher query")
    assert prediction.prompt_format == "native_neo4j_gemma3_2025"
    canonical = json.dumps({"messages": sent["messages"]}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert prediction.prompt_sha256 == hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_completion_format_posts_to_completions_route(monkeypatch):
    import pipecypher.text2cypher as t2c

    llm = OpenAICompatibleLLM("http://localhost:9/v1", "Azzedde/llama3.1-8b-text2cypher")
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"text": " MATCH (p:Person) RETURN DISTINCT p.personId"}]}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return FakeResponse()

    monkeypatch.setattr(t2c.requests, "post", fake_post)
    prediction = predict_text2cypher(
        llm=llm, example=EXAMPLE, schema=FINBENCH, prompt_format="native_azzedde_alpaca"
    )
    assert captured["url"] == "http://localhost:9/v1/completions"
    assert captured["json"]["prompt"].endswith("### Cypher:\n")
    assert captured["json"]["stop"] == ["\n###"]
    assert prediction.predicted_cypher == "MATCH (p:Person) RETURN DISTINCT p.personId"
    assert prediction.prompt_transport == "completion"
    assert prediction.system_message_mode is None


# ---------------------------------------------------------------------------
# Prediction script guards
# ---------------------------------------------------------------------------


def _write_benchmark(tmp_path: Path, graph_profile: str) -> Path:
    bench = tmp_path / "bench"
    bench.mkdir()
    row = {**EXAMPLE, "graph_profile": graph_profile}
    (bench / "test.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    return bench


def _run_prediction_script(monkeypatch, argv):
    from scripts import generate_text2cypher_predictions as script

    monkeypatch.setattr(sys, "argv", ["generate_text2cypher_predictions.py", *argv])
    return script


def test_prediction_script_rejects_few_shot_with_native_format(monkeypatch, tmp_path):
    bench = _write_benchmark(tmp_path, "finbench")
    script = _run_prediction_script(
        monkeypatch,
        [
            "--benchmark", str(bench), "--split", "test",
            "--schema", "finbench=configs/schema_finbench.json",
            "--output", str(tmp_path / "out.jsonl"),
            "--prompt-format", "native_tomasonjo_llama3",
            "--few-shot", str(bench / "test.jsonl"), "--few-shot-k", "3",
            "--skip-model-preflight",
        ],
    )
    with pytest.raises(SystemExit, match="zero-shot template"):
        script.main()


def test_prediction_script_keeps_hosted_provider_on_public_graphs(monkeypatch, tmp_path):
    bench = _write_benchmark(tmp_path, "acme_private_tenant")
    script = _run_prediction_script(
        monkeypatch,
        [
            "--benchmark", str(bench), "--split", "test",
            "--schema", "acme_private_tenant=configs/schema_finbench.json",
            "--output", str(tmp_path / "out.jsonl"),
            "--provider", "openai", "--model", "gpt-6-luna",
            "--base-url", "https://api.openai.com/v1",
        ],
    )

    def no_network(*_args, **_kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("hosted endpoint contacted before the public-graph guard")

    monkeypatch.setattr(script, "assert_model_served", no_network)
    with pytest.raises(SystemExit, match="public graphs"):
        script.main()
    assert not (tmp_path / "out.jsonl").exists()
