from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def load_records(paths: list[str | Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def summarize_runtime(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_graph: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_graph[str(record.get("graph_profile") or "unknown")].append(record)
    return {
        "overall": _summarize_group(records),
        "by_graph": {
            graph: _summarize_group(rows)
            for graph, rows in sorted(by_graph.items())
        },
    }


def _summarize_group(records: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = sum(1 for row in records if bool(row.get("accepted") or row.get("gates", {}).get("accepted")))
    execution_latencies = [
        float(latency)
        for latency in (_execution_latency(row) for row in records)
        if latency is not None
    ]
    judge_calls = sum(1 for row in records if isinstance(row.get("judge"), dict))
    model_counts = Counter(str(row.get("model") or "unknown") for row in records)
    repair_attempts = sum(int(row.get("repair_attempts") or 0) for row in records)
    return {
        "records": len(records),
        "accepted": accepted,
        "rejected": len(records) - accepted,
        "acceptance_rate": accepted / len(records) if records else 0.0,
        "judge_records": judge_calls,
        "repair_attempts": repair_attempts,
        "model_counts": dict(sorted(model_counts.items())),
        "execution_latency_ms": _latency_summary(execution_latencies),
    }


def _execution_latency(record: dict[str, Any]) -> float | None:
    execution = record.get("execution")
    if isinstance(execution, dict) and execution.get("latency_ms") is not None:
        return float(execution["latency_ms"])
    if record.get("latency_ms") is not None:
        return float(record["latency_ms"])
    return None


def _latency_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "n": 0,
            "mean": 0.0,
            "median": 0.0,
            "p95": 0.0,
            "max": 0.0,
        }
    ordered = sorted(values)
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "p95": _percentile(ordered, 0.95),
        "max": max(values),
    }


def _percentile(ordered: list[float], q: float) -> float:
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = q * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight
