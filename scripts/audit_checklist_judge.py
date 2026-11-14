#!/usr/bin/env python3
"""Independent audit of v3 judge-panel decisions with the frozen checklist prompt.

Re-judges every candidate that reached the v3 judge panel (accepted and
rejected) with an auditor model that is NOT part of the gate (gpt-6-luna on
public graphs; owner decision 2026-11-11). Same frozen prompt, same schema,
same execution sample, so disagreement reflects the model, not the prompt.
Outputs are PRIVATE/internal and stay separate from the benchmark export.

Example:
  python scripts/audit_checklist_judge.py --records artifacts/runs/*naacl_v3_main*/records.jsonl \
      --model gpt-6-luna --provider openai --label gpt6luna \
      --output artifacts/naacl_v3/audit/gpt6luna_checklist.jsonl --concurrency 8
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipecypher.judge import ChecklistJudge  # noqa: E402
from pipecypher.llm import DEFAULT_BASE_URLS, OpenAICompatibleLLM  # noqa: E402
from pipecypher.models import ExecutionResult, ValidationIssue, ValidationResult  # noqa: E402
from pipecypher.schema import load_schema  # noqa: E402

SCHEMAS = {"finbench": "configs/schema_finbench.json", "snb": "configs/schema_snb.json"}
SYMMETRIC = {"snb": ["KNOWS"]}


def _validation(row: dict) -> ValidationResult:
    v = row.get("validation") or {}
    return ValidationResult(
        read_only=bool(v.get("read_only")),
        syntax_valid=bool(v.get("syntax_valid")),
        schema_valid=bool(v.get("schema_valid")),
        normalized_cypher=v.get("normalized_cypher") or row.get("cypher", ""),
        issues=[ValidationIssue(i.get("level", "warning"), i.get("code", ""), i.get("message", "")) for i in v.get("issues") or []],
        structural_features=v.get("structural_features") or {},
    )


def _execution(row: dict) -> ExecutionResult:
    e = row.get("execution") or {}
    return ExecutionResult(success=bool(e.get("success")), rows=e.get("rows") or [], error=e.get("error"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--records", nargs="+", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--label", default="auditor")
    parser.add_argument("--reasoning-effort", default=None)
    parser.add_argument("--routing", default="", help="OpenRouter provider routing JSON (provider=openrouter)")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--output", required=True)
    parser.add_argument("--schema", action="append", default=[], help="Extra graph=schema.json[:SYM1,SYM2] (symmetric relationship types after a colon)")
    args = parser.parse_args()

    candidates = []
    for path in args.records:
        for line in Path(path).open(encoding="utf-8"):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue  # a run still writing its last line; picked up on the next (resumed) pass
            if ((row.get("judge") or {}).get("raw") or {}).get("judge_mode") == "panel":
                row["_records_path"] = path
                candidates.append(row)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():
        for line in out.open(encoding="utf-8"):
            if line.strip():
                done.add(json.loads(line)["key"])
    schemas = {}
    for graph, path in SCHEMAS.items():
        schema = load_schema(path)
        schema.symmetric_relationships = SYMMETRIC.get(graph, [])
        schemas[graph] = schema
    for spec in args.schema:
        graph, rest = spec.split("=", 1)
        path, _, sym = rest.partition(":")
        schema = load_schema(path)
        schema.symmetric_relationships = [x for x in sym.split(",") if x]
        schemas[graph] = schema
    llm = OpenAICompatibleLLM(
        DEFAULT_BASE_URLS[args.provider],
        args.model,
        provider=args.provider,
        reasoning_effort=args.reasoning_effort,
        send_temperature=args.provider != "openai",
        provider_routing=json.loads(args.routing) if args.routing else None,
        timeout_sec=240,
        call_label=f"audit:{args.label}",
    )
    judge = ChecklistJudge(llm, label=args.label, max_tokens=args.max_tokens, schema_mode="full", fail_closed=True)
    lock = threading.Lock()

    def key_of(row: dict) -> str:
        return f"{row.get('graph_profile')}|{row.get('category')}|{row.get('question')}|{row.get('cypher')}"

    todo = [row for row in candidates if key_of(row) not in done]
    print(f"{len(candidates)} panel-judged candidates; {len(todo)} to audit")

    def work(row: dict) -> None:
        graph = row.get("graph_profile")
        if graph not in schemas:
            raise SystemExit(f"public graph schemas only; got {graph}")
        result = judge.judge(
            question=row["question"], cypher=row["cypher"], schema=schemas[graph],
            validation=_validation(row), execution=_execution(row),
        )
        panel = ((row.get("judge") or {}).get("raw") or {}).get("panel") or []
        record = {
            "key": key_of(row),
            "graph_profile": graph,
            "category": row.get("category"),
            "difficulty_tier": (row.get("generation_metadata") or {}).get("difficulty_tier"),
            "accepted": bool(row.get("accepted")),
            "panel_passed": bool((row.get("judge") or {}).get("passed")),
            "panel_members": {m.get("label"): bool(m.get("passed")) for m in panel},
            "auditor": args.label,
            "auditor_passed": result.passed,
            "auditor_failure_reason": result.failure_reason,
            "auditor_raw": result.raw,
        }
        with lock, out.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str) + "\n")

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(work, row) for row in todo]
        for future in as_completed(futures):
            future.result()
    print(f"audit written to {out}")


if __name__ == "__main__":
    main()
