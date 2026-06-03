import json
from pathlib import Path

import pytest

from pipecypher.paper_appendix import (
    load_claim_evidence,
    load_examples,
    prompt_contracts,
    render_claim_evidence_tex,
    render_example_cards_tex,
    render_prompt_contracts_tex,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
TRACKED_EVIDENCE_PREFIXES = (
    "configs/",
    "experiments/",
    "knowledge_base/",
    "paper_emnlp2026_industry/",
    "pipecypher/",
    "scripts/",
    "tests/",
)


def test_prompt_contracts_include_generation_and_judge_hashes():
    names = {contract.name for contract in prompt_contracts()}
    text = render_prompt_contracts_tex()

    assert r"\section{Prompt Contracts}" in text
    assert "Cypher generation" in names
    assert "LLM judge" in names
    assert "RETURN DISTINCT" in text
    assert "SHA-256" in text
    assert "LLM Judge Prompt Used in Reported Runs" in text
    assert "You are judging whether an NL-to-Cypher" in text
    assert "benchmark example is acceptable for" in text
    assert "System prompt:" in text
    assert "User prompt template:" in text
    assert r"\label{tab:prompt_contracts}" in text
    assert r"\begin{table*}" not in text


def test_load_claim_evidence_validates_required_keys(tmp_path: Path):
    path = tmp_path / "claims.yaml"
    path.write_text(
        """
claims:
  - claim: Local generation works.
    evidence: A full run exported examples.
    artifacts:
      - artifacts/benchmarks/run
    status: Supported by artifact evidence.
    risk: More graphs are needed.
""",
        encoding="utf-8",
    )

    claims = load_claim_evidence(path)
    text = render_claim_evidence_tex(claims)

    assert claims[0]["claim"] == "Local generation works."
    assert r"\label{tab:claim_evidence_map}" in text
    assert "Local generation works." in text
    assert r"\textit{Risk.} More graphs are needed." in text
    assert "benchmark export" in text
    assert "artifacts/benchmarks/run" not in text
    assert r"\begin{table*}" not in text


def test_claim_evidence_shortens_script_artifact_labels(tmp_path: Path):
    path = tmp_path / "claims.yaml"
    path.write_text(
        """
claims:
  - claim: Remote runs are monitored.
    evidence: Queue tooling records active and completed suites.
    artifacts:
      - scripts/monitor_remote_ablation_queue.py
    status: Supported by tooling.
    risk: Runs still need to complete.
""",
        encoding="utf-8",
    )

    text = render_claim_evidence_tex(load_claim_evidence(path))

    assert "script: monitor remote ablation queue" in text
    assert "monitor\\_remote\\_ablation\\_queue.py" not in text


def test_load_claim_evidence_rejects_missing_keys(tmp_path: Path):
    path = tmp_path / "bad_claims.yaml"
    path.write_text(
        """
claims:
  - claim: Missing fields.
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing keys"):
        load_claim_evidence(path)


def test_claim_evidence_tracked_artifacts_resolve():
    claims = load_claim_evidence(REPO_ROOT / "knowledge_base/claim_evidence_map.yaml")

    missing: list[str] = []
    for claim in claims:
        for artifact in claim.get("artifacts", []):
            if not any(str(artifact).startswith(prefix) for prefix in TRACKED_EVIDENCE_PREFIXES):
                continue
            if not (REPO_ROOT / str(artifact)).exists():
                missing.append(str(artifact))

    assert missing == []


def test_render_example_cards_escapes_cypher_and_reports_gates():
    text = render_example_cards_tex(
        [
            {
                "id": "b",
                "graph_profile": "snb",
                "category": "ranking_topk",
                "difficulty": "medium",
                "question": "Which posts have tag 'A&B'?",
                "cypher": "MATCH (p:Post)-[:HAS_TAG]->(t:Tag {name: 'A&B'}) RETURN DISTINCT p.id",
                "result_rows_sample": [{"id": 1}],
                "gates": {
                    "read_only": True,
                    "syntax_valid": True,
                    "schema_valid": True,
                    "execution_success": True,
                    "judge_pass": True,
                },
                "structural_features": {
                    "strategy_tags": ["join_heavy", "bounded_result"],
                    "relationship_types": ["HAS_TAG"],
                },
            }
        ]
    )

    assert r"A\&B" in text
    assert r"\textgreater{}" in text
    assert "RO/Syn/Schema/Exec/Judge" in text
    assert "HAS\\_TAG" in text


def test_render_example_cards_keeps_quoted_values_intact_after_wrapping():
    text = render_example_cards_tex(
        [
            {
                "id": "a",
                "graph_profile": "finbench",
                "category": "simple_retrieval",
                "difficulty": "medium",
                "question": "Which transfers mention the long routing channel?",
                "cypher": (
                    "MATCH (a:Account)-[:TRANSFER]->(b:Account) "
                    "WHERE a.channel = 'International-Wire-Transfer-Clearing' "
                    "RETURN DISTINCT a.id, b.id"
                ),
                "result_rows_sample": [{"source": "A1", "target": "B2"}],
                "gates": {"read_only": True, "syntax_valid": True},
                "structural_features": {"strategy_tags": [], "relationship_types": ["TRANSFER"]},
            }
        ]
    )

    assert "International-Wire-Transfer-Clearing" in text
    assert "International-Wire-Transfer-\\\\\nClearing" not in text
    assert ") -[:TRANSFER]-\\textgreater{}" in text


def test_load_examples_supports_json_and_jsonl(tmp_path: Path):
    rows = [{"id": "1"}, {"id": "2"}]
    json_path = tmp_path / "examples.json"
    jsonl_path = tmp_path / "examples.jsonl"
    json_path.write_text(json.dumps(rows), encoding="utf-8")
    jsonl_path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    assert load_examples(json_path) == rows
    assert load_examples(jsonl_path) == rows


def test_load_examples_rejects_non_list_json(tmp_path: Path):
    path = tmp_path / "bad.json"
    path.write_text('{"id": "not-a-list"}', encoding="utf-8")

    with pytest.raises(ValueError):
        load_examples(path)
