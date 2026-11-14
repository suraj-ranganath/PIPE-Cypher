#!/usr/bin/env python3
"""Collect every number the NAACL 2027 paper reports into one JSON.

Reads completed artifacts only (exports, run records, spend ledger, evaluation
JSONL, judge outputs, refresh audits). Runs with an invalid prediction-failure
rate are excluded and listed. Intervals are signature-clustered bootstraps.
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import statistics
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.eval_statistics import (  # noqa: E402
    EvaluationRun,
    analyze_models,
    analyze_rank_agreement,
    analyze_self_preference,
    load_benchmark_index,
)
from pipecypher.io import read_jsonl  # noqa: E402

MODELS = [
    "glm53_flash", "qwen35_9b", "llama31_8b", "gemma3_4b", "gemma3_12b", "gemma4_26b_a4b",
    "phi4", "mistral_small32_24b", "gpt_oss_20b", "qwen3_coder_30b_a3b", "gpt6_luna",
]
EV = Path("artifacts/evaluations")


def _eval_path(prefix: str, slug: str, condition: str) -> Path | None:
    if condition == "zero_pipe_standard":
        p = EV / f"{prefix}_downstream_{slug}" / "zero_shot_evaluation.jsonl"
    elif condition == "zero_pipe_governed":
        p = EV / f"{prefix}_promptfmt_{slug}_zero_pipe_governed" / "zero_shot_evaluation.jsonl"
    elif condition == "zero_native":
        p = EV / f"{prefix}_promptfmt_{slug}_zero_native" / "zero_shot_evaluation.jsonl"
    elif condition == "fewshot_ordered":
        p = EV / f"{prefix}_control_{slug}_ordered_logged" / "few_shot_evaluation.jsonl"
    else:
        raise ValueError(condition)
    return p if p.exists() else None


def _run(label: str, path: Path, graph: str | None = None) -> EvaluationRun | None:
    rows = read_jsonl(path)
    if graph:
        rows = [r for r in rows if r.get("graph_profile") == graph]
    if not rows:
        return None
    return EvaluationRun(label=label, path=str(path), rows=rows)


def _overall(path: Path) -> dict[str, Any]:
    rows = read_jsonl(path)
    n = len(rows)

    def mean(key: str) -> float | None:
        vals = [r.get(key) for r in rows if key in r]
        return (sum(1.0 if v is True else 0.0 if v in (False, None) else float(v) for v in vals) / len(vals)) if vals else None

    fails = sum(1 for r in rows if r.get("prediction_failed"))
    return {
        "n": n,
        "strict": mean("execution_accuracy"),
        "projected": mean("projected_execution_accuracy"),
        "answer_f1": mean("answer_f1"),
        "projected_f1": mean("projected_answer_f1"),
        "exec_success": mean("execution_success"),
        "parse_valid": mean("parse_valid"),
        "schema_valid": mean("schema_valid"),
        "governance_valid": mean("governance_valid"),
        "prediction_failure_rate": fails / n if n else None,
        "wrong_direction_rate": sum(1 for r in rows if "wrong_direction" in (r.get("governance_error_codes") or [])) / n if n else None,
    }


def benchmark_section(name: str) -> dict[str, Any]:
    root = Path("artifacts/benchmarks") / name
    if not root.exists():
        return {}
    manifest = json.loads((root / "manifest.json").read_text())
    stats = json.loads((root / "stats.json").read_text())
    return {"manifest": manifest, "stats": stats}


def generation_section(prefixes: list[str], ledger: Path) -> dict[str, Any]:
    records = []
    for prefix in prefixes:
        for f in glob.glob(f"artifacts/runs/*_{prefix}_*/records.jsonl") + glob.glob(f"artifacts/runs/*_{prefix}/records.jsonl"):
            records.extend(read_jsonl(f))
    accepted = [r for r in records if r.get("accepted")]
    reasons: collections.Counter[str] = collections.Counter()
    origins: collections.Counter[str] = collections.Counter()
    realization: collections.Counter[str] = collections.Counter()
    fallback = 0
    for r in records:
        meta = r.get("generation_metadata") or {}
        if r.get("accepted"):
            origins[meta.get("template_origin", "?")] += 1
            if "fallback_after_error" in ((r.get("judge") or {}).get("raw") or {}):
                fallback += 1
        realization[meta.get("question_realization", "?")] += 1
        if r.get("accepted"):
            continue
        judge = r.get("judge") or {}
        reason = str(judge.get("failure_reason") or "")
        execution = r.get("execution") or {}
        if "slot bindings" in str(execution.get("error") or ""):
            reasons["slot bindings unavailable"] += 1
        elif not (r.get("validation") or {}).get("syntax_valid", True) or not (r.get("validation") or {}).get("schema_valid", True):
            reasons["schema/syntax gate"] += 1
        elif not execution.get("success"):
            reasons["execution error"] += 1
        elif reason.startswith("execution returned no rows"):
            reasons["empty result"] += 1
        elif reason.startswith("duplicate") or "diversity cap" in reason:
            reasons["duplicate / entity cap"] += 1
        elif reason.startswith("signature quota"):
            reasons["signature quota"] += 1
        elif "truncated" in reason:
            reasons["truncated unordered LIMIT"] += 1
        else:
            reasons["LLM judge reject"] += 1
    spend = {"calls": 0, "cost_usd": 0.0, "prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0}
    latencies = []
    if ledger.exists():
        for row in read_jsonl(ledger):
            label = str(row.get("label") or "")
            if any(label.startswith(p + ":") or label == p for p in prefixes):
                spend["calls"] += 1
                spend["cost_usd"] += float(row.get("cost_usd") or 0.0)
                spend["prompt_tokens"] += int(row.get("prompt_tokens") or 0)
                spend["completion_tokens"] += int(row.get("completion_tokens") or 0)
                spend["reasoning_tokens"] += int(row.get("reasoning_tokens") or 0)
                latencies.append(float(row.get("latency_s") or 0.0))
    ts = sorted(r.get("created_at") for r in records if r.get("created_at"))
    return {
        "candidates": len(records),
        "accepted": len(accepted),
        "acceptance_rate": len(accepted) / len(records) if records else None,
        "rejection_reasons": dict(reasons.most_common()),
        "accepted_template_origin": dict(origins),
        "question_realization": dict(realization),
        "accepted_via_rule_based_fallback": fallback,
        "spend": spend,
        "median_call_latency_s": statistics.median(latencies) if latencies else None,
        "first_record": ts[0] if ts else None,
        "last_record": ts[-1] if ts else None,
    }


def downstream_section(prefix: str, benchmark: str, conditions: list[str], split: str = "test") -> dict[str, Any]:
    index = load_benchmark_index([str(Path("artifacts/benchmarks") / benchmark / f"{split}.jsonl")])
    out: dict[str, Any] = {"per_model": {}, "clustered": {}}
    for condition in conditions:
        runs = []
        for slug in MODELS:
            p = _eval_path(prefix, slug, condition)
            if p is None:
                continue
            out["per_model"].setdefault(slug, {})[condition] = _overall(p)
            run = _run(slug, p)
            if run:
                runs.append(run)
        if runs:
            try:
                out["clustered"][condition] = analyze_models(
                    runs,
                    metrics=("execution_accuracy", "projected_execution_accuracy"),
                    benchmark_index=index,
                    exclude_invalid=True,
                    require_same_ids=False,
                )
            except Exception as exc:  # report, never hide
                out["clustered"][condition] = {"error": str(exc)}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", default=str(Path.home() / "pipecypher-spend/ledger.jsonl"))
    ap.add_argument("--output", default="artifacts/naacl_results/results.json")
    args = ap.parse_args()
    ledger = Path(args.ledger)
    res: dict[str, Any] = {}
    res["benchmarks"] = {
        name: benchmark_section(name)
        for name in ("naacl_v2_random", "naacl_v2_heldout", "naacl_v2_genswap_gpt6luna",
                     "naacl_t2c_recommendations", "naacl_t2c_northwind", "naacl_t2c_fincen")
    }
    res["generation"] = {
        "main_v2": generation_section(
            ["naacl_v2_snb", "naacl_v2_snbx", "naacl_v2_snby", "naacl_v2_snbz", "naacl_v2_snbt", "naacl_v2_snbu",
             "naacl_v2_finbench", "naacl_v2_finbenchx", "naacl_v2_finbencht"], ledger
        ),
        "genswap": generation_section(["naacl_genswap_snb", "naacl_genswap_finbench"], ledger),
        "t2c": generation_section(
            ["naacl_t2c_recommendations", "naacl_t2c_northwind", "naacl_t2c_fincen",
             "naacl_t2cx_recommendations", "naacl_t2cx_northwind", "naacl_t2cx_fincen"], ledger
        ),
    }
    res["downstream_heldout"] = downstream_section(
        "naacl_v2_heldout", "naacl_v2_heldout", ["zero_pipe_standard", "zero_pipe_governed", "fewshot_ordered"]
    )
    res["genswap_eval"] = downstream_section("naacl_genswap_eval", "naacl_v2_genswap_gpt6luna", ["zero_pipe_standard"], split="all")
    # Anchor (curated T2C-2024) and PIPE-generated benchmarks on the same graphs.
    anchor_pkg = "artifacts/external_benchmarks/t2c2024_d9f1554_recommended_audited/test.jsonl"
    res["anchor"] = {slug: _overall(p) for slug in MODELS if (p := _eval_path("naacl_anchor", slug, "zero_pipe_standard"))}
    res["t2c_pipe"] = {}
    res["rank_agreement"] = {}
    for g in ("recommendations", "northwind", "fincen"):
        prefix = f"naacl_t2cpipe_{g}"
        res["t2c_pipe"][g] = {slug: _overall(p) for slug in MODELS if (p := _eval_path(prefix, slug, "zero_pipe_standard"))}
        runs_a, runs_b = [], []
        for slug in MODELS:
            pa = _eval_path(prefix, slug, "zero_pipe_standard")
            pb = _eval_path("naacl_anchor", slug, "zero_pipe_standard")
            if pa and pb:
                ra, rb = _run(slug, pa), _run(slug, pb, graph=f"t2c_{g}")
                if ra and rb:
                    runs_a.append(ra)
                    runs_b.append(rb)
        if len(runs_a) >= 4:
            try:
                res["rank_agreement"][g] = analyze_rank_agreement(
                    runs_a, runs_b, name_a=f"PIPE-{g}", name_b=f"T2C24-{g}",
                    metrics=("projected_execution_accuracy", "execution_accuracy"),
                    benchmark_index_a=load_benchmark_index([f"artifacts/benchmarks/naacl_t2c_{g}/all.jsonl"]),
                    benchmark_index_b=load_benchmark_index([anchor_pkg]),
                )
            except Exception as exc:
                res["rank_agreement"][g] = {"error": str(exc)}
    # Self-preference: GLM-generated held-out test vs gpt-6-luna-generated slice.
    own, other = [], []
    for slug in MODELS:
        p_own = _eval_path("naacl_v2_heldout", slug, "zero_pipe_standard")
        p_other = _eval_path("naacl_genswap_eval", slug, "zero_pipe_standard")
        if p_own and p_other:
            own.append(_run(slug, p_own))
            other.append(_run(slug, p_other))
    for self_model, own_runs, other_runs, name_own, name_other in (
        ("glm53_flash", own, other, "GLM slice", "gpt-6-luna slice"),
        ("gpt6_luna", other, own, "gpt-6-luna slice", "GLM slice"),
    ):
        if len(own_runs) >= 4:
            for metric in ("projected_execution_accuracy",):
                try:
                    res.setdefault("self_preference", {})[f"{self_model}:{metric}"] = analyze_self_preference(
                        own_runs, other_runs, self_model=self_model, name_own=name_own, name_other=name_other,
                        metric=metric,
                        benchmark_index_own=load_benchmark_index(["artifacts/benchmarks/naacl_v2_heldout/test.jsonl"] if self_model == "glm53_flash" else ["artifacts/benchmarks/naacl_v2_genswap_gpt6luna/all.jsonl"]),
                        benchmark_index_other=load_benchmark_index(["artifacts/benchmarks/naacl_v2_genswap_gpt6luna/all.jsonl"] if self_model == "glm53_flash" else ["artifacts/benchmarks/naacl_v2_heldout/test.jsonl"]),
                    )
                except Exception as exc:
                    res.setdefault("self_preference", {})[f"{self_model}:{metric}"] = {"error": str(exc)}
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
