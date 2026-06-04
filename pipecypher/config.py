from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

import yaml

from .models import DEFAULT_CATEGORIES
from .prompt_profiles import allowed_prompt_profiles


@dataclass
class ModelConfig:
    generation_model: str = "Qwen/Qwen3.5-9B"
    judge_model: str = "Qwen/Qwen3.5-9B"
    embedding_model: str = "BAAI/bge-m3"
    llm_base_url: str = "http://localhost:8000/v1"
    request_timeout_sec: int = 120
    temperature: float = 0.2
    max_tokens: int = 1024
    reasoning_effort: str | None = "none"
    include_reasoning: bool = False
    enable_thinking: bool = False
    strip_reasoning: bool = True


@dataclass
class Neo4jConfig:
    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: str = "password"
    database: str = "neo4j"
    query_timeout_sec: int = 60
    enforce_read_transactions: bool = True


@dataclass
class GenerationConfig:
    graph_profile: str = "finbench"
    categories: list[str] = field(default_factory=lambda: list(DEFAULT_CATEGORIES))
    target_per_category: int = 5
    random_seed: int | None = None
    template_candidates: int = 4
    template_source: str = "llm"
    prompt_profile: str = "full_pipe_cypher_governed"
    allow_seed_template_fallback: bool = True
    retrieval_top_k: int = 3
    normalize_cypher: bool = True
    repair_attempts: int = 1
    deterministic_cypher_fallback: bool = True
    max_entity_pct: float = 0.15
    require_non_empty: bool = True
    empty_result_diagnostics: bool = True
    generated_query_limit: int = 50


@dataclass
class JudgeConfig:
    enabled: bool = True
    deterministic_fallback: bool = True
    min_semantic_alignment: float = 0.75
    min_schema_use: float = 0.8
    max_ambiguity: float = 0.35


@dataclass
class PathConfig:
    artifact_dir: str = "artifacts"
    schema_path: str | None = None
    seed_examples_path: str | None = None


@dataclass
class PrivacyConfig:
    redact_questions: bool = True
    redact_cypher_literals: bool = True
    redact_entity_values: bool = True
    redact_result_samples: bool = True
    redact_numeric_literals: bool = False
    value_sampling_mode: str = "bounded"
    categorical_max_values: int = 12
    categorical_max_value_chars: int = 80
    categorical_omitted_properties: list[str] = field(
        default_factory=lambda: [
            "*.address",
            "*.comments",
            "*.note",
            "*.notes",
            "*.original_address",
        ]
    )
    placeholder_prefix: str = "VALUE"


@dataclass
class RunConfig:
    models: ModelConfig = field(default_factory=ModelConfig)
    neo4j: Neo4jConfig = field(default_factory=Neo4jConfig)
    generation: GenerationConfig = field(default_factory=GenerationConfig)
    judge: JudgeConfig = field(default_factory=JudgeConfig)
    paths: PathConfig = field(default_factory=PathConfig)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)


class ConfigValidationError(ValueError):
    """Raised when a run configuration is unsafe or malformed."""


def collect_unknown_config_keys(
    values: Mapping[str, Any],
    template: Any | None = None,
    prefix: str = "",
) -> list[str]:
    """Return dotted YAML paths that do not correspond to RunConfig fields."""
    if template is None:
        template = RunConfig()
    if not is_dataclass(template):
        return []

    known_fields = {field.name: field for field in fields(template)}
    unknown: list[str] = []
    for key, value in values.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if key not in known_fields:
            unknown.append(path)
            continue
        current = getattr(template, key)
        if is_dataclass(current) and isinstance(value, Mapping):
            unknown.extend(collect_unknown_config_keys(value, current, path))
    return unknown


def _merge_dataclass(obj: Any, values: dict[str, Any]) -> Any:
    for key, value in values.items():
        if not hasattr(obj, key):
            continue
        current = getattr(obj, key)
        if hasattr(current, "__dataclass_fields__") and isinstance(value, dict):
            _merge_dataclass(current, value)
        else:
            setattr(obj, key, value)
    return obj


def _apply_env(config: RunConfig) -> RunConfig:
    env_map = {
        "PIPE_CYPHER_NEO4J_URI": ("neo4j", "uri"),
        "PIPE_CYPHER_NEO4J_USER": ("neo4j", "user"),
        "PIPE_CYPHER_NEO4J_PASSWORD": ("neo4j", "password"),
        "PIPE_CYPHER_NEO4J_DATABASE": ("neo4j", "database"),
        "PIPE_CYPHER_LLM_BASE_URL": ("models", "llm_base_url"),
        "PIPE_CYPHER_LLM_MODEL": ("models", "generation_model"),
        "PIPE_CYPHER_JUDGE_MODEL": ("models", "judge_model"),
        "PIPE_CYPHER_EMBED_MODEL": ("models", "embedding_model"),
    }
    for env_name, (section, attr) in env_map.items():
        if env_name in os.environ:
            setattr(getattr(config, section), attr, os.environ[env_name])
    if "PIPE_CYPHER_RANDOM_SEED" in os.environ:
        raw_seed = os.environ["PIPE_CYPHER_RANDOM_SEED"].strip()
        config.generation.random_seed = int(raw_seed) if raw_seed else None
    if "PIPE_CYPHER_LLM_MAX_TOKENS" in os.environ:
        config.models.max_tokens = int(os.environ["PIPE_CYPHER_LLM_MAX_TOKENS"])
    if "PIPE_CYPHER_LLM_TEMPERATURE" in os.environ:
        config.models.temperature = float(os.environ["PIPE_CYPHER_LLM_TEMPERATURE"])
    if "PIPE_CYPHER_LLM_REASONING_EFFORT" in os.environ:
        raw_effort = os.environ["PIPE_CYPHER_LLM_REASONING_EFFORT"].strip()
        config.models.reasoning_effort = raw_effort or None
    if "PIPE_CYPHER_LLM_INCLUDE_REASONING" in os.environ:
        config.models.include_reasoning = _env_bool("PIPE_CYPHER_LLM_INCLUDE_REASONING")
    if "PIPE_CYPHER_LLM_ENABLE_THINKING" in os.environ:
        config.models.enable_thinking = _env_bool("PIPE_CYPHER_LLM_ENABLE_THINKING")
    if "PIPE_CYPHER_LLM_STRIP_REASONING" in os.environ:
        config.models.strip_reasoning = _env_bool("PIPE_CYPHER_LLM_STRIP_REASONING")
    return config


def _env_bool(name: str) -> bool:
    value = os.environ[name].strip().casefold()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    raise ConfigValidationError(f"{name} must be a boolean value")


def validate_config(config: RunConfig, *, check_paths: bool = False) -> list[str]:
    """Validate run-level config invariants that are easy to mistype before long jobs."""
    errors: list[str] = []
    models = config.models
    neo4j = config.neo4j
    generation = config.generation
    judge = config.judge
    privacy = config.privacy
    paths = config.paths

    if models.request_timeout_sec <= 0:
        errors.append("models.request_timeout_sec must be > 0")
    if models.temperature < 0:
        errors.append("models.temperature must be >= 0")
    if models.max_tokens <= 0:
        errors.append("models.max_tokens must be > 0")

    if neo4j.query_timeout_sec <= 0:
        errors.append("neo4j.query_timeout_sec must be > 0")

    if not generation.categories:
        errors.append("generation.categories must contain at least one category")
    unknown_categories = sorted(set(generation.categories) - set(DEFAULT_CATEGORIES))
    if unknown_categories:
        errors.append(
            "generation.categories contains unknown values: " + ", ".join(unknown_categories)
        )
    if generation.target_per_category <= 0:
        errors.append("generation.target_per_category must be > 0")
    if generation.template_candidates <= 0:
        errors.append("generation.template_candidates must be > 0")
    if generation.prompt_profile not in allowed_prompt_profiles():
        errors.append(
            "generation.prompt_profile must be one of: "
            + ", ".join(sorted(allowed_prompt_profiles()))
        )
    if generation.retrieval_top_k < 0:
        errors.append("generation.retrieval_top_k must be >= 0")
    if generation.repair_attempts < 0:
        errors.append("generation.repair_attempts must be >= 0")
    if generation.generated_query_limit <= 0:
        errors.append("generation.generated_query_limit must be > 0")
    if not 0 < generation.max_entity_pct <= 1:
        errors.append("generation.max_entity_pct must be in (0, 1]")

    if not 0 <= judge.min_semantic_alignment <= 1:
        errors.append("judge.min_semantic_alignment must be in [0, 1]")
    if not 0 <= judge.min_schema_use <= 1:
        errors.append("judge.min_schema_use must be in [0, 1]")
    if not 0 <= judge.max_ambiguity <= 1:
        errors.append("judge.max_ambiguity must be in [0, 1]")

    if privacy.categorical_max_values < 0:
        errors.append("privacy.categorical_max_values must be >= 0")
    if privacy.categorical_max_value_chars <= 0:
        errors.append("privacy.categorical_max_value_chars must be > 0")
    if not privacy.placeholder_prefix.strip():
        errors.append("privacy.placeholder_prefix must not be blank")

    if check_paths:
        if paths.schema_path and not Path(paths.schema_path).exists():
            errors.append(f"paths.schema_path does not exist: {paths.schema_path}")
        if paths.seed_examples_path and not Path(paths.seed_examples_path).exists():
            errors.append(f"paths.seed_examples_path does not exist: {paths.seed_examples_path}")

    return errors


def load_config(
    path: str | os.PathLike[str] | None = None,
    *,
    strict: bool = False,
    validate: bool = False,
    check_paths: bool = False,
) -> RunConfig:
    config = RunConfig()
    if path:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError("Config YAML must be a mapping")
        if strict:
            unknown = collect_unknown_config_keys(data)
            if unknown:
                raise ConfigValidationError("Unknown config keys: " + ", ".join(unknown))
        _merge_dataclass(config, data)
    config = _apply_env(config)
    if validate:
        errors = validate_config(config, check_paths=check_paths)
        if errors:
            raise ConfigValidationError("; ".join(errors))
    return config
