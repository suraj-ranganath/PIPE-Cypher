from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from pipecypher.benchmark_export import benchmark_id, materialize_benchmark_examples
from pipecypher.calibration import _cohen_kappa_from_pairs
from pipecypher.judge import schema_slice_for_cypher
from pipecypher.judge_agreement import (
    PRIVATE_NOTICE,
    RejudgeAborted,
    SourceRecordIndex,
    analyze_judge_agreement,
    assert_hosted_graphs_public,
    binary_confusion,
    cohen_kappa,
    fleiss_kappa,
    fleiss_kappa_from_ratings,
    gwet_ac1,
    items_from_benchmark,
    items_from_records,
    judge_disagreement_rows,
    judge_item,
    load_rejudge_file,
    read_csv_rows,
    run_rejudge,
    write_private_csv,
)
from pipecypher.llm import ChatResponse
from pipecypher.models import ExecutionResult, GenerationRecord, JudgeResult
from pipecypher.prompts import JUDGE_PROMPT, SYSTEM_JSON_ENGINEER
from pipecypher.question_constraints import apply_question_constraints
from pipecypher.schema import load_schema
from pipecypher.validator import validate_cypher
from scripts import analyze_judge_agreement as analyze_script
from scripts import rejudge_with_independent_model as rejudge_script

ROOT = Path(__file__).resolve().parents[1]
FINBENCH_SCHEMA = ROOT / "configs" / "schema_finbench.json"
PASS_JSON = json.dumps(
    {
        "pass": True,
        "ambiguity_score": 0.1,
        "semantic_alignment_score": 0.9,
        "schema_use_score": 1.0,
        "difficulty": "easy",
        "failure_reason": "",
    }
)
FAIL_JSON = json.dumps(
    {
        "pass": False,
        "ambiguity_score": 0.6,
        "semantic_alignment_score": 0.3,
        "schema_use_score": 1.0,
        "difficulty": "easy",
        "failure_reason": "direction reversed",
    }
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def schema():
    return load_schema(FINBENCH_SCHEMA)


def _record(schema, name: str, *, accepted=True, judge=None, rows=None, category="simple_retrieval"):
    question = f"Which accounts are owned by person '{name}'?"
    cypher = (
        f"MATCH (p:Person {{personName: '{name}'}})-[:OWN_ACCOUNT]->(a:Account) "
        "RETURN DISTINCT a.accountId AS AccountId, a.accountType AS AccountType, a.isBlocked AS IsBlocked LIMIT 300"
    )
    validation = apply_question_constraints(validate_cypher(cypher, schema), question)
    if rows is None:
        rows = [{"AccountId": str(100 + i), "AccountType": "prepaid card", "IsBlocked": False} for i in range(7)]
    if judge is None:
        judge = JudgeResult(
            passed=True,
            ambiguity_score=0.0,
            semantic_alignment_score=1.0,
            schema_use_score=1.0,
            difficulty="easy",
            raw=json.loads(PASS_JSON),
        )
    return GenerationRecord(
        question=question,
        cypher=validation.normalized_cypher,
        category=category,
        graph_profile="finbench",
        accepted=accepted,
        validation=validation,
        execution=ExecutionResult(success=True, rows=rows),
        judge=judge,
        model="Qwen/Qwen3.5-9B",
    ).to_dict()


def _write_records(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def _export_rows(records: list[dict], records_path: Path) -> list[dict]:
    rows = []
    for record in records:
        row = dict(record)
        row["_source_run"] = records_path.parent.name
        row["_source_records_path"] = str(records_path)
        rows.append(row)
    return materialize_benchmark_examples(rows)


class StubLLM:
    model = "stub/judge-model"

    def __init__(self, responder):
        self.responder = responder
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        result = self.responder(len(self.calls), kwargs)
        if isinstance(result, Exception):
            raise result
        return ChatResponse(text=result, raw={"usage": {"prompt_tokens": 10, "completion_tokens": 5}})


# ---------------------------------------------------------------------------
# Agreement statistics
# ---------------------------------------------------------------------------


def test_cohen_kappa_known_value_and_matches_calibration():
    # Classic 2x2 example: 20 yes/yes, 5 yes/no, 10 no/yes, 15 no/no -> kappa = 0.4.
    a = [True] * 25 + [False] * 25
    b = [True] * 20 + [False] * 5 + [True] * 10 + [False] * 15
    assert cohen_kappa(a, b) == pytest.approx(0.4)
    assert cohen_kappa(a, b) == pytest.approx(_cohen_kappa_from_pairs(list(zip(a, b))))
    assert cohen_kappa([True, True], [True, True]) is None
    assert cohen_kappa(["x", "y", "z"], ["x", "y", "z"]) == pytest.approx(1.0)


def test_gwet_ac1_known_value():
    a = [True] * 25 + [False] * 25
    b = [True] * 20 + [False] * 5 + [True] * 10 + [False] * 15
    # p_o = 0.7; pi_yes = 0.55; p_e = 2 * 0.55 * 0.45 = 0.495 -> (0.7 - 0.495) / 0.505
    assert gwet_ac1(a, b) == pytest.approx((0.7 - 0.495) / 0.505)


def test_fleiss_kappa_known_value():
    # Fleiss (1971) worked example: 10 items, 14 raters, 5 categories -> kappa ~= 0.210.
    table = [
        [0, 0, 0, 0, 14],
        [0, 2, 6, 4, 2],
        [0, 0, 3, 5, 6],
        [0, 3, 9, 2, 0],
        [2, 2, 8, 1, 1],
        [7, 7, 0, 0, 0],
        [3, 2, 6, 3, 0],
        [2, 5, 3, 2, 2],
        [6, 5, 2, 1, 0],
        [0, 2, 2, 3, 7],
    ]
    counts = [{cat: n for cat, n in enumerate(row) if n} for row in table]
    assert fleiss_kappa(counts) == pytest.approx(0.20993, abs=1e-4)
    # With two raters Fleiss is close to (not identical to) Cohen; perfect agreement -> 1.
    assert fleiss_kappa_from_ratings([[True, True], [False, False], [True, True]]) == pytest.approx(1.0)
    with pytest.raises(ValueError):
        fleiss_kappa([{1: 2}, {1: 3}])


def test_binary_confusion_flag_and_rescue_rates():
    pairs = [(True, True)] * 8 + [(True, False)] * 2 + [(False, False)] * 3 + [(False, True)]
    conf = binary_confusion(pairs)
    assert conf["reference_pass_other_fail"] == 2
    assert conf["reference_fail_other_pass"] == 1
    assert conf["flag_rate_among_reference_pass"] == pytest.approx(0.2)
    assert conf["rescue_rate_among_reference_fail"] == pytest.approx(0.25)
    assert conf["agreement"] == pytest.approx(11 / 14)
    low, high = conf["flag_rate_ci95"]
    assert 0 < low < 0.2 < high < 1


# ---------------------------------------------------------------------------
# Item construction and identical prompt contract
# ---------------------------------------------------------------------------


def test_records_eligibility_skips_post_judge_and_keeps_fallback(schema):
    accepted = _record(schema, "Bertrand")
    llm_rejected = _record(
        schema,
        "Thorburn",
        accepted=False,
        judge=JudgeResult(
            passed=False,
            ambiguity_score=0.6,
            semantic_alignment_score=0.3,
            schema_use_score=1.0,
            difficulty="easy",
            failure_reason="direction reversed",
            raw=json.loads(FAIL_JSON),
        ),
    )
    duplicate = _record(schema, "Alys", accepted=False, judge=JudgeResult.failed("duplicate accepted question"))
    no_rows = _record(schema, "Cato", accepted=False, judge=JudgeResult.failed("execution returned no rows"), rows=[])
    fallback = _record(
        schema,
        "Dara",
        judge=JudgeResult(
            passed=True,
            ambiguity_score=0.2,
            semantic_alignment_score=0.85,
            schema_use_score=1.0,
            difficulty="easy",
            raw={"fallback_after_error": "No JSON object or array found"},
        ),
    )
    records = [accepted, llm_rejected, duplicate, no_rows, fallback]

    rejected_items, skipped = items_from_records(records, {"finbench": schema}, scope="rejected")
    assert [item.question for item in rejected_items] == [llm_rejected["question"]]
    assert rejected_items[0].original["decision"] is False
    assert rejected_items[0].original["decision_source"] == "llm_judge"
    reasons = " | ".join(s.reason for s in skipped)
    assert "post-judge rejection" in reasons and "execution returned no rows" in reasons

    all_items, _ = items_from_records(records, {"finbench": schema}, scope="all")
    sources = {item.question: item.original["decision_source"] for item in all_items}
    assert sources[fallback["question"]] == "deterministic_fallback_after_llm_error"
    assert all_items[0].item_id == benchmark_id(accepted)


def test_export_reconstruction_matches_source_record_prompt(tmp_path: Path, schema):
    records = [_record(schema, "Bertrand"), _record(schema, "Thorburn", category="complex_retrieval")]
    records_path = tmp_path / "runs" / "run_a" / "records.jsonl"
    _write_records(records_path, records)
    rows = _export_rows(records, records_path)

    from_record, _ = items_from_benchmark(
        rows, {"finbench": schema}, context_mode="record", source_index=SourceRecordIndex([tmp_path])
    )
    from_export, _ = items_from_benchmark(rows, {"finbench": schema}, context_mode="export")
    assert {item.context_source for item in from_record} == {"source_record"}
    assert {item.context_source for item in from_export} == {"export_reconstructed"}

    stub = StubLLM(lambda n, kw: PASS_JSON)
    for a, b in zip(from_record, from_export):
        row_a = judge_item(a, llm=stub, schema=schema, judge_label="j", judge_model="m", judge_role="independent")
        row_b = judge_item(b, llm=stub, schema=schema, judge_label="j", judge_model="m", judge_role="independent")
        assert row_a["prompt_sha256"] == row_b["prompt_sha256"]
        # The captured prompt is exactly the original judge contract rendering.
        expected_user = JUDGE_PROMPT.format(
            schema=schema_slice_for_cypher(schema, a.cypher).to_prompt(max_items=80),
            question=a.question,
            cypher=a.cypher,
            rows=json.dumps(a.execution.rows[:5], default=str),
            validation=json.dumps(
                {
                    "ok": a.validation.ok,
                    "issues": [issue.__dict__ for issue in a.validation.issues],
                    "features": a.validation.structural_features,
                },
                default=str,
            ),
        )
        assert row_a["judge_prompt_user"] == expected_user
        assert row_a["judge_prompt_system"] == SYSTEM_JSON_ENGINEER
    assert stub.calls[0]["temperature"] == 0.0
    assert stub.calls[0]["max_tokens"] == 512
    assert stub.calls[0]["response_format"] == {"type": "json_object"}


def test_judge_item_counts_parse_failure_as_error_not_fallback(schema):
    items, _ = items_from_records([_record(schema, "Bertrand")], {"finbench": schema}, scope="all")
    stub = StubLLM(lambda n, kw: "I cannot answer in JSON")
    row = judge_item(items[0], llm=stub, schema=schema, judge_label="j", judge_model="m", judge_role="independent")
    assert row["decision"] is None
    assert row["error_kind"] == "parse_error"
    assert row["raw_response_text"] == "I cannot answer in JSON"
    assert row["scores"] is None


# ---------------------------------------------------------------------------
# Runner: consecutive-failure abort, error-rate gate, resume
# ---------------------------------------------------------------------------


def _many_items(schema, n: int):
    records = [_record(schema, f"Name{i:02d}") for i in range(n)]
    items, _ = items_from_records(records, {"finbench": schema}, scope="all")
    return items


def test_run_rejudge_aborts_after_consecutive_failures(tmp_path: Path, schema):
    items = _many_items(schema, 8)
    stub = StubLLM(lambda n, kw: requests.exceptions.ConnectionError("refused"))
    out = tmp_path / "rejudge.jsonl"
    with pytest.raises(RejudgeAborted) as excinfo:
        run_rejudge(
            items,
            llm=stub,
            schemas={"finbench": schema},
            output_path=out,
            judge_label="stub",
            judge_model="stub/judge-model",
            judge_role="independent",
            max_consecutive_errors=5,
            request_retries=1,
            progress=None,
            sleep=lambda _: None,
        )
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(rows) == 5
    assert all(row["error_kind"] == "request_error" for row in rows)
    assert all(row["request_attempts"] == 2 for row in rows)
    assert excinfo.value.summary["status"] == "aborted_consecutive_failures"
    assert len(stub.calls) == 10


def test_run_rejudge_error_rate_gate_and_resume(tmp_path: Path, schema):
    items = _many_items(schema, 10)

    def responder(n, kwargs):
        return "not json" if n == 3 else PASS_JSON

    out = tmp_path / "rejudge.jsonl"
    summary = run_rejudge(
        items,
        llm=StubLLM(responder),
        schemas={"finbench": schema},
        output_path=out,
        judge_label="stub",
        judge_model="stub/judge-model",
        judge_role="independent",
        concurrency=3,
        progress=None,
    )
    assert summary["status"] == "error_rate_exceeded"
    assert summary["failed_calls"] == 1
    assert summary["decisions"] == {"pass": 9}
    with pytest.raises(FileExistsError):
        run_rejudge(
            items,
            llm=StubLLM(responder),
            schemas={"finbench": schema},
            output_path=out,
            judge_label="stub",
            judge_model="m",
            judge_role="independent",
            progress=None,
        )
    resumed = run_rejudge(
        items,
        llm=StubLLM(lambda n, kw: FAIL_JSON),
        schemas={"finbench": schema},
        output_path=out,
        judge_label="stub",
        judge_model="stub/judge-model",
        judge_role="independent",
        resume=True,
        progress=None,
    )
    assert resumed["items_targeted"] == 1 and resumed["status"] == "complete"
    run = load_rejudge_file(out)
    assert len(run.rows_by_id) == 10 and run.duplicate_rows == 1
    assert sum(1 for row in run.rows_by_id.values() if row["decision"] is False) == 1


# ---------------------------------------------------------------------------
# Script: preflight abort, hosted OpenAI path, hosted graph guard
# ---------------------------------------------------------------------------


def _script_fixture(tmp_path: Path, schema, graph: str = "finbench") -> tuple[Path, Path]:
    records = [_record(schema, "Bertrand"), _record(schema, "Thorburn")]
    for record in records:
        record["graph_profile"] = graph
    records_path = tmp_path / "runs" / "run_a" / "records.jsonl"
    _write_records(records_path, records)
    bench = tmp_path / "bench.jsonl"
    bench.write_text("".join(json.dumps(r) + "\n" for r in _export_rows(records, records_path)), encoding="utf-8")
    return bench, records_path


def test_script_preflight_aborts_when_model_not_served(tmp_path: Path, schema, monkeypatch):
    bench, _ = _script_fixture(tmp_path, schema)
    models = Mock()
    models.json.return_value = {"data": [{"id": "Qwen/Qwen3.5-9B"}]}
    models.raise_for_status.return_value = None
    monkeypatch.setattr("pipecypher.llm.requests.get", Mock(return_value=models))
    post = Mock(side_effect=AssertionError("no judge call may happen before preflight passes"))
    monkeypatch.setattr("pipecypher.llm.requests.post", post)
    out = tmp_path / "out.jsonl"
    code = rejudge_script.main(
        [
            "--benchmark", str(bench),
            "--schema", f"finbench={FINBENCH_SCHEMA}",
            "--model", "meta-llama/Llama-3.3-70B-Instruct",
            "--output", str(out),
        ]
    )
    assert code == 2
    assert not out.exists()
    post.assert_not_called()


def test_script_refuses_hosted_endpoint_for_vllm_provider(tmp_path: Path, schema, monkeypatch):
    bench, _ = _script_fixture(tmp_path, schema)
    get = Mock(side_effect=AssertionError("hosted endpoint must be refused before any request"))
    monkeypatch.setattr("pipecypher.llm.requests.get", get)
    code = rejudge_script.main(
        [
            "--benchmark", str(bench),
            "--schema", f"finbench={FINBENCH_SCHEMA}",
            "--base-url", "https://api.openai.com/v1",
            "--model", "gpt-6-luna",
            "--output", str(tmp_path / "out.jsonl"),
        ]
    )
    assert code == 2
    get.assert_not_called()


def test_script_openai_provider_path(tmp_path: Path, schema, monkeypatch):
    secret = "sk-test-secret-should-never-be-written"
    monkeypatch.delenv("PIPE_CYPHER_LLM_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    bench, _ = _script_fixture(tmp_path, schema)
    models = Mock()
    models.json.return_value = {"data": [{"id": "gpt-6-luna"}, {"id": "other"}]}
    models.raise_for_status.return_value = None
    get = Mock(return_value=models)
    completion = Mock()
    completion.status_code = 200
    completion.raise_for_status.return_value = None
    completion.json.return_value = {
        "choices": [{"message": {"content": FAIL_JSON}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }
    post = Mock(return_value=completion)
    monkeypatch.setattr("pipecypher.llm.requests.get", get)
    monkeypatch.setattr("pipecypher.llm.requests.post", post)
    out = tmp_path / "luna.jsonl"
    code = rejudge_script.main(
        [
            "--benchmark", str(bench),
            "--schema", f"finbench={FINBENCH_SCHEMA}",
            "--provider", "openai",
            "--model", "gpt-6-luna",
            "--no-temperature",
            "--reasoning-effort", "low",
            "--max-tokens", "4096",
            "--source-root", str(tmp_path),
            "--output", str(out),
        ]
    )
    assert code == 0
    assert get.call_args.args[0] == "https://api.openai.com/v1/models"
    assert post.call_args.args[0] == "https://api.openai.com/v1/chat/completions"
    assert post.call_args.kwargs["headers"]["Authorization"] == f"Bearer {secret}"
    payload = post.call_args.kwargs["json"]
    assert "temperature" not in payload
    assert payload["max_completion_tokens"] == 4096
    assert payload["reasoning_effort"] == "low"
    assert "chat_template_kwargs" not in payload and "include_reasoning" not in payload
    assert payload["messages"][0] == {"role": "system", "content": SYSTEM_JSON_ENGINEER}

    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(rows) == 2
    assert {row["provider"] for row in rows} == {"openai"}
    assert {row["judge_model"] for row in rows} == {"gpt-6-luna"}
    assert {row["judge_role"] for row in rows} == {"independent"}
    assert all(row["decision"] is False for row in rows)
    assert all(row["call_settings"]["send_temperature"] is False for row in rows)
    assert {row["context_source"] for row in rows} == {"source_record"}
    for path in tmp_path.glob("luna*"):
        assert secret not in path.read_text(encoding="utf-8")


def test_hosted_provider_refuses_non_ldbc_graph(tmp_path: Path, schema, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    bench, _ = _script_fixture(tmp_path, schema, graph="tenant_private")
    get = Mock(side_effect=AssertionError("must refuse before contacting the hosted API"))
    monkeypatch.setattr("pipecypher.llm.requests.get", get)
    code = rejudge_script.main(
        [
            "--benchmark", str(bench),
            "--context-source", "export",
            "--schema", f"tenant_private={FINBENCH_SCHEMA}",
            "--provider", "openai",
            "--model", "gpt-6-luna",
            "--output", str(tmp_path / "out.jsonl"),
        ]
    )
    assert code == 2
    get.assert_not_called()
    with pytest.raises(ValueError):
        assert_hosted_graphs_public(["finbench", "icij"])
    assert_hosted_graphs_public(["finbench", "snb"])


# ---------------------------------------------------------------------------
# Agreement analysis and disagreement packet
# ---------------------------------------------------------------------------


def _rejudge_rows(label: str, decisions: dict[str, bool | None], originals: dict[str, bool], *, role="independent"):
    rows = []
    for item_id, decision in decisions.items():
        rows.append(
            {
                "item_id": item_id,
                "item_source": "benchmark" if originals[item_id] else "records_rejected",
                "graph_profile": "finbench" if item_id < "i5" else "snb",
                "category": "ranking_topk" if item_id.endswith(("0", "1")) else "simple_retrieval",
                "difficulty": "easy",
                "question": f"Question {item_id} about 'Value'?",
                "cypher": "MATCH (n) RETURN DISTINCT n.id AS id",
                "result_row_count_observed": 2,
                "execution_rows_shown": [{"id": "Value"}],
                "original_judge": {
                    "decision": originals[item_id],
                    "decision_source": "llm_judge",
                    "source_model": "Qwen/Qwen3.5-9B",
                },
                "judge_label": label,
                "judge_model": f"org/{label}",
                "judge_role": role,
                "provider": "vllm",
                "decision": decision,
                "error": None if decision is not None else "boom",
                "error_kind": None if decision is not None else "request_error",
                "scores": {"failure_reason": "" if decision else "bad"} if decision is not None else None,
                "judge_contract_sha256": "abc",
                "context_source": "source_record",
            }
        )
    return rows


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_analyze_judge_agreement_and_disagreement_packet(tmp_path: Path):
    ids = [f"i{k}" for k in range(8)]
    originals = {i: True for i in ids[:6]} | {"i6": False, "i7": False}
    llama = {"i0": True, "i1": False, "i2": True, "i3": True, "i4": False, "i5": True, "i6": False, "i7": True}
    gemma = {"i0": True, "i1": False, "i2": True, "i3": True, "i4": True, "i5": None, "i6": False, "i7": False}
    _write_jsonl(tmp_path / "llama.jsonl", _rejudge_rows("llama", llama, originals))
    _write_jsonl(tmp_path / "gemma.jsonl", _rejudge_rows("gemma", gemma, originals))
    runs = [load_rejudge_file(tmp_path / "llama.jsonl"), load_rejudge_file(tmp_path / "gemma.jsonl")]
    report = analyze_judge_agreement(runs, original_label="original")

    judges = {j["label"]: j for j in report["judges"]}
    assert judges["original"]["pass_rate"]["count"] == 6
    assert judges["gemma"]["decided"] == 7 and judges["gemma"]["errors"] == 1
    vs = report["vs_original"]["llama"]
    assert (vs["both_pass"], vs["reference_pass_other_fail"], vs["reference_fail_other_pass"], vs["both_fail"]) == (4, 2, 1, 1)
    assert vs["cohen_kappa"] == pytest.approx(cohen_kappa([originals[i] for i in ids], [llama[i] for i in ids]))
    flags = report["flags"]
    assert flags["flagged_by_any_independent"] == 2  # i1 (both), i4 (llama)
    assert flags["flagged_by_at_least_2_independent"] == 1
    assert flags["rescued_by_any_independent"] == 1  # i7 by llama
    fleiss = report["fleiss"]["all_judges"]
    assert fleiss["n_items"] == 7
    common = [i for i in ids if i != "i5"]
    expected = fleiss_kappa_from_ratings([[originals[i], llama[i], gemma[i]] for i in common])
    assert fleiss["kappa"] == pytest.approx(expected)
    assert report["slices"]["by_graph"]["finbench"]["llama"]["n"] == 5

    rows, fields = judge_disagreement_rows(runs, report)
    assert {row["item_id"] for row in rows} == {"i1", "i4", "i7"}
    assert rows[0]["item_id"] == "i1"  # original pass, failed by both independents
    csv_path = tmp_path / "disagreements.csv"
    write_private_csv(csv_path, rows, fields)
    assert csv_path.read_text(encoding="utf-8").splitlines()[0] == f"# {PRIVATE_NOTICE}"
    assert [row["item_id"] for row in read_csv_rows(csv_path)] == [row["item_id"] for row in rows]


def test_analyze_judge_agreement_script_writes_outputs(tmp_path: Path):
    originals = {f"i{k}": k % 3 != 0 for k in range(6)}
    decisions = {f"i{k}": k % 2 == 0 for k in range(6)}
    _write_jsonl(tmp_path / "a.jsonl", _rejudge_rows("judge_a", decisions, originals))
    code = analyze_script.main(
        [
            "--rejudge", f"custom_label={tmp_path / 'a.jsonl'}",
            "--output-json", str(tmp_path / "out" / "agreement.json"),
            "--output-md", str(tmp_path / "out" / "agreement.md"),
            "--output-tex", str(tmp_path / "out" / "agreement.tex"),
            "--output-slices-tex", str(tmp_path / "out" / "slices.tex"),
            "--output-disagreements-csv", str(tmp_path / "out" / "disagreements.csv"),
            "--require-complete",
        ]
    )
    assert code == 0
    report = json.loads((tmp_path / "out" / "agreement.json").read_text())
    assert [j["label"] for j in report["judges"]] == ["original_qwen3.5_9b", "custom_label"]
    tex = (tmp_path / "out" / "agreement.tex").read_text()
    assert "custom\\_label" in tex and "\\begin{tabular}" in tex
    assert "Independent Judge Agreement" in (tmp_path / "out" / "agreement.md").read_text()
    assert (tmp_path / "out" / "disagreements.csv").read_text().startswith("# PRIVATE/internal")
