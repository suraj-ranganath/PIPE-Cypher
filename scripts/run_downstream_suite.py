#!/usr/bin/env python3
"""Run the downstream Text2Cypher suite for models listed in a model manifest.

For every selected model the suite

1. resolves an endpoint (``--endpoint slug=URL`` > manifest ``base_url`` >
   ``--base-url``); it starts vLLM itself only with ``--launch`` (local models
   only, explicit ``--gpu-ids``), using the manifest's documented command
   template;
2. runs a preflight against the endpoint's ``/models`` route (the request name,
   i.e. the LoRA alias for adapters, must be served);
3. runs the conditions
     zero-shot  x {pipe_standard, pipe_governed, native (if documented)}
     few-shot   (pipe_standard) x {ordered_same_category, scored_no_signature,
                                   random_same_category seeds 13/17/23}
   through ``scripts/generate_text2cypher_predictions.py`` and
   ``scripts/evaluate_benchmark_predictions.py`` (both graph configs);
4. writes ``artifacts/evaluations/<run dir>/metadata.json`` for every condition.

A preflight failure, a failed prediction run, or an evaluator invalid-run exit
(code 3) stops that model's queue immediately. The suite moves on to the next
model only with ``--continue-on-model-failure``; otherwise it exits with code
4. ``--dry-run`` prints every command without touching the filesystem.

Run-directory names stay parseable by ``pipecypher.downstream_model_transfer``:

* zero-shot pipe_standard   ``<prefix>_downstream_<slug>``
  (``_control_slug_from_zero_run`` -> ``<slug>``)
* few-shot controls         ``<prefix>_control_<slug>_{ordered_logged,
  scored_no_signature,random_seed13,random_seed17,random_seed23}``
  (``_parse_control_run_id`` -> ``(<slug>, mode)``)
* prompt-format variants    ``<prefix>_promptfmt_<slug>_{zero_pipe_governed,zero_native}``
  (ignored by the few-shot control parsers by design)

Hosted providers (e.g. the gpt-6-luna reference row) are never launched, may
only see public graphs, and read their API key from the environment; the key is
never placed in commands, logs, or metadata.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import yaml

from pipecypher.downstream_model_transfer import (
    _control_slug_from_zero_run,
    _parse_control_run_id,
)
from pipecypher.llm import PROVIDERS, assert_model_served, served_model_ids
from pipecypher.prompt_formats import (
    UnknownPromptFormatError,
    get_prompt_format,
)

MANIFEST_KIND = "pipecypher_downstream_model_manifest"
EVALUATOR_INVALID_RUN_EXIT = 3
EXIT_MODEL_FAILURE = 4
DEFAULT_MANIFEST = "configs/downstream_models_naacl2027.yaml"
DEFAULT_SCHEMAS = ("finbench=configs/schema_finbench.json", "snb=configs/schema_snb.json")
DEFAULT_GRAPH_CONFIGS = ("finbench=configs/finbench_full.yaml", "snb=configs/snb_full.yaml")
RANDOM_SEEDS = (13, 17, 23)
RESERVED_NAME_TOKENS = ("downstream", "control", "promptfmt")

FAMILIES = {"general", "code", "text2cypher", "frontier (hosted)"}
TIERS = {"core", "extended", "reference"}
NATIVE_STATUSES = {
    "documented_model_card",
    "documented_official_companion",
    "none_documented",
    "not_applicable",
}
SYSTEM_MESSAGE_MODES = {"separate", "merge"}

TOP_LEVEL_KEYS = {
    "manifest_kind",
    "manifest_version",
    "title",
    "verified_on",
    "verification_method",
    "hardware",
    "defaults",
    "launch",
    "models",
}
DEFAULT_KEYS = {
    "provider",
    "port",
    "dtype",
    "max_model_len",
    "quantization",
    "tensor_parallel_size",
    "gpu_memory_utilization",
    "system_message_mode",
    "base_vllm_args",
}
LAUNCH_KEYS = {"serve_script", "command_template", "health_timeout_sec"}
HARDWARE_KEYS = {"host", "gpu", "gpu_memory_gb"}
MODEL_REQUIRED_KEYS = {
    "slug",
    "tier",
    "hf_id",
    "served_model_name",
    "family",
    "lineage",
    "tuning",
    "license_gated",
    "system_message_mode",
    "native_prompt_format",
    "native_format_status",
    "gpu_memory_estimate_gb",
    "gpus_required",
}
MODEL_OPTIONAL_KEYS = {
    "hf_sha",
    "upstream_hf_id",
    "serve_model",
    "prepare_command",
    "lora",
    "is_generator",
    "license",
    "vllm",
    "weights_gb",
    "alternatives",
    "notes",
    "provider",
    "base_url",
    "hosted",
    "public_graphs_only",
    "allowed_graph_profiles",
    "send_temperature",
    "reasoning_effort",
}
LORA_KEYS = {
    "alias",
    "adapter_hf_id",
    "base_model",
    "base_served_model_name",
    "rank",
    "max_lora_rank",
    "use_rslora",
}
VLLM_KEYS = {
    "dtype",
    "max_model_len",
    "quantization",
    "tensor_parallel_size",
    "gpu_memory_utilization",
    "extra_args",
}


class ManifestError(ValueError):
    """Raised when the downstream model manifest is malformed."""


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LoraSpec:
    alias: str
    adapter_hf_id: str
    base_model: str
    base_served_model_name: str
    rank: int
    max_lora_rank: int
    use_rslora: bool = False


@dataclass(frozen=True)
class VllmSpec:
    dtype: str
    max_model_len: int
    quantization: str | None
    tensor_parallel_size: int
    gpu_memory_utilization: float
    extra_args: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModelSpec:
    slug: str
    tier: str
    hf_id: str | None
    served_model_name: str
    family: str
    lineage: str
    tuning: str
    license_gated: bool
    system_message_mode: str
    native_prompt_format: str | None
    native_format_status: str
    gpu_memory_estimate_gb: float
    gpus_required: int
    provider: str = "vllm"
    base_url: str | None = None
    hosted: bool = False
    public_graphs_only: bool = False
    allowed_graph_profiles: tuple[str, ...] = ()
    send_temperature: bool = True
    reasoning_effort: str | None = None
    is_generator: bool = False
    serve_model: str | None = None
    lora: LoraSpec | None = None
    vllm: VllmSpec | None = None
    hf_sha: str | None = None
    upstream_hf_id: str | None = None
    license: str | None = None
    weights_gb: float | None = None
    prepare_command: str | None = None
    notes: str = ""

    @property
    def local_weights(self) -> bool:
        return not self.hosted

    @property
    def base_served_model_name(self) -> str:
        return self.lora.base_served_model_name if self.lora else self.served_model_name

    @property
    def display_model(self) -> str:
        return self.hf_id or self.served_model_name


@dataclass(frozen=True)
class ModelManifest:
    path: Path
    sha256: str
    defaults: dict[str, Any]
    launch: dict[str, Any]
    models: tuple[ModelSpec, ...]

    def model(self, slug: str) -> ModelSpec:
        for model in self.models:
            if model.slug == slug:
                return model
        raise ManifestError(
            f"unknown model slug {slug!r}; manifest has {', '.join(m.slug for m in self.models)}"
        )


def load_model_manifest(path: str | os.PathLike[str]) -> ModelManifest:
    """Load and strictly validate a downstream model manifest (not a RunConfig)."""

    manifest_path = Path(path)
    raw_bytes = manifest_path.read_bytes()
    data = yaml.safe_load(raw_bytes.decode("utf-8")) or {}
    if not isinstance(data, dict):
        raise ManifestError("model manifest must be a YAML mapping")
    if data.get("manifest_kind") != MANIFEST_KIND:
        raise ManifestError(
            f"{manifest_path} is not a downstream model manifest "
            f"(expected manifest_kind: {MANIFEST_KIND})"
        )
    _reject_unknown(data, TOP_LEVEL_KEYS, "manifest")
    defaults = dict(data.get("defaults") or {})
    _reject_unknown(defaults, DEFAULT_KEYS, "defaults")
    launch = dict(data.get("launch") or {})
    _reject_unknown(launch, LAUNCH_KEYS, "launch")
    _reject_unknown(dict(data.get("hardware") or {}), HARDWARE_KEYS, "hardware")
    raw_models = data.get("models")
    if not isinstance(raw_models, list) or not raw_models:
        raise ManifestError("manifest must list at least one model under `models`")

    models: list[ModelSpec] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_models):
        if not isinstance(raw, dict):
            raise ManifestError(f"models[{index}] must be a mapping")
        model = _parse_model(raw, defaults, index)
        if model.slug in seen:
            raise ManifestError(f"duplicate model slug {model.slug!r}")
        seen.add(model.slug)
        models.append(model)
    return ModelManifest(
        path=manifest_path,
        sha256=hashlib.sha256(raw_bytes).hexdigest(),
        defaults=defaults,
        launch=launch,
        models=tuple(models),
    )


def _reject_unknown(data: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ManifestError(f"unknown key(s) in {where}: {', '.join(unknown)}")


def validate_slug(slug: str) -> None:
    if not re.fullmatch(r"[a-z0-9]+(?:_[a-z0-9]+)*", slug or ""):
        raise ManifestError(f"model slug {slug!r} must be lowercase snake_case")
    tokens = slug.split("_")
    for reserved in RESERVED_NAME_TOKENS:
        if reserved in tokens:
            raise ManifestError(
                f"model slug {slug!r} may not contain the run-directory marker {reserved!r}"
            )


def _parse_model(raw: dict[str, Any], defaults: dict[str, Any], index: int) -> ModelSpec:
    where = f"models[{index}]"
    _reject_unknown(raw, MODEL_REQUIRED_KEYS | MODEL_OPTIONAL_KEYS, where)
    missing = sorted(key for key in MODEL_REQUIRED_KEYS if key not in raw)
    if missing:
        raise ManifestError(f"{where} missing required key(s): {', '.join(missing)}")
    slug = str(raw["slug"])
    validate_slug(slug)
    where = f"model {slug}"

    provider = str(raw.get("provider") or defaults.get("provider") or "vllm")
    if provider not in PROVIDERS:
        raise ManifestError(f"{where}: provider must be one of {PROVIDERS}")
    hosted = bool(raw.get("hosted", False))
    if (provider != "vllm") != hosted:
        raise ManifestError(f"{where}: hosted must be true exactly when provider is not vllm")
    if raw["tier"] not in TIERS:
        raise ManifestError(f"{where}: tier must be one of {sorted(TIERS)}")
    if raw["family"] not in FAMILIES:
        raise ManifestError(f"{where}: family must be one of {sorted(FAMILIES)}")
    system_mode = str(raw["system_message_mode"])
    if system_mode not in SYSTEM_MESSAGE_MODES:
        raise ManifestError(f"{where}: system_message_mode must be separate or merge")

    lora = None
    if raw.get("lora"):
        lora_raw = dict(raw["lora"])
        _reject_unknown(lora_raw, LORA_KEYS, f"{where}.lora")
        lora_missing = sorted(LORA_KEYS - {"use_rslora"} - set(lora_raw))
        if lora_missing:
            raise ManifestError(f"{where}.lora missing key(s): {', '.join(lora_missing)}")
        lora = LoraSpec(
            alias=str(lora_raw["alias"]),
            adapter_hf_id=str(lora_raw["adapter_hf_id"]),
            base_model=str(lora_raw["base_model"]),
            base_served_model_name=str(lora_raw["base_served_model_name"]),
            rank=int(lora_raw["rank"]),
            max_lora_rank=int(lora_raw["max_lora_rank"]),
            use_rslora=bool(lora_raw.get("use_rslora", False)),
        )
        if lora.alias != raw["served_model_name"]:
            raise ManifestError(
                f"{where}: requests must use the LoRA alias; served_model_name "
                f"{raw['served_model_name']!r} != lora.alias {lora.alias!r}"
            )
        if lora.base_served_model_name == lora.alias:
            raise ManifestError(
                f"{where}: base_served_model_name must differ from the LoRA alias, otherwise "
                "requests can silently hit the untuned base model"
            )
        if raw.get("serve_model") != lora.base_model:
            raise ManifestError(f"{where}: serve_model must equal lora.base_model")
        if lora.max_lora_rank < lora.rank:
            raise ManifestError(f"{where}: max_lora_rank must be >= adapter rank")

    vllm = None
    if hosted:
        if not raw.get("base_url"):
            raise ManifestError(f"{where}: hosted models need base_url")
        if raw.get("vllm") or raw.get("lora") or raw.get("serve_model"):
            raise ManifestError(f"{where}: hosted models cannot declare vllm, lora, or serve_model")
        if not raw.get("public_graphs_only"):
            raise ManifestError(f"{where}: hosted models must set public_graphs_only: true")
        if not raw.get("allowed_graph_profiles"):
            raise ManifestError(f"{where}: hosted models must list allowed_graph_profiles")
    else:
        vllm_raw = raw.get("vllm")
        if not isinstance(vllm_raw, dict):
            raise ManifestError(f"{where}: local models need a vllm block")
        _reject_unknown(vllm_raw, VLLM_KEYS, f"{where}.vllm")
        if not raw.get("serve_model"):
            raise ManifestError(f"{where}: local models need serve_model")
        vllm = VllmSpec(
            dtype=str(vllm_raw.get("dtype", defaults.get("dtype", "bfloat16"))),
            max_model_len=int(vllm_raw.get("max_model_len", defaults.get("max_model_len", 4096))),
            quantization=vllm_raw.get("quantization", defaults.get("quantization")),
            tensor_parallel_size=int(
                vllm_raw.get("tensor_parallel_size", defaults.get("tensor_parallel_size", 1))
            ),
            gpu_memory_utilization=float(
                vllm_raw.get(
                    "gpu_memory_utilization", defaults.get("gpu_memory_utilization", 0.88)
                )
            ),
            extra_args=tuple(str(item) for item in vllm_raw.get("extra_args") or ()),
        )
        if vllm.tensor_parallel_size != int(raw["gpus_required"]):
            raise ManifestError(f"{where}: gpus_required must equal vllm.tensor_parallel_size")
        batched = _flag_value(list(defaults.get("base_vllm_args") or ()), "--max-num-batched-tokens")
        if batched is not None and int(batched) < vllm.max_model_len:
            raise ManifestError(
                f"{where}: max_model_len {vllm.max_model_len} exceeds --max-num-batched-tokens {batched}"
            )
        if not raw.get("hf_id"):
            raise ManifestError(f"{where}: local models need hf_id")

    native = raw.get("native_prompt_format")
    status = str(raw["native_format_status"])
    if status not in NATIVE_STATUSES:
        raise ManifestError(f"{where}: native_format_status must be one of {sorted(NATIVE_STATUSES)}")
    if native:
        try:
            fmt = get_prompt_format(str(native))
        except UnknownPromptFormatError as exc:
            raise ManifestError(f"{where}: {exc}") from exc
        if not str(native).startswith("native_"):
            raise ManifestError(f"{where}: native_prompt_format must name a native_* format")
        ids = {raw.get("hf_id"), lora.adapter_hf_id if lora else None}
        if not ids & set(fmt.model_hf_ids):
            raise ManifestError(
                f"{where}: {native} documents {', '.join(fmt.model_hf_ids)}, not {raw.get('hf_id')}"
            )
        if not status.startswith("documented_"):
            raise ManifestError(f"{where}: native format set but native_format_status is {status}")
        if hosted:
            raise ManifestError(f"{where}: hosted models cannot use native checkpoint formats")
    else:
        if status.startswith("documented_"):
            raise ManifestError(f"{where}: {status} requires native_prompt_format")
        if raw["family"] == "text2cypher" and status != "none_documented":
            raise ManifestError(
                f"{where}: Text2Cypher checkpoints without a native format must say none_documented"
            )

    return ModelSpec(
        slug=slug,
        tier=str(raw["tier"]),
        hf_id=raw.get("hf_id"),
        served_model_name=str(raw["served_model_name"]),
        family=str(raw["family"]),
        lineage=str(raw["lineage"]),
        tuning=str(raw["tuning"]),
        license_gated=bool(raw["license_gated"]),
        system_message_mode=system_mode,
        native_prompt_format=str(native) if native else None,
        native_format_status=status,
        gpu_memory_estimate_gb=float(raw["gpu_memory_estimate_gb"]),
        gpus_required=int(raw["gpus_required"]),
        provider=provider,
        base_url=raw.get("base_url"),
        hosted=hosted,
        public_graphs_only=bool(raw.get("public_graphs_only", False)),
        allowed_graph_profiles=tuple(str(item) for item in raw.get("allowed_graph_profiles") or ()),
        send_temperature=bool(raw.get("send_temperature", True)),
        reasoning_effort=raw.get("reasoning_effort"),
        is_generator=bool(raw.get("is_generator", False)),
        serve_model=raw.get("serve_model"),
        lora=lora,
        vllm=vllm,
        hf_sha=raw.get("hf_sha"),
        upstream_hf_id=raw.get("upstream_hf_id"),
        license=raw.get("license"),
        weights_gb=raw.get("weights_gb"),
        prepare_command=raw.get("prepare_command"),
        notes=str(raw.get("notes") or ""),
    )


def _flag_value(args: list[str], flag: str) -> str | None:
    if flag in args:
        position = args.index(flag)
        if position + 1 < len(args):
            return args[position + 1]
    return None


# ---------------------------------------------------------------------------
# Conditions and run-directory naming
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Condition:
    id: str
    shot: str  # "zero_shot" or "few_shot"; also the artifact file prefix
    prompt_format: str
    dir_kind: str  # downstream | promptfmt | control
    dir_suffix: str = ""
    few_shot_mode: str | None = None
    few_shot_seed: int | None = None
    exclude_signature_match: bool = False


def all_condition_ids() -> list[str]:
    return [
        "zero_pipe_standard",
        "zero_pipe_governed",
        "zero_native",
        "fewshot_ordered",
        "fewshot_scored_no_signature",
        *[f"fewshot_random_seed{seed}" for seed in RANDOM_SEEDS],
    ]


def conditions_for_model(model: ModelSpec, selected: set[str] | None = None) -> list[Condition]:
    conditions = [
        Condition("zero_pipe_standard", "zero_shot", "pipe_standard", "downstream"),
        Condition("zero_pipe_governed", "zero_shot", "pipe_governed", "promptfmt", "zero_pipe_governed"),
    ]
    if model.native_prompt_format:
        conditions.append(
            Condition("zero_native", "zero_shot", model.native_prompt_format, "promptfmt", "zero_native")
        )
    conditions.append(
        Condition(
            "fewshot_ordered",
            "few_shot",
            "pipe_standard",
            "control",
            "ordered_logged",
            few_shot_mode="ordered_same_category",
            few_shot_seed=13,
        )
    )
    conditions.append(
        Condition(
            "fewshot_scored_no_signature",
            "few_shot",
            "pipe_standard",
            "control",
            "scored_no_signature",
            few_shot_mode="scored_no_signature",
            few_shot_seed=13,
            exclude_signature_match=True,
        )
    )
    for seed in RANDOM_SEEDS:
        conditions.append(
            Condition(
                f"fewshot_random_seed{seed}",
                "few_shot",
                "pipe_standard",
                "control",
                f"random_seed{seed}",
                few_shot_mode="random_same_category",
                few_shot_seed=seed,
            )
        )
    if selected is not None:
        conditions = [condition for condition in conditions if condition.id in selected]
    return conditions


def validate_prefix(prefix: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*(?:_[A-Za-z0-9.-]+)*", prefix or ""):
        raise SystemExit(f"--prefix {prefix!r} must be a filesystem-safe identifier")
    tokens = prefix.split("_")
    for reserved in RESERVED_NAME_TOKENS:
        if reserved in tokens:
            raise SystemExit(f"--prefix may not contain the run-directory marker {reserved!r}")


def run_dir_name(prefix: str, slug: str, condition: Condition) -> str:
    if condition.dir_kind == "downstream":
        return f"{prefix}_downstream_{slug}"
    return f"{prefix}_{condition.dir_kind}_{slug}_{condition.dir_suffix}"


_CONTROL_MODE_TO_CONDITION = {
    "ordered": "fewshot_ordered",
    "scored_no_signature": "fewshot_scored_no_signature",
    **{f"random_seed{seed}": f"fewshot_random_seed{seed}" for seed in RANDOM_SEEDS},
}


def parse_run_dir_name(name: str) -> tuple[str, str, str] | None:
    """Return ``(prefix, slug, condition_id)`` for a suite run directory name."""

    if "_control_" in name:
        parsed = _parse_control_run_id(name)
        if not parsed:
            return None
        slug, mode = parsed
        return name.split("_control_", 1)[0], slug, _CONTROL_MODE_TO_CONDITION[mode]
    if "_promptfmt_" in name:
        prefix, body = name.split("_promptfmt_", 1)
        for condition_id in ("zero_pipe_governed", "zero_native"):
            if body.endswith("_" + condition_id):
                return prefix, body[: -len(condition_id) - 1], condition_id
        return None
    if "_downstream_" in name:
        return name.split("_downstream_", 1)[0], _control_slug_from_zero_run(name), "zero_pipe_standard"
    return None


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@dataclass
class SuiteContext:
    benchmark: Path
    split: str
    prefix: str
    output_root: Path
    log_dir: Path
    python: str
    schemas: list[str]
    graph_configs: list[str]
    few_shot_k: int = 5
    few_shot_max_question_sim: float = 0.90
    max_consecutive_errors: int = 5
    max_prediction_failure_rate: float = 0.01
    text_metrics: bool = False
    temperature: float = 0.0
    max_tokens: int = 512
    schema_max_items: int = 70
    timeout_sec: int = 180
    limit: int = 0
    dry_run: bool = False
    skip_existing: bool = False
    overwrite: bool = False
    continue_on_model_failure: bool = False
    launch: bool = False
    gpu_ids: str = ""
    port: int = 8000
    default_base_url: str = "http://localhost:8000/v1"
    endpoints: dict[str, str] = field(default_factory=dict)
    conda_env: str = ""

    @property
    def few_shot_pool(self) -> Path:
        return self.benchmark / "train.jsonl"


def prediction_command(
    ctx: SuiteContext, model: ModelSpec, condition: Condition, out_dir: Path, base_url: str
) -> list[str]:
    cmd = [
        ctx.python,
        "scripts/generate_text2cypher_predictions.py",
        "--benchmark",
        str(ctx.benchmark),
        "--split",
        ctx.split,
    ]
    for item in ctx.schemas:
        cmd += ["--schema", item]
    cmd += [
        "--output",
        str(out_dir / f"{condition.shot}_predictions.jsonl"),
        "--base-url",
        base_url,
        "--model",
        model.served_model_name,
        "--provider",
        model.provider,
        "--system-message-mode",
        model.system_message_mode,
        "--prompt-format",
        condition.prompt_format,
        "--max-consecutive-errors",
        str(ctx.max_consecutive_errors),
        "--timeout-sec",
        str(ctx.timeout_sec),
        "--temperature",
        str(ctx.temperature),
        "--max-tokens",
        str(ctx.max_tokens),
        "--schema-max-items",
        str(ctx.schema_max_items),
    ]
    if not model.send_temperature:
        cmd.append("--no-temperature")
    if model.reasoning_effort:
        cmd += ["--reasoning-effort", str(model.reasoning_effort)]
    if condition.shot == "few_shot":
        cmd += [
            "--few-shot",
            str(ctx.few_shot_pool),
            "--few-shot-k",
            str(ctx.few_shot_k),
            "--few-shot-mode",
            str(condition.few_shot_mode),
            "--few-shot-seed",
            str(condition.few_shot_seed),
            "--few-shot-max-question-sim",
            str(ctx.few_shot_max_question_sim),
            "--few-shot-log",
            str(out_dir / "few_shot_selection.jsonl"),
        ]
        if condition.exclude_signature_match:
            cmd.append("--few-shot-exclude-signature-match")
    else:
        cmd += ["--few-shot-k", "0"]
    if ctx.limit:
        cmd += ["--limit", str(ctx.limit)]
    return cmd


def evaluation_command(ctx: SuiteContext, condition: Condition, out_dir: Path) -> list[str]:
    cmd = [
        ctx.python,
        "scripts/evaluate_benchmark_predictions.py",
        "--benchmark",
        str(ctx.benchmark),
        "--split",
        ctx.split,
        "--predictions",
        str(out_dir / f"{condition.shot}_predictions.jsonl"),
    ]
    for item in ctx.graph_configs:
        cmd += ["--config", item]
    cmd += [
        "--output",
        str(out_dir / f"{condition.shot}_evaluation.jsonl"),
        "--summary-output",
        str(out_dir / f"{condition.shot}_summary.json"),
        "--max-prediction-failure-rate",
        str(ctx.max_prediction_failure_rate),
    ]
    if not ctx.text_metrics:
        cmd.append("--disable-text-metrics")
    return cmd


def vllm_args(manifest: ModelManifest, model: ModelSpec) -> list[str]:
    if model.vllm is None:
        raise ValueError(f"{model.slug} has no vLLM serving block")
    args = [str(item) for item in manifest.defaults.get("base_vllm_args") or ()]
    args += ["--dtype", model.vllm.dtype]
    if model.vllm.quantization:
        args += ["--quantization", str(model.vllm.quantization)]
    if model.lora:
        args += [
            "--enable-lora",
            "--max-lora-rank",
            str(model.lora.max_lora_rank),
            "--lora-modules",
            f"{model.lora.alias}={model.lora.adapter_hf_id}",
        ]
    args += list(model.vllm.extra_args)
    return args


def launch_spec(
    manifest: ModelManifest, model: ModelSpec, *, gpu_ids: str, port: int, conda_env: str = ""
) -> tuple[list[str], dict[str, str], str]:
    """``(argv, env_updates, rendered_template)`` for starting a local vLLM server."""

    if model.hosted or model.vllm is None:
        raise ValueError(f"{model.slug} is a hosted model and is never launched")
    serve_script = str(manifest.launch.get("serve_script") or "scripts/serve_qwen_vllm.sh")
    args = vllm_args(manifest, model)
    argv = ["bash", serve_script, str(model.serve_model), *args]
    env = {
        "CUDA_VISIBLE_DEVICES": gpu_ids,
        "PORT": str(port),
        "SERVED_MODEL_NAME": model.base_served_model_name,
        "TENSOR_PARALLEL_SIZE": str(model.vllm.tensor_parallel_size),
        "MAX_MODEL_LEN": str(model.vllm.max_model_len),
        "GPU_MEMORY_UTILIZATION": str(model.vllm.gpu_memory_utilization),
        "EXTRA_VLLM_ARGS": "",
    }
    if conda_env:
        env["CONDA_ENV"] = conda_env
    template = str(manifest.launch.get("command_template") or "")
    rendered = template.format(
        gpu_ids=shlex.quote(gpu_ids),
        port=port,
        base_served_model_name=shlex.quote(model.base_served_model_name),
        tensor_parallel_size=model.vllm.tensor_parallel_size,
        max_model_len=model.vllm.max_model_len,
        gpu_memory_utilization=model.vllm.gpu_memory_utilization,
        serve_model=shlex.quote(str(model.serve_model)),
        vllm_args=shlex.join(args),
    )
    if conda_env:
        rendered = f"CONDA_ENV={shlex.quote(conda_env)} {rendered}"
    return argv, env, rendered


def resolve_base_url(ctx: SuiteContext, model: ModelSpec) -> str:
    if model.slug in ctx.endpoints:
        return ctx.endpoints[model.slug]
    if model.base_url:
        return str(model.base_url)
    if ctx.launch and not model.hosted:
        return f"http://localhost:{ctx.port}/v1"
    return ctx.default_base_url


# ---------------------------------------------------------------------------
# Provenance helpers
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def benchmark_provenance(ctx: SuiteContext) -> dict[str, Any]:
    manifest_path = ctx.benchmark / "manifest.json"
    split_path = ctx.benchmark / f"{ctx.split}.jsonl"
    declared = None
    if manifest_path.exists():
        declared = json.loads(manifest_path.read_text(encoding="utf-8")).get("sha256")
    return {
        "benchmark": str(ctx.benchmark),
        "benchmark_manifest": str(manifest_path),
        "benchmark_manifest_sha256": _sha256_file(manifest_path),
        "benchmark_manifest_declared_sha256": declared,
        "split": ctx.split,
        "split_path": str(split_path),
        "split_sha256": _sha256_file(split_path),
        "split_rows": _count_lines(split_path),
        "few_shot_pool": str(ctx.few_shot_pool),
        "few_shot_pool_sha256": _sha256_file(ctx.few_shot_pool),
    }


def _count_lines(path: Path) -> int | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def benchmark_graph_profiles(ctx: SuiteContext) -> set[str]:
    profiles: set[str] = set()
    for path in (ctx.benchmark / f"{ctx.split}.jsonl", ctx.few_shot_pool):
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    profiles.add(str(json.loads(line).get("graph_profile")))
    return profiles


def git_provenance() -> dict[str, Any]:
    info: dict[str, Any] = {"git_revision": None, "git_dirty": None}
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        info["git_revision"] = (head.stdout or "").strip() or None
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        info["git_dirty"] = bool((status.stdout or "").strip())
    except OSError:
        pass
    return info


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


@dataclass
class ModelOutcome:
    slug: str
    status: str  # complete | failed | dry_run
    failure: dict[str, Any] | None = None
    runs: dict[str, dict[str, Any]] = field(default_factory=dict)


class SuiteLogger:
    def __init__(self, ctx: SuiteContext) -> None:
        self.ctx = ctx
        self.log_path = ctx.log_dir / f"{ctx.prefix}_downstream_suite.log"
        self.failure_path = ctx.log_dir / f"{ctx.prefix}_downstream_suite_failures.jsonl"

    def info(self, message: str) -> None:
        line = f"[{_utc_now()}] {message}"
        print(line, flush=True)
        if not self.ctx.dry_run:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def failure(self, record: dict[str, Any]) -> None:
        self.info(
            "MODEL_QUEUE_STOPPED model={slug} stage={stage} reason={reason}".format(
                slug=record.get("model_slug"),
                stage=record.get("stage"),
                reason=record.get("reason"),
            )
        )
        if not self.ctx.dry_run:
            self.failure_path.parent.mkdir(parents=True, exist_ok=True)
            with self.failure_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")


def run_logged(cmd: list[str], log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"# {_utc_now()} $ {shlex.join(cmd)}\n")
        handle.flush()
        completed = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            stdout=handle,
            stderr=subprocess.STDOUT,
            env=env,
            check=False,
        )
    return int(completed.returncode)


def _tail(path: Path, lines: int = 8) -> str:
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(content[-lines:])


def condition_metadata(
    *,
    ctx: SuiteContext,
    manifest: ModelManifest,
    model: ModelSpec,
    condition: Condition,
    run_dir: Path,
    base_url: str,
    provenance: dict[str, Any],
    commands: dict[str, list[str]],
) -> dict[str, Any]:
    fmt = get_prompt_format(condition.prompt_format)
    return {
        "suite": "run_downstream_suite",
        "run_id": run_dir.name,
        "run_prefix": ctx.prefix,
        "condition": condition.id,
        "model_slug": model.slug,
        "model": model.display_model,
        "hf_id": model.hf_id,
        "hf_sha": model.hf_sha,
        "upstream_hf_id": model.upstream_hf_id,
        "served_model_name": model.served_model_name,
        "serve_model": model.serve_model,
        "lora_alias": model.lora.alias if model.lora else None,
        "lora_adapter_hf_id": model.lora.adapter_hf_id if model.lora else None,
        "base_model": model.lora.base_model if model.lora else model.serve_model,
        "base_served_model_name": model.base_served_model_name,
        "provider": model.provider,
        "hosted": model.hosted,
        "local_weights": model.local_weights,
        "public_graphs_only": model.public_graphs_only,
        "base_url": base_url,
        "model_family": model.lineage,
        "study_family": model.family,
        "tuning": model.tuning,
        "tier": model.tier,
        "is_generator": model.is_generator,
        "license_gated": model.license_gated,
        "system_message_mode": model.system_message_mode,
        "send_temperature": model.send_temperature,
        "reasoning_effort": model.reasoning_effort,
        "prompt_format": condition.prompt_format,
        "prompt_format_documented": fmt.documented,
        "prompt_format_source_url": fmt.source_url,
        "prompt_transport": fmt.transport,
        "native_format_status": model.native_format_status,
        "few_shot_k": ctx.few_shot_k if condition.shot == "few_shot" else 0,
        "few_shot_mode": condition.few_shot_mode,
        "few_shot_seed": condition.few_shot_seed,
        "few_shot_exclude_signature_match": condition.exclude_signature_match,
        "few_shot_max_question_similarity": ctx.few_shot_max_question_sim
        if condition.shot == "few_shot"
        else None,
        "temperature": ctx.temperature,
        "max_tokens": ctx.max_tokens,
        "schema_max_items": ctx.schema_max_items,
        "limit": ctx.limit or None,
        "text_metrics_disabled": not ctx.text_metrics,
        "max_prediction_failure_rate": ctx.max_prediction_failure_rate,
        "schemas": list(ctx.schemas),
        "graph_configs": list(ctx.graph_configs),
        "model_manifest": str(manifest.path),
        "model_manifest_sha256": manifest.sha256,
        "vllm": None
        if model.vllm is None
        else {
            "dtype": model.vllm.dtype,
            "max_model_len": model.vllm.max_model_len,
            "quantization": model.vllm.quantization,
            "tensor_parallel_size": model.vllm.tensor_parallel_size,
            "gpu_memory_utilization": model.vllm.gpu_memory_utilization,
            "args": vllm_args(manifest, model),
        },
        "launched_by_suite": bool(ctx.launch and not model.hosted),
        "commands": {key: shlex.join(value) for key, value in commands.items()},
        **provenance,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _existing_status(run_dir: Path, condition: Condition) -> str:
    metadata_path = run_dir / "metadata.json"
    summary_path = run_dir / f"{condition.shot}_summary.json"
    if not metadata_path.exists() or not summary_path.exists():
        return "absent"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    valid = (summary.get("run_validity") or {}).get("valid", False)
    if metadata.get("status") == "complete" and valid:
        return "complete"
    return "incomplete"


def run_model(
    ctx: SuiteContext,
    manifest: ModelManifest,
    model: ModelSpec,
    conditions: list[Condition],
    logger: SuiteLogger,
    provenance: dict[str, Any],
) -> ModelOutcome:
    outcome = ModelOutcome(slug=model.slug, status="dry_run" if ctx.dry_run else "complete")
    base_url = resolve_base_url(ctx, model)

    def fail(stage: str, reason: str, **extra: Any) -> ModelOutcome:
        outcome.status = "failed"
        outcome.failure = {
            "at_utc": _utc_now(),
            "run_prefix": ctx.prefix,
            "model_slug": model.slug,
            "served_model_name": model.served_model_name,
            "base_url": base_url,
            "stage": stage,
            "reason": reason,
            **extra,
        }
        logger.failure(outcome.failure)
        return outcome

    logger.info(
        f"MODEL {model.slug} provider={model.provider} served={model.served_model_name} "
        f"base_url={base_url} conditions={','.join(c.id for c in conditions)}"
    )
    if model.license_gated and not model.hosted:
        logger.info(f"note: {model.slug} is license-gated ({model.license}); accept terms before download")
    if model.hosted:
        logger.info(
            f"note: {model.slug} is a hosted reference model; public graphs only, key read from "
            "the environment and never recorded"
        )
        profiles = benchmark_graph_profiles(ctx)
        disallowed = sorted(profiles - set(model.allowed_graph_profiles))
        if disallowed:
            return fail(
                "public_graph_guard",
                "hosted model may only see public graphs; benchmark contains "
                + ", ".join(disallowed),
            )

    server: subprocess.Popen[bytes] | None = None
    if ctx.launch:
        if model.hosted:
            logger.info(f"{model.slug} is hosted ({model.provider}); --launch ignored, never launched")
        else:
            argv, env_updates, rendered = launch_spec(
                manifest, model, gpu_ids=ctx.gpu_ids, port=ctx.port, conda_env=ctx.conda_env
            )
            if model.prepare_command:
                logger.info(f"prepare (run once before launch): {model.prepare_command}")
            logger.info(f"launch: {rendered}")
            if not ctx.dry_run:
                gpu_count = len([item for item in ctx.gpu_ids.split(",") if item.strip()])
                if gpu_count < model.gpus_required:
                    return fail(
                        "launch",
                        f"needs {model.gpus_required} GPU(s); --gpu-ids has {gpu_count}",
                    )
                server, launch_error = start_server(
                    argv,
                    env_updates,
                    log_path=ctx.log_dir / f"{ctx.prefix}_vllm_{model.slug}.log",
                    base_url=base_url,
                    expected=model.served_model_name,
                    timeout_sec=int(manifest.launch.get("health_timeout_sec") or 1800),
                )
                if launch_error:
                    stop_server(server)
                    return fail("launch", launch_error)

    try:
        if ctx.dry_run:
            logger.info(
                f"preflight: GET {base_url}/models must list {model.served_model_name!r}"
                + (f" (provider={model.provider})" if model.hosted else "")
            )
        else:
            try:
                served = assert_model_served(base_url, model.served_model_name, provider=model.provider)
            except Exception as exc:  # noqa: BLE001 - any preflight failure stops the queue
                return fail("preflight", str(exc))
            logger.info(f"preflight_ok {model.slug} served={served}")
            if model.lora and model.base_served_model_name not in served:
                logger.info(
                    f"warning: base name {model.base_served_model_name!r} not listed; requests use "
                    f"the verified LoRA alias {model.lora.alias!r}"
                )

        for condition in conditions:
            run_dir = ctx.output_root / run_dir_name(ctx.prefix, model.slug, condition)
            predict_cmd = prediction_command(ctx, model, condition, run_dir, base_url)
            evaluate_cmd = evaluation_command(ctx, condition, run_dir)
            if ctx.dry_run:
                print(f"# {model.slug} {condition.id} -> {run_dir}")
                print(shlex.join(predict_cmd))
                print(shlex.join(evaluate_cmd))
                outcome.runs[condition.id] = {"run_dir": str(run_dir), "status": "dry_run"}
                continue

            existing = _existing_status(run_dir, condition)
            if existing == "complete":
                if ctx.skip_existing:
                    logger.info(f"skip_existing {run_dir}")
                    outcome.runs[condition.id] = {"run_dir": str(run_dir), "status": "complete"}
                    continue
                if not ctx.overwrite:
                    return fail(
                        condition.id,
                        f"{run_dir} already holds a complete run; pass --skip-existing or --overwrite",
                    )

            metadata = condition_metadata(
                ctx=ctx,
                manifest=manifest,
                model=model,
                condition=condition,
                run_dir=run_dir,
                base_url=base_url,
                provenance=provenance,
                commands={"predict": predict_cmd, "evaluate": evaluate_cmd},
            )
            metadata.update({"status": "running", "started_at_utc": _utc_now()})
            _write_json(run_dir / "metadata.json", metadata)
            logger.info(f"RUN {model.slug} {condition.id} -> {run_dir}")

            def finish(status: str, **extra: Any) -> None:
                metadata.update({"status": status, "finished_at_utc": _utc_now(), **extra})
                _write_json(run_dir / "metadata.json", metadata)
                outcome.runs[condition.id] = {"run_dir": str(run_dir), "status": status}

            predict_log = run_dir / "predict.log"
            code = run_logged(predict_cmd, predict_log)
            if code != 0:
                finish("failed", exit_codes={"predict": code})
                return fail(
                    condition.id,
                    f"prediction run exited {code} (preflight failure or consecutive request "
                    "errors); partial predictions are not a model result",
                    run_dir=str(run_dir),
                    exit_code=code,
                    log_tail=_tail(predict_log),
                )

            evaluate_log = run_dir / "evaluate.log"
            code = run_logged(evaluate_cmd, evaluate_log)
            if code == EVALUATOR_INVALID_RUN_EXIT:
                finish("invalid", exit_codes={"predict": 0, "evaluate": code})
                return fail(
                    condition.id,
                    "evaluator marked the run INVALID (prediction failure rate above "
                    f"{ctx.max_prediction_failure_rate}); not a model result",
                    run_dir=str(run_dir),
                    exit_code=code,
                    log_tail=_tail(evaluate_log),
                )
            if code != 0:
                finish("failed", exit_codes={"predict": 0, "evaluate": code})
                return fail(
                    condition.id,
                    f"evaluation exited {code}",
                    run_dir=str(run_dir),
                    exit_code=code,
                    log_tail=_tail(evaluate_log),
                )
            finish(
                "complete",
                exit_codes={"predict": 0, "evaluate": 0},
                result=_summary_headline(run_dir / f"{condition.shot}_summary.json"),
            )
    finally:
        stop_server(server)
    return outcome


def _summary_headline(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    summary = json.loads(path.read_text(encoding="utf-8"))
    overall = summary.get("overall") or {}
    keys = (
        "n",
        "execution_accuracy",
        "projected_execution_accuracy",
        "answer_f1",
        "execution_success",
        "parse_valid",
        "schema_valid",
    )
    return {
        **{key: overall.get(key) for key in keys if key in overall},
        "run_validity": summary.get("run_validity"),
    }


def start_server(
    argv: list[str],
    env_updates: dict[str, str],
    *,
    log_path: Path,
    base_url: str,
    expected: str,
    timeout_sec: int,
    poll_sec: float = 20.0,
) -> tuple[subprocess.Popen[bytes] | None, str | None]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("ab")
    server = subprocess.Popen(
        argv,
        cwd=PROJECT_ROOT,
        env={**os.environ, **env_updates},
        stdout=handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if server.poll() is not None:
            return server, f"vLLM exited with code {server.returncode} before becoming healthy (log {log_path})"
        try:
            if expected in served_model_ids(base_url, timeout_sec=10):
                return server, None
        except Exception:  # noqa: BLE001 - endpoint still starting
            pass
        time.sleep(poll_sec)
    return server, f"endpoint {base_url} did not list {expected!r} within {timeout_sec}s (log {log_path})"


def stop_server(server: subprocess.Popen[bytes] | None) -> None:
    if server is None or server.poll() is not None:
        return
    try:
        os.killpg(server.pid, signal.SIGTERM)
        server.wait(timeout=120)
    except (ProcessLookupError, PermissionError):
        return
    except subprocess.TimeoutExpired:
        os.killpg(server.pid, signal.SIGKILL)
        server.wait(timeout=30)


def write_suite_index(ctx: SuiteContext, outcomes: list[ModelOutcome]) -> Path:
    index_path = ctx.output_root / f"{ctx.prefix}_suite_index.json"
    index: dict[str, Any] = {}
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
    models = index.setdefault("models", {})
    for outcome in outcomes:
        models[outcome.slug] = {
            "status": outcome.status,
            "failure": outcome.failure,
            "runs": outcome.runs,
        }
    zero_dirs = sorted(
        run["run_dir"]
        for model in models.values()
        for condition, run in model["runs"].items()
        if condition == "zero_pipe_standard" and run["status"] == "complete"
    )
    control_dirs = sorted(
        run["run_dir"]
        for model in models.values()
        for condition, run in model["runs"].items()
        if condition.startswith("fewshot_") and run["status"] == "complete"
    )
    index.update(
        {
            "run_prefix": ctx.prefix,
            "updated_at_utc": _utc_now(),
            "benchmark": str(ctx.benchmark),
            "split": ctx.split,
            "fewshot_control_summary_command": shlex.join(
                [
                    "python",
                    "scripts/summarize_downstream_fewshot_controls.py",
                    *[arg for path in zero_dirs for arg in ("--zero-run-dir", path)],
                    *[arg for path in control_dirs for arg in ("--control-run-dir", path)],
                    "--output-json",
                    f"artifacts/evaluations/{ctx.prefix}_fewshot_controls.json",
                    "--output-md",
                    f"artifacts/evaluations/{ctx.prefix}_fewshot_controls.md",
                ]
            )
            if zero_dirs and control_dirs
            else None,
        }
    )
    _write_json(index_path, index)
    return index_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run zero-shot / prompt-format / few-shot downstream conditions per model.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--benchmark", required=True, help="Benchmark export directory")
    parser.add_argument("--split", default="test", choices=["dev", "test", "all"])
    parser.add_argument(
        "--models",
        action="append",
        default=[],
        help="Model slug(s) to run (comma-separated or repeated).",
    )
    parser.add_argument("--tier", action="append", default=[], choices=sorted(TIERS))
    parser.add_argument("--all-models", action="store_true")
    parser.add_argument(
        "--conditions",
        default="",
        help="Comma-separated subset of: " + ", ".join(all_condition_ids()),
    )
    parser.add_argument(
        "--prefix",
        default=dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d") + "_naacl2027",
        help="Run prefix for artifacts/evaluations/<prefix>_<kind>_<slug>[_<condition>]",
    )
    parser.add_argument("--output-root", default="artifacts/evaluations")
    parser.add_argument("--log-dir", default="logs")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--schema", action="append", default=[], help="graph_profile=schema.json")
    parser.add_argument("--config", action="append", default=[], help="graph_profile=config.yaml")
    parser.add_argument(
        "--endpoint",
        action="append",
        default=[],
        help="Per-model endpoint override as slug=http://host:port/v1",
    )
    parser.add_argument("--base-url", default="", help="Default endpoint for local models")
    parser.add_argument("--port", type=int, default=0, help="Port for --launch / default base URL")
    parser.add_argument("--few-shot-k", type=int, default=5)
    parser.add_argument("--few-shot-max-question-sim", type=float, default=0.90)
    parser.add_argument("--max-consecutive-errors", type=int, default=5)
    parser.add_argument("--max-prediction-failure-rate", type=float, default=0.01)
    parser.add_argument("--text-metrics", action="store_true", help="Keep supplementary text metrics")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--schema-max-items", type=int, default=70)
    parser.add_argument("--timeout-sec", type=int, default=180)
    parser.add_argument("--limit", type=int, default=0, help="Development only; limited runs are not paper results")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--continue-on-model-failure", action="store_true")
    parser.add_argument(
        "--launch",
        action="store_true",
        help="Start vLLM for each local model with the manifest command template (never for hosted models).",
    )
    parser.add_argument("--gpu-ids", default="", help="Required with --launch, e.g. 2 or 2,3")
    parser.add_argument("--conda-env", default="", help="CONDA_ENV passed to the serve script with --launch")
    return parser


def select_models(manifest: ModelManifest, args: argparse.Namespace) -> list[ModelSpec]:
    slugs = [slug.strip() for item in args.models for slug in item.split(",") if slug.strip()]
    if not (slugs or args.tier or args.all_models):
        raise SystemExit("select models with --models, --tier, or --all-models")
    selected: list[ModelSpec] = []
    for slug in slugs:
        try:
            selected.append(manifest.model(slug))
        except ManifestError as exc:
            raise SystemExit(str(exc)) from exc
    for model in manifest.models:
        if (args.all_models or model.tier in args.tier) and model not in selected:
            selected.append(model)
    return selected


def _parse_mapping(items: list[str], flag: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise SystemExit(f"{flag} entries must use key=value")
        key, value = item.split("=", 1)
        mapping[key] = value
    return mapping


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = load_model_manifest(args.manifest)
    except ManifestError as exc:
        raise SystemExit(f"invalid model manifest: {exc}") from exc
    validate_prefix(args.prefix)
    if args.skip_existing and args.overwrite:
        raise SystemExit("--skip-existing and --overwrite are mutually exclusive")
    if args.launch and not args.gpu_ids:
        raise SystemExit("--launch requires explicit --gpu-ids (never pick GPUs implicitly)")

    selected_conditions: set[str] | None = None
    if args.conditions:
        selected_conditions = {item.strip() for item in args.conditions.split(",") if item.strip()}
        unknown = sorted(selected_conditions - set(all_condition_ids()))
        if unknown:
            raise SystemExit(f"unknown condition(s): {', '.join(unknown)}")

    benchmark = Path(args.benchmark)
    if not benchmark.is_dir():
        raise SystemExit(f"--benchmark must be an export directory: {benchmark}")
    for required in (f"{args.split}.jsonl", "train.jsonl"):
        if not (benchmark / required).exists():
            raise SystemExit(f"benchmark export is missing {required}: {benchmark}")

    port = args.port or int(manifest.defaults.get("port") or 8000)
    ctx = SuiteContext(
        benchmark=benchmark,
        split=args.split,
        prefix=args.prefix,
        output_root=Path(args.output_root),
        log_dir=Path(args.log_dir),
        python=args.python,
        schemas=args.schema or list(DEFAULT_SCHEMAS),
        graph_configs=args.config or list(DEFAULT_GRAPH_CONFIGS),
        few_shot_k=args.few_shot_k,
        few_shot_max_question_sim=args.few_shot_max_question_sim,
        max_consecutive_errors=args.max_consecutive_errors,
        max_prediction_failure_rate=args.max_prediction_failure_rate,
        text_metrics=args.text_metrics,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        schema_max_items=args.schema_max_items,
        timeout_sec=args.timeout_sec,
        limit=args.limit,
        dry_run=args.dry_run,
        skip_existing=args.skip_existing,
        overwrite=args.overwrite,
        continue_on_model_failure=args.continue_on_model_failure,
        launch=args.launch,
        gpu_ids=args.gpu_ids,
        port=port,
        default_base_url=args.base_url or f"http://localhost:{port}/v1",
        endpoints=_parse_mapping(args.endpoint, "--endpoint"),
        conda_env=args.conda_env,
    )
    models = select_models(manifest, args)
    unknown_endpoints = sorted(set(ctx.endpoints) - {model.slug for model in manifest.models})
    if unknown_endpoints:
        raise SystemExit(f"--endpoint names unknown model slug(s): {', '.join(unknown_endpoints)}")

    logger = SuiteLogger(ctx)
    provenance = {**benchmark_provenance(ctx)}
    if not ctx.dry_run:
        provenance.update(git_provenance())
    logger.info(
        f"suite prefix={ctx.prefix} benchmark={ctx.benchmark} split={ctx.split} "
        f"split_sha256={provenance.get('split_sha256')} manifest={manifest.path} "
        f"manifest_sha256={manifest.sha256} models={','.join(m.slug for m in models)}"
        + (" DRY-RUN" if ctx.dry_run else "")
    )
    if ctx.limit:
        logger.info(f"--limit {ctx.limit}: development run, not a paper result")

    outcomes: list[ModelOutcome] = []
    for model in models:
        conditions = conditions_for_model(model, selected_conditions)
        if not conditions:
            logger.info(f"skip {model.slug}: no selected conditions apply")
            continue
        outcome = run_model(ctx, manifest, model, conditions, logger, provenance)
        outcomes.append(outcome)
        if outcome.status == "failed" and not ctx.continue_on_model_failure:
            logger.info("stopping suite (pass --continue-on-model-failure to move on to the next model)")
            break

    if not ctx.dry_run and outcomes:
        index_path = write_suite_index(ctx, outcomes)
        logger.info(f"suite index: {index_path}")
    failed = [outcome.slug for outcome in outcomes if outcome.status == "failed"]
    if failed:
        logger.info(f"FAILED models: {', '.join(failed)} (details: {logger.failure_path})")
        return EXIT_MODEL_FAILURE
    return 0


if __name__ == "__main__":
    sys.exit(main())
