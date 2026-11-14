#!/usr/bin/env python3
"""G1 go/no-go audit for a v3 pilot (or any v3 build): record-level checks.

Reads every ``records.jsonl`` under the given run directories plus the spend
ledger and writes ``pilot_audit.json`` with one entry per check (value,
threshold, pass). Export-level checks (redaction residual, ties on the export)
run separately through scripts/audit_redaction_policy.py and
scripts/audit_limit_ties.py; pass their summaries with --extra NAME=PATH so the
verdict covers them too.

Example:
  python scripts/audit_v3_pilot.py --runs artifacts/runs/*naacl_v3_pilot* \
      --ledger artifacts/naacl_v3/ledgers/naacl_v3_pilot_generation_spend.jsonl \
      --planned-items 3200 --budget-usd 4.0 --output experiments/snapshots/20261113_naacl_v3/pilot_audit.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipecypher.diversity_metrics import self_bleu  # noqa: E402
from pipecypher.literal_consistency import literal_consistency_problems  # noqa: E402

V2_REFERENCE = {
    "empty_reject_share": 1220 / 5031,
    "self_bleu": 0.87,
    "judge_kappa": 0.22,
    "tier_mix": {"easy": 134, "medium": 81, "hard": 1},
}


def _records(run_dirs: list[str]) -> list[dict]:
    rows = []
    for raw in run_dirs:
        path = Path(raw)
        files = [path] if path.is_file() else sorted(path.rglob("records.jsonl"))
        for file in files:
            for line in file.open(encoding="utf-8"):
                if line.strip():
                    row = json.loads(line)
                    row["_run"] = str(file.parent.name)
                    rows.append(row)
    return rows


def _kappa(pairs: list[tuple[bool, bool]]) -> float | None:
    if not pairs:
        return None
    n = len(pairs)
    agree = sum(a == b for a, b in pairs) / n
    pa = sum(a for a, _ in pairs) / n
    pb = sum(b for _, b in pairs) / n
    expected = pa * pb + (1 - pa) * (1 - pb)
    return None if expected >= 1 else (agree - expected) / (1 - expected)


def _panel_votes(judge: dict) -> list[bool] | None:
    raw = judge.get("raw") or {}
    for key in ("panel", "judges", "per_judge"):
        votes = raw.get(key)
        if isinstance(votes, list) and len(votes) >= 2:
            out = []
            for vote in votes:
                if isinstance(vote, dict) and "passed" in vote:
                    out.append(bool(vote["passed"]))
            if len(out) >= 2:
                return out
        if isinstance(votes, dict) and len(votes) >= 2:
            out = [bool(v.get("passed")) for v in votes.values() if isinstance(v, dict) and "passed" in v]
            if len(out) >= 2:
                return out
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", nargs="+", required=True)
    parser.add_argument("--ledger", action="append", default=[])
    parser.add_argument("--planned-items", type=int, default=3200)
    parser.add_argument("--budget-usd", type=float, default=4.0, help="Generation budget for the full build")
    parser.add_argument("--extra", action="append", default=[], help="NAME=summary.json from export-level audits")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    rows = _records(args.runs)
    accepted = [r for r in rows if r.get("accepted")]
    reasons = Counter(((r.get("judge") or {}).get("failure_reason") or "accepted") for r in rows)
    executed = [r for r in rows if (r.get("execution") or {}).get("success")]
    empty = sum(1 for r in rows if ((r.get("judge") or {}).get("failure_reason") or "") == "execution returned no rows")

    literal_problems = []
    for r in accepted:
        bound = [v for v in r.get("entity_values") or []]
        problems = literal_consistency_problems(r.get("question", ""), r.get("cypher", ""), bound, ignore_limits=[200, 300])
        if problems:
            literal_problems.append({"question": r.get("question"), "cypher": r.get("cypher"), "problems": problems})

    tiers = Counter((r.get("generation_metadata") or {}).get("difficulty_tier", "unknown") for r in accepted)
    tier_share = {t: tiers[t] / max(1, len(accepted)) for t in ("easy", "medium", "hard")}
    target_share = {"easy": 0.35, "medium": 0.35, "hard": 0.30}

    by_cell_questions: dict[str, list[str]] = defaultdict(list)
    for r in accepted:
        by_cell_questions[f"{r.get('graph_profile')}:{r.get('category')}"].append(r.get("question", ""))
    all_questions = [r.get("question", "") for r in accepted]
    sbleu = self_bleu(all_questions) if len(all_questions) > 2 else None

    votes = [_panel_votes(r.get("judge") or {}) for r in rows]
    pairs = [(v[0], v[1]) for v in votes if v]
    kappa = _kappa(pairs)

    binding = Counter()
    agreement = Counter()
    sources = Counter()
    realization = Counter()
    for r in rows:
        meta = r.get("generation_metadata") or {}
        b = meta.get("binding") or {}
        if b:
            binding[str(b.get("binding_source"))] += 1
        if r.get("accepted"):
            sources[str(meta.get("reference_source"))] += 1
            if "template_cypher_agreement" in meta:
                agreement[str(meta.get("template_cypher_agreement"))] += 1
            realization[str(meta.get("question_realization", "")).split(":")[0]] += 1

    cost = 0.0
    calls = 0
    cached = 0
    prompt_tokens = 0
    for ledger in args.ledger:
        for line in Path(ledger).open(encoding="utf-8"):
            if not line.strip():
                continue
            entry = json.loads(line)
            cost += float(entry.get("cost_usd") or 0.0)
            calls += 1
            cached += int(entry.get("cached_tokens") or 0)
            prompt_tokens += int(entry.get("prompt_tokens") or 0)
    cost_per_item = cost / max(1, len(accepted))
    projected = cost_per_item * args.planned_items

    checks = {
        "empty_reject_share": {
            "value": empty / max(1, len(rows)), "threshold": "< 0.05", "pass": empty / max(1, len(rows)) < 0.05,
            "v2": V2_REFERENCE["empty_reject_share"],
        },
        "accepted_literal_mismatches": {"value": len(literal_problems), "threshold": "== 0", "pass": not literal_problems},
        "tier_mix_max_deviation": {
            "value": max(abs(tier_share[t] - target_share[t]) for t in target_share) if accepted else None,
            "shares": tier_share, "counts": dict(tiers), "threshold": "<= 0.10",
            "pass": bool(accepted) and max(abs(tier_share[t] - target_share[t]) for t in target_share) <= 0.10,
        },
        "panel_kappa": {"value": kappa, "n": len(pairs), "threshold": ">= 0.6", "pass": kappa is not None and kappa >= 0.6,
                        "v2": V2_REFERENCE["judge_kappa"]},
        "self_bleu": {"value": sbleu, "threshold": "< 0.81", "pass": sbleu is not None and sbleu < 0.81, "v2": V2_REFERENCE["self_bleu"]},
        "projected_generation_cost_usd": {"value": projected, "per_item": cost_per_item, "threshold": f"<= {args.budget_usd}",
                                          "pass": projected <= args.budget_usd},
    }
    for item in args.extra:
        name, path = item.split("=", 1)
        checks[name] = json.loads(Path(path).read_text())

    report = {
        "records": len(rows),
        "accepted": len(accepted),
        "executed": len(executed),
        "acceptance_rate": len(accepted) / max(1, len(rows)),
        "failure_reasons": dict(reasons.most_common(25)),
        "binding_sources": dict(binding),
        "reference_sources": dict(sources),
        "template_cypher_agreement": dict(agreement),
        "question_realization": dict(realization),
        "spend": {"usd": round(cost, 4), "calls": calls, "cache_hit_share": cached / max(1, prompt_tokens),
                  "calls_per_accepted": calls / max(1, len(accepted))},
        "accepted_by_cell": {cell: len(qs) for cell, qs in sorted(by_cell_questions.items())},
        "checks": checks,
        "all_record_checks_pass": all(c.get("pass", True) for c in checks.values() if isinstance(c, dict)),
        "literal_problem_examples": literal_problems[:20],
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(json.dumps({k: v.get("pass") for k, v in checks.items() if isinstance(v, dict)}, indent=1))
    print(f"accepted {len(accepted)}/{len(rows)}; spend ${cost:.4f}; projected ${projected:.2f} for {args.planned_items}")


if __name__ == "__main__":
    main()
