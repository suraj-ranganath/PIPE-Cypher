from __future__ import annotations

import copy
import csv
import io
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml

from pipecypher.io import read_jsonl


def load_yaml(path: str | Path) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def dump_yaml(data: dict[str, Any], path: str | Path) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def apply_variant(base: dict[str, Any], variant: dict[str, Any]) -> dict[str, Any]:
    cfg = copy.deepcopy(base)
    generation = cfg.setdefault("generation", {})
    judge = cfg.setdefault("judge", {})
    models = cfg.setdefault("models", {})

    baseline = variant.get("baseline", "")
    if baseline == "unconstrained_local_llm":
        generation["template_source"] = "llm"
        generation["allow_seed_template_fallback"] = False
        generation["retrieval_top_k"] = 0
        generation["normalize_cypher"] = False
        generation["repair_attempts"] = 0
        generation["deterministic_cypher_fallback"] = False
        judge["enabled"] = False
    elif baseline == "reverse_only":
        generation["template_source"] = "default"
        generation["allow_seed_template_fallback"] = True
        generation["retrieval_top_k"] = 0
        generation["normalize_cypher"] = False
        generation["repair_attempts"] = 0
        judge["enabled"] = False
    elif baseline == "validators_repair":
        generation["retrieval_top_k"] = 0
        generation["normalize_cypher"] = True
        generation["repair_attempts"] = max(1, generation.get("repair_attempts", 1))
        generation["deterministic_cypher_fallback"] = True
        judge["enabled"] = False
    elif baseline == "full_pipe_cypher":
        generation["normalize_cypher"] = True
        generation["deterministic_cypher_fallback"] = True
        judge["enabled"] = True

    if "retrieval_top_k" in variant:
        generation["retrieval_top_k"] = int(variant["retrieval_top_k"])
    if "rewrite" in variant:
        generation["normalize_cypher"] = bool(variant["rewrite"])
    if "judge" in variant:
        judge["enabled"] = bool(variant["judge"])
    if "generation_model" in variant:
        models["generation_model"] = variant["generation_model"]
        models["judge_model"] = variant["generation_model"]
    if "graph_mix" in variant:
        generation["graph_mix"] = variant["graph_mix"]
    if "target_per_category" in variant:
        generation["target_per_category"] = int(variant["target_per_category"])
    if "prompt_profile" in variant:
        generation["prompt_profile"] = str(variant["prompt_profile"])
    return cfg


def build_experiment_variants(matrix: dict[str, Any]) -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = []
    for baseline in matrix.get("baselines", []):
        variants.append({"name": baseline["name"], "baseline": baseline["name"]})

    ablations = matrix.get("ablations", {})
    for value in ablations.get("retrieval_top_k", []):
        variants.append({"name": f"ablation_retrieval_topk_{value}", "baseline": "full_pipe_cypher", "retrieval_top_k": value})
    for value in ablations.get("judge", []):
        variants.append({"name": f"ablation_judge_{str(value).lower()}", "baseline": "full_pipe_cypher", "judge": value})
    for value in ablations.get("rewrite", []):
        variants.append({"name": f"ablation_rewrite_{str(value).lower()}", "baseline": "full_pipe_cypher", "rewrite": value})
    for model in ablations.get("generation_model", []):
        safe_model = model.replace("/", "_").replace(":", "_")
        variants.append({"name": f"ablation_model_{safe_model}", "baseline": "full_pipe_cypher", "generation_model": model})
    for value in ablations.get("graph_mix", []):
        variants.append({"name": f"ablation_graph_mix_{value}", "baseline": "full_pipe_cypher", "graph_mix": value})
    for profile in ablations.get("prompt_profile", []):
        variants.append(
            {
                "name": f"prompt_profile_{profile}",
                "baseline": "full_pipe_cypher",
                "prompt_profile": profile,
            }
        )
    return variants


def variant_applies_to_graph(variant: dict[str, Any], graph_profile: str) -> bool:
    graph_mix = variant.get("graph_mix")
    if not graph_mix:
        return True
    if graph_mix == "finbench_only":
        return graph_profile == "finbench"
    if graph_mix == "finbench_plus_snb":
        return graph_profile in {"finbench", "snb"}
    return True


def summarize_records(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    accepted = sum(1 for row in rows if row.get("accepted"))
    by_category = Counter(row.get("category") for row in rows)
    accepted_by_category = Counter(row.get("category") for row in rows if row.get("accepted"))
    issue_counts = Counter()
    difficulty_counts = Counter()
    strategy_counts = Counter()
    gate_counts = defaultdict(int)

    for row in rows:
        validation = row.get("validation", {})
        features = validation.get("structural_features", {})
        difficulty_counts[features.get("difficulty", "unknown")] += 1
        strategy_counts[features.get("primary_strategy", "unknown")] += 1
        if validation.get("read_only"):
            gate_counts["read_only"] += 1
        if validation.get("syntax_valid"):
            gate_counts["syntax_valid"] += 1
        if validation.get("schema_valid"):
            gate_counts["schema_valid"] += 1
        if row.get("execution", {}).get("success"):
            gate_counts["execution_success"] += 1
        if row.get("judge", {}).get("passed"):
            gate_counts["judge_pass"] += 1
        for issue in validation.get("issues", []):
            issue_counts[issue.get("code", "unknown")] += 1

    return {
        "records": total,
        "accepted": accepted,
        "accept_rate": accepted / total if total else 0.0,
        "by_category": dict(sorted(by_category.items())),
        "accepted_by_category": dict(sorted(accepted_by_category.items())),
        "difficulty": dict(sorted(difficulty_counts.items())),
        "primary_strategy": dict(sorted(strategy_counts.items())),
        "gates": dict(sorted(gate_counts.items())),
        "issues": dict(sorted(issue_counts.items())),
    }


def summarize_records_path(path: str | Path) -> dict[str, Any]:
    records_path = records_jsonl_path(path)
    summary = summarize_records(read_jsonl(records_path))
    summary["run"] = records_path.parent.name
    summary["records_path"] = str(records_path)
    return summary


def records_jsonl_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_dir():
        candidate = candidate / "records.jsonl"
    return candidate


def format_summary_lines(summary: dict[str, Any]) -> list[str]:
    lines = [
        f"records={summary['records']}",
        f"accepted={summary['accepted']}",
    ]
    if summary["records"]:
        lines.append(f"accept_rate={summary['accept_rate']:.3f}")
    for key in [
        "by_category",
        "accepted_by_category",
        "difficulty",
        "primary_strategy",
        "gates",
        "issues",
    ]:
        lines.append(f"{key}=" + json.dumps(summary[key], sort_keys=True))
    return lines


def compare_runs(paths: list[str | Path]) -> list[dict[str, Any]]:
    return [summarize_records_path(path) for path in paths]


def format_run_comparison_markdown(summaries: list[dict[str, Any]]) -> str:
    lines = [
        "| Run | Records | Accepted | Accept Rate | Judge Pass | Execution Success | Accepted Categories |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for summary in summaries:
        gates = summary.get("gates", {})
        lines.append(
            "| "
            + " | ".join(
                [
                    str(summary["run"]),
                    str(summary["records"]),
                    str(summary["accepted"]),
                    f"{summary['accept_rate']:.3f}",
                    str(gates.get("judge_pass", 0)),
                    str(gates.get("execution_success", 0)),
                    _compact_counts(summary.get("accepted_by_category", {})),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def format_run_comparison_csv(summaries: list[dict[str, Any]]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(
        out,
        fieldnames=[
            "run",
            "records",
            "accepted",
            "accept_rate",
            "judge_pass",
            "execution_success",
            "accepted_by_category",
        ],
    )
    writer.writeheader()
    for summary in summaries:
        gates = summary.get("gates", {})
        writer.writerow(
            {
                "run": summary["run"],
                "records": summary["records"],
                "accepted": summary["accepted"],
                "accept_rate": f"{summary['accept_rate']:.3f}",
                "judge_pass": gates.get("judge_pass", 0),
                "execution_success": gates.get("execution_success", 0),
                "accepted_by_category": _compact_counts(summary.get("accepted_by_category", {})),
            }
        )
    return out.getvalue()


def _compact_counts(counts: dict[str, int]) -> str:
    return "; ".join(f"{key}:{value}" for key, value in sorted(counts.items()))
