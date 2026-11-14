#!/usr/bin/env python3
"""Inspect PIPE-Cypher generation runs (pilot or full) before trusting them.

Reports, per graph/category: candidates, accepted, first blocking reason,
template origin (seed / schema_derived / llm / llm_induced), paraphrase
outcomes, accepted query signatures, difficulty mix, and samples of accepted
and rejected items for manual reading. Optionally joins the spend ledger.

Engineering diagnostics only; pilot numbers are never paper evidence.
"""

from __future__ import annotations

import argparse
import collections
import json
import random
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.diversity_metrics import canonical_query_signature  # noqa: E402


def _records(paths: list[str]) -> list[dict]:
    rows: list[dict] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            path = path / "records.jsonl"
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                row["_run"] = path.parent.name
                rows.append(row)
    return rows


def _reason(row: dict) -> str:
    if row.get("accepted"):
        return "accepted"
    judge = row.get("judge") or {}
    validation = row.get("validation") or {}
    execution = row.get("execution") or {}
    errors = [i.get("code") for i in validation.get("issues", []) if i.get("level") == "error"]
    if errors:
        return "validation:" + ",".join(sorted(set(errors)))[:60]
    if not execution.get("success"):
        return "execution:" + str(execution.get("error") or "")[:50]
    return "judge:" + str(judge.get("failure_reason") or "")[:60]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", nargs="+", required=True, help="Run dirs or records.jsonl files")
    parser.add_argument("--ledger", default="", help="Optional spend ledger JSONL")
    parser.add_argument("--ledger-label-prefix", default="", help="Only ledger rows whose label starts with this")
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--output", default="", help="Write the Markdown report here as well")
    args = parser.parse_args()

    rows = _records(args.runs)
    rng = random.Random(args.seed)
    out: list[str] = [f"# Generation inspection ({len(rows)} records)\n"]
    cells: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    for row in rows:
        cells[(str(row.get("graph_profile")), str(row.get("category")))].append(row)

    out.append("| graph | category | cand. | acc. | acc. sigs | origins (acc.) | paraphrase | difficulty (acc.) |")
    out.append("|---|---|---:|---:|---:|---|---|---|")
    totals = collections.Counter()
    for (graph, category), cell in sorted(cells.items()):
        accepted = [r for r in cell if r.get("accepted")]
        sigs = {canonical_query_signature(r.get("cypher") or "") for r in accepted}
        origins = collections.Counter((r.get("generation_metadata") or {}).get("template_origin", "?") for r in accepted)
        para = collections.Counter((r.get("generation_metadata") or {}).get("question_realization", "?") for r in cell)
        diff = collections.Counter(((r.get("validation") or {}).get("structural_features") or {}).get("difficulty", "?") for r in accepted)
        totals.update({"candidates": len(cell), "accepted": len(accepted)})
        out.append(
            f"| {graph} | {category} | {len(cell)} | {len(accepted)} | {len(sigs)} | "
            f"{dict(origins)} | {dict(para)} | {dict(diff)} |"
        )
    out.append(f"\nTotal: {totals['accepted']}/{totals['candidates']} accepted.\n")

    reasons = collections.Counter(_reason(r) for r in rows)
    out.append("## Outcomes (first blocking reason)\n")
    for reason, count in reasons.most_common(25):
        out.append(f"- {count:5d}  {reason}")

    fallback = sum(
        1 for r in rows if r.get("accepted") and "fallback_after_error" in ((r.get("judge") or {}).get("raw") or {})
    )
    fail_closed = sum(1 for r in rows if ((r.get("judge") or {}).get("raw") or {}).get("fail_closed"))
    out.append(f"\nAccepted via rule-based fallback judge: {fallback} (must be 0 for v2)")
    out.append(f"Rejected by fail-closed judge errors: {fail_closed}\n")

    out.append("## Samples\n")
    for (graph, category), cell in sorted(cells.items()):
        accepted = [r for r in cell if r.get("accepted")]
        rejected = [r for r in cell if not r.get("accepted")]
        out.append(f"### {graph} / {category}\n")
        for label, pool in (("ACCEPTED", accepted), ("REJECTED", rejected)):
            for row in rng.sample(pool, min(args.samples, len(pool))):
                meta = row.get("generation_metadata") or {}
                out.append(f"- **{label}** [{meta.get('template_origin', '?')}, {meta.get('question_realization', '?')}] {_reason(row)}")
                if meta.get("canonical_question") and meta.get("canonical_question") != row.get("question"):
                    out.append(f"  - template Q: {meta.get('canonical_question')}")
                out.append(f"  - Q: {row.get('question')}")
                out.append(f"  - C: `{row.get('cypher')}`")
                rows_sample = ((row.get("execution") or {}).get("rows") or [])[:2]
                out.append(f"  - rows: {json.dumps(rows_sample, default=str)[:200]}")
        out.append("")

    if args.ledger and Path(args.ledger).exists():
        ledger = [json.loads(line) for line in Path(args.ledger).read_text().splitlines() if line.strip()]
        ledger = [r for r in ledger if str(r.get("label") or "").startswith(args.ledger_label_prefix)]
        cost = sum(float(r.get("cost_usd") or 0) for r in ledger)
        served = collections.Counter(r.get("served_by") for r in ledger)
        out.append("## Spend\n")
        out.append(f"- calls={len(ledger)} cost_usd={cost:.4f} served_by={dict(served)}")
        if totals["accepted"]:
            out.append(f"- cost per accepted item: ${cost / totals['accepted']:.5f}")
            out.append(f"- calls per accepted item: {len(ledger) / totals['accepted']:.2f}")

    report = "\n".join(out) + "\n"
    print(report)
    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
