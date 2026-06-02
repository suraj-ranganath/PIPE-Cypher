from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .models import DEFAULT_CATEGORIES


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


@dataclass
class GenerationConfig:
    graph_profile: str = "finbench"
    categories: list[str] = field(default_factory=lambda: list(DEFAULT_CATEGORIES))
    target_per_category: int = 5
    random_seed: int | None = None
    template_candidates: int = 4
    template_source: str = "llm"
    allow_seed_template_fallback: bool = True
    retrieval_top_k: int = 3
    normalize_cypher: bool = True
    repair_attempts: int = 1
    deterministic_cypher_fallback: bool = True
    max_entity_pct: float = 0.15
    require_non_empty: bool = True
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
    return config


def load_config(path: str | os.PathLike[str] | None = None) -> RunConfig:
    config = RunConfig()
    if path:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError("Config YAML must be a mapping")
        _merge_dataclass(config, data)
    return _apply_env(config)
