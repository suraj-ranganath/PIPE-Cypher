from __future__ import annotations

import pytest

from scripts.render_ablation_suite_figure import merge_unconstrained_stress_baseline


def test_merge_unconstrained_stress_baseline_replaces_attemptless_rows() -> None:
    summary = {
        "metadata": {"run_prefix": "target100"},
        "runs": [
            {
                "graph": "finbench",
                "variant": "unconstrained_local_llm",
                "summary_present": True,
                "candidate_attempts": 0,
                "records": 0,
                "accepted": 0,
            },
            {
                "graph": "finbench",
                "variant": "full_pipe_cypher",
                "summary_present": True,
                "candidate_attempts": 824,
                "records": 824,
                "accepted": 800,
            },
        ],
    }
    stress_summary = {
        "metadata": {"run_prefix": "attempt_logged_stress"},
        "runs": [
            {
                "graph": "finbench",
                "variant": "unconstrained_local_llm",
                "summary_present": True,
                "candidate_attempts": 422,
                "records": 422,
                "accepted": 200,
            }
        ],
    }

    merged = merge_unconstrained_stress_baseline(summary, stress_summary)

    assert merged["runs"][0]["candidate_attempts"] == 422
    assert merged["runs"][0]["accepted"] == 200
    assert merged["runs"][1]["variant"] == "full_pipe_cypher"
    assert merged["runs"][1]["accepted"] == 800
    assert (
        merged["metadata"]["unconstrained_stress_baseline_source"]
        == "attempt_logged_stress"
    )


def test_merge_unconstrained_stress_baseline_requires_graph_match() -> None:
    summary = {
        "metadata": {},
        "runs": [
            {
                "graph": "snb",
                "variant": "unconstrained_local_llm",
                "summary_present": True,
                "candidate_attempts": 0,
                "records": 0,
            }
        ],
    }
    stress_summary = {
        "metadata": {},
        "runs": [
            {
                "graph": "finbench",
                "variant": "unconstrained_local_llm",
                "summary_present": True,
                "candidate_attempts": 422,
            }
        ],
    }

    with pytest.raises(SystemExit, match="missing corrected unconstrained"):
        merge_unconstrained_stress_baseline(summary, stress_summary)
