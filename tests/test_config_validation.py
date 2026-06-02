from __future__ import annotations

import pytest

from pipecypher.config import (
    ConfigValidationError,
    RunConfig,
    collect_unknown_config_keys,
    load_config,
    validate_config,
)
from scripts.validate_config import main as validate_config_main


def test_collect_unknown_nested_config_keys():
    unknown = collect_unknown_config_keys(
        {
            "models": {"generation_model": "Qwen/Qwen3.5-9B", "typo_model": "bad"},
            "generation": {"retrieval_top_k": 2},
            "extra_section": {},
        }
    )

    assert unknown == ["models.typo_model", "extra_section"]


def test_strict_load_rejects_unknown_key(tmp_path):
    config_path = tmp_path / "bad.yaml"
    config_path.write_text(
        """
models:
  generation_model: Qwen/Qwen3.5-9B
generation:
  target_per_catgory: 100
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigValidationError, match="generation.target_per_catgory"):
        load_config(config_path, strict=True)


def test_validate_config_rejects_expensive_run_mistakes():
    config = RunConfig()
    config.generation.target_per_category = 0
    config.generation.max_entity_pct = 1.5
    config.judge.min_schema_use = 1.2

    errors = validate_config(config)

    assert "generation.target_per_category must be > 0" in errors
    assert "generation.max_entity_pct must be in (0, 1]" in errors
    assert "judge.min_schema_use must be in [0, 1]" in errors


def test_validate_config_cli_accepts_run_config():
    assert validate_config_main(["configs/local_smoke.yaml"]) == 0


def test_validate_config_cli_rejects_non_run_matrix():
    assert validate_config_main(["configs/experiment_matrix.yaml"]) == 1
