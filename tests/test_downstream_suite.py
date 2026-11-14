from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from pipecypher.config import ConfigValidationError, load_config
from pipecypher.downstream_model_transfer import _control_slug_from_zero_run, _parse_control_run_id
from pipecypher.prompt_formats import get_prompt_format
from scripts import run_downstream_suite as suite

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "configs/downstream_models_naacl2027.yaml"
PREFIX = "20261111_test"

REQUIRED_SLUGS = {
    "qwen35_9b",
    "qwen25_coder7b",
    "qwen3_coder_30b_a3b",
    "gemma3_12b_it",
    "gemma3_27b_it",
    "llama31_8b_instruct",
    "llama33_70b_instruct_awq",
    "mistral_small32_24b",
    "neo4j_gemma2_text2cypher_lora",
    "neo4j_gemma3_4b_text2cypher",
    "neo4j_gemma3_27b_text2cypher",
    "tomasonjo_text2cypher8b",
    "azzedde_llama31_text2cypher",
    "aigentx_llama31_cypher_lora",
    "aigentx_llama31_cypher_mixed_lora",
    "projectwilsen_llama31_text2cypher_lora",
    "saiprasanth_llama31_text2cypher_lora",
    "stable_cypher_instruct3b",
    "gpt6_luna",
}


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def test_manifest_parses_and_covers_required_models():
    manifest = suite.load_model_manifest(MANIFEST)
    slugs = {model.slug for model in manifest.models}
    assert REQUIRED_SLUGS <= slugs

    generator = manifest.model("qwen35_9b")
    assert generator.is_generator and generator.hf_id == "Qwen/Qwen3.5-9B"

    for model in manifest.models:
        if model.lora:
            assert model.served_model_name == model.lora.alias
            assert model.base_served_model_name != model.served_model_name
            assert model.serve_model == model.lora.base_model
        if model.family == "text2cypher":
            assert model.native_format_status in {
                "documented_model_card",
                "documented_official_companion",
                "none_documented",
            }
        if model.native_prompt_format:
            fmt = get_prompt_format(model.native_prompt_format)
            assert {model.hf_id, model.lora.adapter_hf_id if model.lora else None} & set(fmt.model_hf_ids)
        if not model.hosted:
            assert model.vllm is not None
            assert model.vllm.tensor_parallel_size == model.gpus_required

    natives = {m.slug: m.native_prompt_format for m in manifest.models}
    assert natives["neo4j_gemma2_text2cypher_lora"] == "native_neo4j_gemma2_2024"
    assert natives["neo4j_gemma3_4b_text2cypher"] == "native_neo4j_gemma3_2025"
    assert natives["tomasonjo_text2cypher8b"] == "native_tomasonjo_llama3"
    assert natives["azzedde_llama31_text2cypher"] == "native_azzedde_alpaca"
    assert natives["stable_cypher_instruct3b"] == "native_stable_cypher"
    for slug in (
        "aigentx_llama31_cypher_lora",
        "aigentx_llama31_cypher_mixed_lora",
        "projectwilsen_llama31_text2cypher_lora",
        "saiprasanth_llama31_text2cypher_lora",
    ):
        assert natives[slug] is None
        assert manifest.model(slug).native_format_status == "none_documented"

    gated = {m.slug for m in manifest.models if m.license_gated}
    assert {"gemma3_12b_it", "llama31_8b_instruct", "neo4j_gemma2_text2cypher_lora"} <= gated


def test_manifest_hosted_reference_entry():
    hosted = suite.load_model_manifest(MANIFEST).model("gpt6_luna")
    assert hosted.served_model_name == "gpt-6-luna"
    assert hosted.provider == "openai"
    assert hosted.hosted and not hosted.local_weights
    assert hosted.base_url == "https://api.openai.com/v1"
    assert hosted.family == "frontier (hosted)"
    assert hosted.public_graphs_only
    assert set(hosted.allowed_graph_profiles) >= {"finbench", "snb"}
    assert hosted.vllm is None and hosted.lora is None and hosted.native_prompt_format is None


def test_manifest_is_not_a_run_config():
    with pytest.raises(ConfigValidationError):
        load_config(MANIFEST, strict=True)
    with pytest.raises(suite.ManifestError, match="not a downstream model manifest"):
        suite.load_model_manifest(ROOT / "configs/finbench_full.yaml")


def _write_manifest_variant(tmp_path: Path, mutate) -> Path:
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _model(data, slug):
    return next(model for model in data["models"] if model["slug"] == slug)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: _model(d, "qwen35_9b").update({"servd_model_name": "x"}), "unknown key"),
        (lambda d: d.update({"generation": {}}), "unknown key"),
        (
            lambda d: _model(d, "neo4j_gemma2_text2cypher_lora")["lora"].update(
                {"base_served_model_name": "neo4j_gemma2_text2cypher_lora"}
            ),
            "must differ from the LoRA alias",
        ),
        (
            lambda d: _model(d, "neo4j_gemma2_text2cypher_lora").update({"served_model_name": "google/gemma-2-9b-it"}),
            "LoRA alias",
        ),
        (lambda d: _model(d, "gpt6_luna").update({"public_graphs_only": False}), "public_graphs_only"),
        (lambda d: _model(d, "qwen35_9b").update({"native_prompt_format": "native_nope"}), "unknown prompt format"),
        (
            lambda d: _model(d, "qwen35_9b").update(
                {"native_prompt_format": "native_tomasonjo_llama3", "native_format_status": "documented_model_card"}
            ),
            "documents",
        ),
        (
            lambda d: _model(d, "aigentx_llama31_cypher_lora").update({"native_format_status": "not_applicable"}),
            "none_documented",
        ),
        (lambda d: _model(d, "qwen35_9b").update({"slug": "qwen_control_9b"}), "run-directory marker"),
    ],
)
def test_manifest_validation_errors(tmp_path, mutate, message):
    path = _write_manifest_variant(tmp_path, mutate)
    with pytest.raises(suite.ManifestError, match=message):
        suite.load_model_manifest(path)


# ---------------------------------------------------------------------------
# Run-directory names stay parseable by downstream_model_transfer
# ---------------------------------------------------------------------------


def test_run_dir_names_round_trip_with_transfer_parsers():
    manifest = suite.load_model_manifest(MANIFEST)
    for model in manifest.models:
        for condition in suite.conditions_for_model(model):
            name = suite.run_dir_name(PREFIX, model.slug, condition)
            assert suite.parse_run_dir_name(name) == (PREFIX, model.slug, condition.id)
            if condition.id == "zero_pipe_standard":
                assert _control_slug_from_zero_run(name) == model.slug
                assert _parse_control_run_id(name) is None
            elif condition.dir_kind == "control":
                slug, _mode = _parse_control_run_id(name)
                assert slug == model.slug
            else:
                assert _parse_control_run_id(name) is None


def test_conditions_cover_reviewer_matrix():
    manifest = suite.load_model_manifest(MANIFEST)
    with_native = [c.id for c in suite.conditions_for_model(manifest.model("tomasonjo_text2cypher8b"))]
    without_native = [c.id for c in suite.conditions_for_model(manifest.model("qwen25_coder7b"))]
    assert with_native == suite.all_condition_ids()
    assert "zero_native" not in without_native
    few_shot = [c for c in suite.conditions_for_model(manifest.model("qwen25_coder7b")) if c.shot == "few_shot"]
    assert {c.prompt_format for c in few_shot} == {"pipe_standard"}
    assert sorted(c.few_shot_seed for c in few_shot if c.few_shot_mode == "random_same_category") == [13, 17, 23]
    scored = next(c for c in few_shot if c.few_shot_mode == "scored_no_signature")
    assert scored.exclude_signature_match


# ---------------------------------------------------------------------------
# CLI: dry run, provider handling, abort semantics
# ---------------------------------------------------------------------------


def _benchmark(tmp_path: Path, graph_profile: str = "finbench") -> Path:
    bench = tmp_path / "bench"
    bench.mkdir()
    (bench / "manifest.json").write_text(json.dumps({"sha256": "declared"}), encoding="utf-8")
    rows = [
        {"id": f"{graph_profile}_{i}", "question": "Q?", "cypher": "MATCH (n) RETURN n", "graph_profile": graph_profile}
        for i in range(2)
    ]
    text = "".join(json.dumps(row) + "\n" for row in rows)
    (bench / "test.jsonl").write_text(text, encoding="utf-8")
    (bench / "train.jsonl").write_text(text, encoding="utf-8")
    return bench


def _argv(tmp_path: Path, bench: Path, *extra: str) -> list[str]:
    return [
        "--manifest",
        str(MANIFEST),
        "--benchmark",
        str(bench),
        "--prefix",
        PREFIX,
        "--output-root",
        str(tmp_path / "evaluations"),
        "--log-dir",
        str(tmp_path / "logs"),
        "--python",
        "python",
        *extra,
    ]


def test_dry_run_prints_every_command_without_writing(tmp_path, capsys, monkeypatch):
    def forbidden(*_args, **_kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("dry run must not execute subprocesses or contact endpoints")

    monkeypatch.setattr(suite.subprocess, "run", forbidden)
    monkeypatch.setattr(suite, "assert_model_served", forbidden)
    bench = _benchmark(tmp_path)
    code = suite.main(_argv(tmp_path, bench, "--models", "tomasonjo_text2cypher8b", "--dry-run"))
    assert code == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    predict = [line for line in lines if "generate_text2cypher_predictions.py" in line]
    evaluate = [line for line in lines if "evaluate_benchmark_predictions.py" in line]
    assert len(predict) == len(evaluate) == len(suite.all_condition_ids())
    assert sum("--prompt-format pipe_standard" in line for line in predict) == 6
    assert sum("--prompt-format pipe_governed" in line for line in predict) == 1
    assert sum("--prompt-format native_tomasonjo_llama3" in line for line in predict) == 1
    for seed in (13, 17, 23):
        assert any(f"--few-shot-mode random_same_category --few-shot-seed {seed}" in line for line in predict)
    assert any("--few-shot-mode scored_no_signature" in line and "--few-shot-exclude-signature-match" in line for line in predict)
    assert all("--provider vllm" in line for line in predict)
    assert all(
        "--config finbench=configs/finbench_full.yaml --config snb=configs/snb_full.yaml" in line
        for line in evaluate
    )
    assert f"{PREFIX}_downstream_tomasonjo_text2cypher8b" in out
    assert f"{PREFIX}_control_tomasonjo_text2cypher8b_ordered_logged" in out
    assert f"{PREFIX}_promptfmt_tomasonjo_text2cypher8b_zero_native" in out
    assert not (tmp_path / "evaluations").exists()
    assert not (tmp_path / "logs").exists()


def test_dry_run_launch_renders_lora_command_with_distinct_base_name(tmp_path, capsys):
    bench = _benchmark(tmp_path)
    suite.main(
        _argv(
            tmp_path,
            bench,
            "--models",
            "neo4j_gemma2_text2cypher_lora",
            "--conditions",
            "zero_native",
            "--dry-run",
            "--launch",
            "--gpu-ids",
            "2",
        )
    )
    out = capsys.readouterr().out
    launch = next(line for line in out.splitlines() if "launch:" in line)
    assert "SERVED_MODEL_NAME=base-google-gemma-2-9b-it" in launch
    assert "--lora-modules neo4j_gemma2_text2cypher_lora=neo4j/text2cypher-gemma-2-9b-it-finetuned-2024v1" in launch
    assert "--max-lora-rank 64" in launch
    assert "--model neo4j_gemma2_text2cypher_lora" in out
    assert "--prompt-format native_neo4j_gemma2_2024" in out


def test_openai_dry_run_uses_provider_and_never_launches(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret-value")
    bench = _benchmark(tmp_path)
    code = suite.main(
        _argv(tmp_path, bench, "--models", "gpt6_luna", "--dry-run", "--launch", "--gpu-ids", "2,3")
    )
    assert code == 0
    out = capsys.readouterr().out
    predict = [line for line in out.splitlines() if "generate_text2cypher_predictions.py" in line]
    assert predict and all("--provider openai" in line for line in predict)
    assert all("--base-url https://api.openai.com/v1" in line for line in predict)
    assert all("--model gpt-6-luna" in line and "--no-temperature" in line for line in predict)
    assert "serve_qwen_vllm.sh" not in out
    assert "launch:" not in out
    assert "never launched" in out
    assert "sk-test-secret-value" not in out
    assert not any("native" in line for line in predict)

    manifest = suite.load_model_manifest(MANIFEST)
    model = manifest.model("gpt6_luna")
    ctx = suite.SuiteContext(
        benchmark=bench,
        split="test",
        prefix=PREFIX,
        output_root=tmp_path / "evaluations",
        log_dir=tmp_path / "logs",
        python="python",
        schemas=list(suite.DEFAULT_SCHEMAS),
        graph_configs=list(suite.DEFAULT_GRAPH_CONFIGS),
    )
    condition = suite.conditions_for_model(model)[0]
    metadata = suite.condition_metadata(
        ctx=ctx,
        manifest=manifest,
        model=model,
        condition=condition,
        run_dir=tmp_path / "run",
        base_url=model.base_url,
        provenance=suite.benchmark_provenance(ctx),
        commands={"predict": suite.prediction_command(ctx, model, condition, tmp_path / "run", model.base_url)},
    )
    assert metadata["provider"] == "openai"
    assert metadata["hosted"] is True and metadata["local_weights"] is False
    assert metadata["launched_by_suite"] is False
    assert "sk-test-secret-value" not in json.dumps(metadata)
    with pytest.raises(ValueError, match="never launched"):
        suite.launch_spec(manifest, model, gpu_ids="2", port=8000)


def test_hosted_model_refuses_private_graph_before_contacting_endpoint(tmp_path, monkeypatch):
    def forbidden(*_args, **_kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("endpoint contacted for a private graph")

    monkeypatch.setattr(suite, "assert_model_served", forbidden)
    monkeypatch.setattr(suite.subprocess, "run", _fake_runner([])[0])
    bench = _benchmark(tmp_path, graph_profile="acme_private")
    code = suite.main(_argv(tmp_path, bench, "--models", "gpt6_luna"))
    assert code == suite.EXIT_MODEL_FAILURE
    failures = (tmp_path / "logs" / f"{PREFIX}_downstream_suite_failures.jsonl").read_text().splitlines()
    assert json.loads(failures[0])["stage"] == "public_graph_guard"


def _fake_runner(calls: list[list[str]], *, eval_exit: dict[str, int] | None = None):
    eval_exit = eval_exit or {}

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["git", "rev-parse"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="deadbeef\n", stderr="")
        if cmd[:2] == ["git", "status"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        calls.append(list(cmd))
        if "scripts/evaluate_benchmark_predictions.py" in cmd:
            summary = Path(cmd[cmd.index("--summary-output") + 1])
            run_dir = summary.parent.name
            code = next((value for key, value in eval_exit.items() if key in run_dir), 0)
            summary.parent.mkdir(parents=True, exist_ok=True)
            summary.write_text(
                json.dumps(
                    {
                        "overall": {"n": 2, "execution_accuracy": 0.5},
                        "run_validity": {"valid": code == 0, "prediction_failure_rate": 0.0 if code == 0 else 1.0},
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(cmd, code)
        return subprocess.CompletedProcess(cmd, 0)

    return fake_run, calls


def test_preflight_failure_stops_model_queue(tmp_path, monkeypatch):
    calls: list[list[str]] = []
    fake_run, _ = _fake_runner(calls)
    monkeypatch.setattr(suite.subprocess, "run", fake_run)

    def preflight(base_url, model, **kwargs):
        if model == "tomasonjo/text2cypher-demo-16bit":
            raise RuntimeError(f"Model {model!r} is not served at {base_url}; endpoint reports ['other']")
        return [model]

    monkeypatch.setattr(suite, "assert_model_served", preflight)
    bench = _benchmark(tmp_path)

    code = suite.main(
        _argv(tmp_path, bench, "--models", "tomasonjo_text2cypher8b,qwen25_coder7b")
    )
    assert code == suite.EXIT_MODEL_FAILURE
    assert calls == []  # no prediction/evaluation command ran, and the next model did not start
    failure = json.loads(
        (tmp_path / "logs" / f"{PREFIX}_downstream_suite_failures.jsonl").read_text().splitlines()[0]
    )
    assert failure["stage"] == "preflight" and failure["model_slug"] == "tomasonjo_text2cypher8b"
    assert not list((tmp_path / "evaluations").glob("*tomasonjo*"))


def test_continue_on_model_failure_runs_next_model(tmp_path, monkeypatch):
    calls: list[list[str]] = []
    fake_run, _ = _fake_runner(calls)
    monkeypatch.setattr(suite.subprocess, "run", fake_run)

    def preflight(base_url, model, **kwargs):
        if model == "tomasonjo/text2cypher-demo-16bit":
            raise RuntimeError("404")
        return [model]

    monkeypatch.setattr(suite, "assert_model_served", preflight)
    bench = _benchmark(tmp_path)
    code = suite.main(
        _argv(
            tmp_path,
            bench,
            "--models",
            "tomasonjo_text2cypher8b,qwen25_coder7b",
            "--continue-on-model-failure",
        )
    )
    assert code == suite.EXIT_MODEL_FAILURE
    models_called = {cmd[cmd.index("--model") + 1] for cmd in calls if "--model" in cmd}
    assert models_called == {"Qwen/Qwen2.5-Coder-7B-Instruct"}
    assert len(calls) == 2 * len(suite.conditions_for_model(suite.load_model_manifest(MANIFEST).model("qwen25_coder7b")))

    zero_dir = tmp_path / "evaluations" / f"{PREFIX}_downstream_qwen25_coder7b"
    metadata = json.loads((zero_dir / "metadata.json").read_text())
    assert metadata["status"] == "complete"
    assert metadata["prompt_format"] == "pipe_standard"
    assert metadata["provider"] == "vllm"
    assert metadata["served_model_name"] == "Qwen/Qwen2.5-Coder-7B-Instruct"
    assert metadata["git_revision"] == "deadbeef"
    assert metadata["benchmark_manifest_declared_sha256"] == "declared"
    assert metadata["split_sha256"] and metadata["benchmark_manifest_sha256"]
    seed_dir = tmp_path / "evaluations" / f"{PREFIX}_control_qwen25_coder7b_random_seed17"
    seed_meta = json.loads((seed_dir / "metadata.json").read_text())
    assert seed_meta["few_shot_mode"] == "random_same_category" and seed_meta["few_shot_seed"] == 17
    index = json.loads((tmp_path / "evaluations" / f"{PREFIX}_suite_index.json").read_text())
    assert index["models"]["tomasonjo_text2cypher8b"]["status"] == "failed"
    assert index["models"]["qwen25_coder7b"]["status"] == "complete"
    assert "--zero-run-dir" in index["fewshot_control_summary_command"]


def test_evaluator_invalid_run_exit_stops_model_queue(tmp_path, monkeypatch):
    calls: list[list[str]] = []
    fake_run, _ = _fake_runner(calls, eval_exit={"_downstream_qwen25_coder7b": 3})
    monkeypatch.setattr(suite.subprocess, "run", fake_run)
    monkeypatch.setattr(suite, "assert_model_served", lambda base_url, model, **kwargs: [model])
    bench = _benchmark(tmp_path)
    code = suite.main(_argv(tmp_path, bench, "--models", "qwen25_coder7b"))
    assert code == suite.EXIT_MODEL_FAILURE
    assert len(calls) == 2  # one prediction + one evaluation, then the queue stopped
    metadata = json.loads(
        (tmp_path / "evaluations" / f"{PREFIX}_downstream_qwen25_coder7b" / "metadata.json").read_text()
    )
    assert metadata["status"] == "invalid"
    failure = json.loads(
        (tmp_path / "logs" / f"{PREFIX}_downstream_suite_failures.jsonl").read_text().splitlines()[0]
    )
    assert "INVALID" in failure["reason"]


def test_prediction_failure_stops_model_queue(tmp_path, monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        if cmd[0] == "git":
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 1)

    monkeypatch.setattr(suite.subprocess, "run", fake_run)
    monkeypatch.setattr(suite, "assert_model_served", lambda base_url, model, **kwargs: [model])
    bench = _benchmark(tmp_path)
    code = suite.main(_argv(tmp_path, bench, "--models", "qwen25_coder7b"))
    assert code == suite.EXIT_MODEL_FAILURE
    assert len(calls) == 1 and "generate_text2cypher_predictions.py" in calls[0][1]


def test_launch_requires_explicit_gpu_ids(tmp_path):
    bench = _benchmark(tmp_path)
    with pytest.raises(SystemExit, match="--gpu-ids"):
        suite.main(_argv(tmp_path, bench, "--models", "qwen25_coder7b", "--launch"))
