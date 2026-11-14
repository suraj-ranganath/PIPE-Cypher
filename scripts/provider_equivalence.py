#!/usr/bin/env python3
"""Provider-equivalence check: re-run stored v2 GLM judge prompts on another provider.

The v2 build judged every candidate with GLM-5.3-Flash on Z.AI's FP8 endpoint.
The v3 build pins the same model to a different FP8 provider. This script takes
a stratified sample of v2 judged items, replays the *exact* stored v2 judge
prompt (system + user text from the rejudge files, same temperature, token
budget, reasoning effort, and JSON response format) on the new provider, and
compares the raw ``pass`` decision with the stored Z.AI decision.

Outputs (PRIVATE/internal: questions, Cypher literals, result values):
  <output-dir>/items.jsonl    one row per item with both decisions
  <output-dir>/summary.json   agreement, Cohen's kappa, cache-hit rate, latency

Keys come from the environment (OPENROUTER_API_KEY); never written anywhere.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipecypher.judge_agreement import cohen_kappa, rate_with_ci  # noqa: E402
from pipecypher.llm import OpenAICompatibleLLM, extract_json_text  # noqa: E402


def load_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open() if line.strip()]


def stratified_sample(rows: list[dict], n_pass: int, n_fail: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    passed = [r for r in rows if r["original_judge"].get("llm_decision") is True]
    failed = [r for r in rows if r["original_judge"].get("llm_decision") is False]
    rng.shuffle(passed)
    rng.shuffle(failed)
    # Balance graphs within each stratum.
    def take(pool: list[dict], n: int) -> list[dict]:
        by_graph: dict[str, list[dict]] = {}
        for row in pool:
            by_graph.setdefault(row["graph_profile"], []).append(row)
        out: list[dict] = []
        graphs = sorted(by_graph)
        i = 0
        while len(out) < n and any(by_graph.values()):
            g = graphs[i % len(graphs)]
            if by_graph[g]:
                out.append(by_graph[g].pop())
            i += 1
        return out

    return take(passed, n_pass) + take(failed, n_fail)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rejudge-file", default="artifacts/judges/naacl_v2/rejudge_qwen35_9b.jsonl",
                        help="v2 rejudge JSONL that stores judge_prompt_system/user and original_judge")
    parser.add_argument("--model", default="z-ai/glm-5.3-flash")
    parser.add_argument("--provider-order", default="novita/fp8")
    parser.add_argument("--n-pass", type=int, default=100)
    parser.add_argument("--n-fail", type=int, default=50)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--reasoning-effort", default="low")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    rows = [r for r in load_rows(Path(args.rejudge_file)) if r.get("judge_prompt_user")]
    sample = stratified_sample(rows, args.n_pass, args.n_fail, args.seed)
    routing = {"order": [args.provider_order], "allow_fallbacks": False, "require_parameters": True}
    llm = OpenAICompatibleLLM(
        "https://openrouter.ai/api/v1",
        args.model,
        provider="openrouter",
        reasoning_effort=args.reasoning_effort,
        provider_routing=routing,
        timeout_sec=180,
        call_label="v3_provider_equivalence",
    )
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    def run(row: dict) -> dict:
        started = time.time()
        record = {
            "item_id": row["item_id"],
            "graph_profile": row["graph_profile"],
            "category": row["category"],
            "item_source": row["item_source"],
            "zai_decision": row["original_judge"].get("llm_decision"),
            "zai_failure_reason": row["original_judge"].get("failure_reason", ""),
        }
        try:
            resp = llm.chat(
                system=row["judge_prompt_system"],
                user=row["judge_prompt_user"],
                temperature=0.0,
                max_tokens=args.max_tokens,
                response_format={"type": "json_object"},
            )
            data = json.loads(extract_json_text(resp.text))
            usage = resp.raw.get("usage") or {}
            record.update(
                new_decision=bool(data.get("pass", False)),
                new_failure_reason=str(data.get("failure_reason", "")),
                served_by=resp.raw.get("provider"),
                prompt_tokens=usage.get("prompt_tokens"),
                cached_tokens=(usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                cost_usd=usage.get("cost"),
                error=None,
            )
        except Exception as exc:  # recorded, never silently dropped
            record.update(new_decision=None, error=f"{type(exc).__name__}: {str(exc)[:300]}")
            if type(exc).__name__ == "BudgetExceededError":
                raise
        record["latency_s"] = round(time.time() - started, 3)
        return record

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(run, sample))
    with (out_dir / "items.jsonl").open("w") as handle:
        for record in results:
            handle.write(json.dumps(record) + "\n")

    ok = [r for r in results if r["new_decision"] is not None]
    pairs = [(r["zai_decision"], r["new_decision"]) for r in ok]
    agree = sum(a == b for a, b in pairs)
    prompt_tokens = sum(r.get("prompt_tokens") or 0 for r in ok)
    cached = sum(r.get("cached_tokens") or 0 for r in ok)
    summary = {
        "note": "PRIVATE items file; summary is shareable. Exact v2 judge prompts replayed.",
        "model": args.model,
        "provider_routing": routing,
        "reasoning_effort": args.reasoning_effort,
        "temperature": 0.0,
        "max_tokens": args.max_tokens,
        "sample": {"n": len(sample), "n_zai_pass": args.n_pass, "n_zai_fail": args.n_fail, "seed": args.seed},
        "errors": len(results) - len(ok),
        "served_by": dict(Counter(r.get("served_by") for r in ok)),
        "agreement": rate_with_ci(agree, len(pairs)),
        "cohen_kappa": cohen_kappa([a for a, _ in pairs], [b for _, b in pairs]),
        "confusion_zai_vs_new": {
            "pass_pass": sum(a and b for a, b in pairs),
            "pass_fail": sum(a and not b for a, b in pairs),
            "fail_pass": sum((not a) and b for a, b in pairs),
            "fail_fail": sum((not a) and (not b) for a, b in pairs),
        },
        "new_pass_rate_on_zai_pass": (
            sum(b for a, b in pairs if a) / max(1, sum(1 for a, _ in pairs if a))
        ),
        "new_pass_rate_on_zai_fail": (
            sum(b for a, b in pairs if not a) / max(1, sum(1 for a, _ in pairs if not a))
        ),
        "cache_hit_rate_tokens": cached / prompt_tokens if prompt_tokens else None,
        "prompt_tokens": prompt_tokens,
        "cached_tokens": cached,
        "cost_usd": round(sum(r.get("cost_usd") or 0 for r in ok), 6),
        "latency_s": {
            "median": statistics.median(r["latency_s"] for r in ok) if ok else None,
            "p90": sorted(r["latency_s"] for r in ok)[int(0.9 * (len(ok) - 1))] if ok else None,
        },
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in ("agreement", "cohen_kappa", "cache_hit_rate_tokens", "cost_usd", "latency_s", "errors")}, indent=1))


if __name__ == "__main__":
    main()
