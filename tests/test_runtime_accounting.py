from pipecypher.runtime_accounting import summarize_runtime


def test_summarize_runtime_reports_acceptance_and_latency_by_graph():
    summary = summarize_runtime(
        [
            {
                "graph_profile": "finbench",
                "accepted": True,
                "execution": {"latency_ms": 10.0},
                "judge": {},
                "model": "m",
            },
            {
                "graph_profile": "finbench",
                "accepted": False,
                "execution": {"latency_ms": 30.0},
                "judge": {},
                "repair_attempts": 1,
                "model": "m",
            },
            {
                "graph_profile": "snb",
                "accepted": True,
                "execution": {"latency_ms": 20.0},
                "judge": {},
                "model": "m",
            },
        ]
    )

    assert summary["overall"]["records"] == 3
    assert summary["overall"]["accepted"] == 2
    assert summary["overall"]["acceptance_rate"] == 2 / 3
    assert summary["overall"]["repair_attempts"] == 1
    assert summary["overall"]["execution_latency_ms"]["median"] == 20.0
    assert summary["by_graph"]["finbench"]["accepted"] == 1
    assert summary["by_graph"]["snb"]["execution_latency_ms"]["n"] == 1
