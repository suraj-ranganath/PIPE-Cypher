from __future__ import annotations

import pytest

from pipecypher.config import load_config
from pipecypher.run_estimate import estimate_run_capacity, format_run_estimate_markdown
from scripts.estimate_run_capacity import main as estimate_run_capacity_main


def test_estimate_run_capacity_matches_pipeline_attempt_ceiling():
    config = load_config("configs/local_smoke.yaml", strict=True, validate=True)
    estimate = estimate_run_capacity(
        config,
        assumed_accept_rate=0.5,
        llm_calls_per_minute=8.0,
    )

    assert estimate["totals"]["target_examples"] == 4
    assert estimate["totals"]["upper_candidate_attempts"] >= 16
    assert estimate["totals"]["cypher_generation_calls_upper"] == estimate["totals"][
        "upper_candidate_attempts"
    ]
    assert estimate["totals"]["approx_total_tokens_upper"] > estimate["totals"][
        "approx_total_tokens_nominal"
    ]
    assert estimate["totals"]["upper_wall_clock_minutes"] > 0


def test_estimate_rejects_invalid_assumed_accept_rate():
    config = load_config("configs/local_smoke.yaml")

    with pytest.raises(ValueError, match="assumed_accept_rate"):
        estimate_run_capacity(config, assumed_accept_rate=0)

    with pytest.raises(ValueError, match="llm_calls_per_minute"):
        estimate_run_capacity(config, llm_calls_per_minute=0)


def test_format_run_estimate_markdown_contains_operational_totals():
    config = load_config("configs/local_smoke.yaml", strict=True, validate=True)
    markdown = format_run_estimate_markdown(
        estimate_run_capacity(config, llm_calls_per_minute=10)
    )

    assert "PIPE-Cypher Run Estimate" in markdown
    assert "Upper LLM calls" in markdown
    assert "Rough upper wall-clock" in markdown
    assert "| Category |" in markdown


def test_estimate_run_capacity_cli_json_smoke(capsys):
    assert (
        estimate_run_capacity_main(
            ["--config", "configs/local_smoke.yaml", "--format", "json"]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert '"target_examples"' in captured.out


def test_estimate_run_capacity_cli_target_override(capsys):
    assert (
        estimate_run_capacity_main(
            [
                "--config",
                "configs/local_smoke.yaml",
                "--target-per-category",
                "3",
                "--format",
                "json",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert '"target": 3' in captured.out
    assert '"target_examples": 12' in captured.out
