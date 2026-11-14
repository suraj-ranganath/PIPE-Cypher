#!/usr/bin/env python3
"""Judge v3 calibration on v2 items (development set; PRIVATE artifacts).

Subcommands:
  select   build the calibration set (stratified, oversampling v2 judge disagreement)
  run      run one or more judges (v2 or v3 checklist prompt) on the calibration set
  report   agreement tables: judge vs Claude adjudication, judge vs judge, prompt ablation

The development reference is "Claude adjudication" (an LLM expert label written
item by item under the v3 convention sheet). It is never reported as human labels.

Judge spec for ``run --judge``: ``label=model@provider_order[:reasoning_effort]``,
for example ``glm=z-ai/glm-5.3-flash@novita/fp8:low`` or
``gemma4=google/gemma-4-26b-a4b-it@primeintellect/bf16:none``.

Keys come from the environment (OPENROUTER_API_KEY); never written anywhere.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from pipecypher.judge import (  # noqa: E402
    JUDGE_V3_PROMPT_SHA256,
    ChecklistJudge,
    LLMJudge,
    DeterministicJudge,
    render_judge_v3_prompt,
)
from pipecypher.judge_agreement import cohen_kappa, gwet_ac1, rate_with_ci  # noqa: E402
from pipecypher.llm import OpenAICompatibleLLM  # noqa: E402
from pipecypher.models import ExecutionResult, ValidationIssue, ValidationResult  # noqa: E402
from pipecypher.prompts import JUDGE_PROMPT, JUDGE_V3_PROMPT, JUDGE_V3_SYSTEM  # noqa: E402
from pipecypher.schema import load_schema  # noqa: E402

DEFAULT_DIR = ROOT / "artifacts/naacl_v3/calibration"
SCHEMAS = {"finbench": "configs/schema_finbench.json", "snb": "configs/schema_snb.json"}
CONFIGS = {"finbench": "configs/finbench_v2_glm.yaml", "snb": "configs/snb_v2_glm.yaml"}
# Allocation per (GLM, gpt-6-luna, Qwen) decision pattern; oversamples disagreement.
ALLOCATION = {
    (True, True, True): 30,
    (True, False, True): 35,
    (True, False, False): 20,
    (True, True, False): 20,
    (False, False, True): 20,
    (False, False, False): 10,
    (False, True, True): 11,
    (False, True, False): 4,
}


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open() if line.strip()]


def _validation_from_prompt(user_prompt: str, cypher: str) -> dict:
    match = re.search(r"Validation summary:\n(\{.*?\})\n\nReturn strict JSON", user_prompt, re.S)
    if not match:
        return {"ok": True, "issues": [], "features": {}}
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return {"ok": True, "issues": [], "features": {}}


def cmd_select(args: argparse.Namespace) -> None:
    gpt = {r["item_id"]: r for r in load_jsonl(Path(args.gpt6))}
    qwen = {r["item_id"]: r for r in load_jsonl(Path(args.qwen))}
    rng = random.Random(args.seed)
    by_pattern: dict[tuple, list[str]] = defaultdict(list)
    for item_id, row in qwen.items():
        if item_id not in gpt or row.get("decision") is None or gpt[item_id].get("decision") is None:
            continue
        pattern = (bool(row["original_judge"]["llm_decision"]), bool(gpt[item_id]["decision"]), bool(row["decision"]))
        by_pattern[pattern].append(item_id)
    chosen: list[str] = []
    for pattern, n in ALLOCATION.items():
        pool = sorted(by_pattern.get(pattern, []))
        rng.shuffle(pool)
        # alternate graphs for balance
        fin = [i for i in pool if qwen[i]["graph_profile"] == "finbench"]
        snb = [i for i in pool if qwen[i]["graph_profile"] == "snb"]
        picked: list[str] = []
        while len(picked) < n and (fin or snb):
            for src in (fin, snb):
                if src and len(picked) < n:
                    picked.append(src.pop())
        chosen.extend(picked)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "calibration_items.jsonl").open("w") as handle:
        for item_id in chosen:
            q, g = qwen[item_id], gpt[item_id]
            validation = _validation_from_prompt(q["judge_prompt_user"], q["cypher"])
            handle.write(
                json.dumps(
                    {
                        "item_id": item_id,
                        "graph_profile": q["graph_profile"],
                        "category": q["category"],
                        "item_source": q["item_source"],
                        "question": q["question"],
                        "cypher": q["cypher"],
                        "rows_shown": q["execution_rows_shown"],
                        "row_count": q.get("result_row_count_observed"),
                        "validation": validation,
                        "v2_judge_system": q["judge_prompt_system"],
                        "v2_judge_user": q["judge_prompt_user"],
                        "v2_decisions": {
                            "glm": q["original_judge"]["llm_decision"],
                            "gpt6_luna": g["decision"],
                            "qwen35_9b": q["decision"],
                        },
                        "v2_reasons": {
                            "glm": q["original_judge"].get("failure_reason", ""),
                            "gpt6_luna": (g.get("scores") or {}).get("failure_reason", ""),
                            "qwen35_9b": (q.get("scores") or {}).get("failure_reason", ""),
                        },
                    }
                )
                + "\n"
            )
    counts = Counter(qwen[i]["graph_profile"] for i in chosen)
    print(json.dumps({"n": len(chosen), "by_graph": counts, "seed": args.seed}))


def _schemas() -> dict[str, Any]:
    schemas = {}
    for graph, path in SCHEMAS.items():
        schema = load_schema(ROOT / path)
        cfg = yaml.safe_load((ROOT / CONFIGS[graph]).read_text())
        symmetric = ((cfg.get("generation") or {}).get("symmetric_relationships")) or []
        if symmetric:
            schema.symmetric_relationships = sorted({*schema.symmetric_relationships, *symmetric})
        schemas[graph] = schema
    return schemas


def _validation(item: dict) -> ValidationResult:
    data = item.get("validation") or {}
    issues = [ValidationIssue(**issue) for issue in data.get("issues", []) if isinstance(issue, dict)]
    ok = bool(data.get("ok", True))
    return ValidationResult(
        read_only=True,
        syntax_valid=True,
        schema_valid=ok,
        normalized_cypher=item["cypher"],
        issues=issues,
        structural_features=data.get("features") or {},
    )


def _parse_judge_spec(spec: str) -> dict:
    label, rest = spec.split("=", 1)
    model, _, routing = rest.partition("@")
    order, _, effort = routing.partition(":")
    return {"label": label, "model": model, "order": order, "effort": effort or None}


def cmd_run(args: argparse.Namespace) -> None:
    items = load_jsonl(Path(args.items))
    if args.limit:
        items = items[: args.limit]
    schemas = _schemas()
    out_dir = Path(args.output_dir) / args.tag
    out_dir.mkdir(parents=True, exist_ok=True)
    fallback = DeterministicJudge()
    for raw_spec in args.judge:
        spec = _parse_judge_spec(raw_spec)
        if spec["order"] == "openai":
            # Direct OpenAI endpoint (gpt-6-luna; key from OPENAI_API_KEY), public graphs only.
            llm = OpenAICompatibleLLM(
                "https://api.openai.com/v1",
                spec["model"],
                provider="openai",
                reasoning_effort=spec["effort"],
                send_temperature=False,
                timeout_sec=240,
                call_label=f"v3_calibration:{args.tag}:{spec['label']}",
            )
        else:
            routing = {"order": [spec["order"]], "allow_fallbacks": False, "require_parameters": True}
            llm = OpenAICompatibleLLM(
                "https://openrouter.ai/api/v1",
                spec["model"],
                provider="openrouter",
                reasoning_effort=spec["effort"],
                provider_routing=routing,
                timeout_sec=240,
                call_label=f"v3_calibration:{args.tag}:{spec['label']}",
            )
        if args.prompt == "v3":
            judge: Any = ChecklistJudge(llm, label=spec["label"], max_tokens=args.max_tokens, schema_mode=args.schema_mode)
        else:
            judge = None  # v2: replay stored prompt below

        def run(item: dict) -> dict:
            started = time.time()
            execution = ExecutionResult(success=True, rows=item["rows_shown"])
            record: dict[str, Any] = {"item_id": item["item_id"], "judge": spec["label"], "model": spec["model"],
                                      "provider_order": spec["order"], "prompt": args.prompt}
            if args.prompt == "v3":
                result = judge.judge(
                    question=item["question"],
                    cypher=item["cypher"],
                    schema=schemas[item["graph_profile"]],
                    validation=_validation(item),
                    execution=execution,
                    row_count=item.get("row_count"),
                )
                record.update(passed=result.passed, failure_reason=result.failure_reason, raw=result.raw,
                              error=result.raw.get("judge_error"))
            else:
                v2 = LLMJudge(llm, fallback, max_tokens=args.max_tokens, fail_closed=True)
                try:
                    data = llm.chat_json(system=item["v2_judge_system"], user=item["v2_judge_user"], temperature=0.0,
                                         max_tokens=args.max_tokens, response_format={"type": "json_object"})
                    record.update(passed=bool(data.get("pass", False)), failure_reason=str(data.get("failure_reason", "")),
                                  raw=data, error=None)
                except Exception as exc:
                    record.update(passed=False, failure_reason=f"error: {exc}"[:300], raw={}, error=str(exc)[:300])
                del v2
            record["latency_s"] = round(time.time() - started, 3)
            return record

        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            results = list(pool.map(run, items))
        path = out_dir / f"{spec['label']}.jsonl"
        with path.open("w") as handle:
            for record in results:
                handle.write(json.dumps(record, default=str) + "\n")
        errors = sum(1 for r in results if r.get("error"))
        print(json.dumps({"judge": spec["label"], "n": len(results), "pass_rate": round(sum(r["passed"] for r in results) / len(results), 3),
                          "errors": errors, "median_latency_s": statistics.median(r["latency_s"] for r in results)}))
    meta = {
        "tag": args.tag,
        "prompt": args.prompt,
        "schema_mode": args.schema_mode,
        "v3_prompt_sha256": JUDGE_V3_PROMPT_SHA256 if args.prompt == "v3" else None,
        "judges": args.judge,
        "items": args.items,
        "n_items": len(items),
        "max_tokens": args.max_tokens,
    }
    (out_dir / f"meta_{int(time.time())}.json").write_text(json.dumps(meta, indent=2) + "\n")


def _binary_adjudication(label: str) -> bool | None:
    if label == "correct":
        return True
    if label in {"wrong", "ambiguous"}:
        return False
    return None


def cmd_report(args: argparse.Namespace) -> None:
    adjudication = {r["item_id"]: r for r in load_jsonl(Path(args.adjudication))}
    items = {r["item_id"]: r for r in load_jsonl(Path(args.items))}
    runs: dict[str, dict[str, dict]] = {}
    for run_spec in args.run:
        name, path = run_spec.split("=", 1)
        runs[name] = {r["item_id"]: r for r in load_jsonl(Path(path))}
    # Panel gates: an item passes only if every listed run passes it.
    for panel_spec in args.panel:
        name, members = panel_spec.split("=", 1)
        member_names = members.split("+")
        common = set(items)
        for member in member_names:
            common &= set(runs[member])
        runs[name] = {
            i: {"item_id": i, "passed": all(bool(runs[m][i].get("passed")) for m in member_names)}
            for i in common
        }
    # v2 stored decisions as extra "runs"
    for judge in ("glm", "gpt6_luna", "qwen35_9b"):
        runs[f"v2stored_{judge}"] = {
            i: {"item_id": i, "passed": bool(item["v2_decisions"][judge])} for i, item in items.items()
        }
    ids = [i for i in items if _binary_adjudication(adjudication.get(i, {}).get("label", "")) is not None]
    gold = {i: _binary_adjudication(adjudication[i]["label"]) for i in ids}
    table = {}
    for name, rows in runs.items():
        common = [i for i in ids if i in rows and rows[i].get("passed") is not None]
        a = [gold[i] for i in common]
        b = [bool(rows[i]["passed"]) for i in common]
        tp = sum(x and y for x, y in zip(a, b))
        fp = sum((not x) and y for x, y in zip(a, b))
        fn = sum(x and (not y) for x, y in zip(a, b))
        tn = sum((not x) and (not y) for x, y in zip(a, b))
        table[name] = {
            "n": len(common),
            "pass_rate": round(sum(b) / len(b), 3) if b else None,
            "agreement_with_adjudication": rate_with_ci(sum(x == y for x, y in zip(a, b)), len(common)),
            "kappa_with_adjudication": cohen_kappa(a, b),
            "ac1_with_adjudication": gwet_ac1(a, b),
            "precision_accept": round(tp / (tp + fp), 3) if tp + fp else None,
            "recall_accept": round(tp / (tp + fn), 3) if tp + fn else None,
            "false_accepts": fp,
            "false_rejects": fn,
            "true_rejects": tn,
        }
    pairwise = {}
    names = sorted(runs)
    for i, x in enumerate(names):
        for y in names[i + 1:]:
            common = [k for k in items if k in runs[x] and k in runs[y]
                      and runs[x][k].get("passed") is not None and runs[y][k].get("passed") is not None]
            a = [bool(runs[x][k]["passed"]) for k in common]
            b = [bool(runs[y][k]["passed"]) for k in common]
            pairwise[f"{x}|{y}"] = {
                "n": len(common),
                "agreement": round(sum(p == q for p, q in zip(a, b)) / len(common), 3) if common else None,
                "kappa": cohen_kappa(a, b),
            }
    adj_counts = Counter(adjudication[i]["label"] for i in items if i in adjudication)
    report = {
        "note": "Development calibration on v2 items. Reference = Claude adjudication (LLM expert labels under the v3 convention sheet), not human labels.",
        "adjudication_counts": dict(adj_counts),
        "n_items": len(items),
        "per_judge": table,
        "pairwise": pairwise,
    }
    out = Path(args.output)
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(f"{'judge':40s} {'n':>4s} {'pass':>6s} {'agree':>6s} {'kappa':>6s} {'FA':>4s} {'FR':>4s}")
    for name, row in sorted(table.items()):
        kappa = row["kappa_with_adjudication"]
        print(f"{name:40s} {row['n']:4d} {row['pass_rate'] or 0:6.3f} {row['agreement_with_adjudication']['rate']:6.3f} "
              f"{(kappa if kappa is not None else float('nan')):6.3f} {row['false_accepts']:4d} {row['false_rejects']:4d}")
    if args.show_pairs:
        for key, row in sorted(pairwise.items()):
            if any(s in key for s in args.show_pairs.split(",")):
                print(f"  {key:70s} n={row['n']} agree={row['agreement']} kappa={row['kappa']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sel = sub.add_parser("select")
    sel.add_argument("--gpt6", default="artifacts/judges/naacl_v2/rejudge_gpt6_luna.jsonl")
    sel.add_argument("--qwen", default="artifacts/judges/naacl_v2/rejudge_qwen35_9b.jsonl")
    sel.add_argument("--seed", type=int, default=2027)
    sel.add_argument("--output-dir", default=str(DEFAULT_DIR))
    sel.set_defaults(func=cmd_select)
    run = sub.add_parser("run")
    run.add_argument("--items", default=str(DEFAULT_DIR / "calibration_items.jsonl"))
    run.add_argument("--judge", action="append", required=True)
    run.add_argument("--prompt", choices=["v2", "v3"], default="v3")
    run.add_argument("--schema-mode", choices=["full", "slice"], default="full")
    run.add_argument("--tag", required=True)
    run.add_argument("--limit", type=int, default=0)
    run.add_argument("--max-tokens", type=int, default=2048)
    run.add_argument("--concurrency", type=int, default=8)
    run.add_argument("--output-dir", default=str(DEFAULT_DIR / "runs"))
    run.set_defaults(func=cmd_run)
    rep = sub.add_parser("report")
    rep.add_argument("--items", default=str(DEFAULT_DIR / "calibration_items.jsonl"))
    rep.add_argument("--adjudication", default=str(DEFAULT_DIR / "claude_adjudication.jsonl"))
    rep.add_argument("--run", action="append", default=[], help="name=path/to/judge.jsonl")
    rep.add_argument("--output", required=True)
    rep.add_argument("--show-pairs", default="")
    rep.add_argument("--panel", action="append", default=[], help="name=runA+runB (AND gate over named runs)")
    rep.set_defaults(func=cmd_report)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
