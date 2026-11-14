#!/usr/bin/env python3
"""Reference-quality sensitivity: do model scores and rankings survive removing doubtful references?

Compares zero-shot projected EX of the 11 models on (a) the full release, (b) items the outside
auditor passed, and (c) human-labeled items whose reference was resolved as not wrong / fully correct.
Also reports retained coverage and where the strict-vs-projected gap comes from.
Reads existing artifacts only; makes no model calls.

Example:
  python scripts/reference_quality_sensitivity.py --output artifacts/naacl_results/reference_quality_sensitivity.json
"""
from __future__ import annotations
import argparse, itertools, json, sys
from collections import Counter, defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipecypher.human_validation import item_outcomes  # noqa: E402

MODELS = ["gpt6_luna", "glm53_flash", "gemma4_26b_a4b", "gpt_oss_20b", "mistral_small32_24b", "qwen3_coder_30b_a3b",
          "phi4", "qwen35_9b", "llama31_8b", "gemma3_12b", "gemma3_4b"]


def kendall_tau_b(x, y):
    conc = disc = tx = ty = 0
    for i, j in itertools.combinations(range(len(x)), 2):
        a, b = x[i] - x[j], y[i] - y[j]
        if a == 0 and b == 0:
            continue
        if a == 0:
            tx += 1
        elif b == 0:
            ty += 1
        elif a * b > 0:
            conc += 1
        else:
            disc += 1
    denom = ((conc + disc + tx) * (conc + disc + ty)) ** 0.5
    return (conc - disc) / denom if denom else float("nan")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export", default="artifacts/benchmarks/naacl_v3_full/all.jsonl")
    ap.add_argument("--audit", default="artifacts/naacl_v3/audit/full_gpt6luna_checklist.jsonl")
    ap.add_argument("--eval-root", default="artifacts/evaluations")
    ap.add_argument("--eval-prefix", default="naacl_v3_all")
    ap.add_argument("--human-dir", default="artifacts/human_validation_v3/v3d")
    ap.add_argument("--output", default="artifacts/naacl_results/reference_quality_sensitivity.json")
    args = ap.parse_args()

    items = {}
    by_key = {}
    for line in open(args.export):
        r = json.loads(line)
        items[r["id"]] = r
        by_key[f'{r["graph_profile"]}|{r["category"]}|{r["question"]}|{r["cypher"]}'] = r["id"]
    audit = {}
    for line in open(args.audit):
        r = json.loads(line)
        if r.get("accepted") and r["key"] in by_key and r.get("auditor_passed") is not None:
            audit[by_key[r["key"]]] = bool(r["auditor_passed"])
    hd = Path(args.human_dir)
    labels = [json.loads(l) for l in (hd / "results_adjudicated/labels.jsonl").read_text().splitlines() if l.strip()]
    outcomes = item_outcomes(labels, json.loads((hd / "adjudicated_labels.json").read_text()))
    key = {r["item_id"]: r for r in map(json.loads, (hd / "key.jsonl").read_text().splitlines()) if r}
    human_ids = {i: key[i].get("export_id") or key[i].get("id") or i for i in outcomes}

    scores = {}
    gap = Counter()
    for m in MODELS:
        per = {}
        for line in open(Path(args.eval_root) / f"{args.eval_prefix}_downstream_{m}" / "zero_shot_evaluation.jsonl"):
            r = json.loads(line)
            per[r["id"]] = (bool(r.get("execution_accuracy")), bool(r.get("projected_execution_accuracy")))
            if r.get("projected_execution_accuracy") and not r.get("execution_accuracy"):
                gold, req, mp = r.get("gold_result_columns") or [], r.get("required_gold_columns") or [], r.get("projection_mapping") or {}
                if r.get("projection_node_expansion"):
                    gap["prediction returned whole nodes"] += 1
                elif len(req) < len(gold):
                    gap["reference context columns not asked for"] += 1
                elif len(gold) > 1 and all(k == v for k, v in mp.items()):
                    gap["extra predicted columns only"] += 1
                else:
                    gap["column names (and possibly extra columns)"] += 1
        scores[m] = per

    subsets = {
        "full release": set(items),
        "auditor judged": set(audit),
        "auditor passed": {i for i, ok in audit.items() if ok},
        "auditor flagged": {i for i, ok in audit.items() if not ok},
    }
    hum_all = {human_ids[i] for i in outcomes if human_ids[i] in items}
    subsets["human-labeled (all)"] = hum_all
    subsets["human: reference not wrong"] = {human_ids[i] for i, o in outcomes.items() if o["wrong"] == 0 and human_ids[i] in items}
    subsets["human: fully correct"] = {human_ids[i] for i, o in outcomes.items() if o["wrong_or_minor"] == 0 and human_ids[i] in items}

    out = {"subsets": {}, "strict_projected_gap": dict(gap)}
    full = [sum(p for _, p in (scores[m][i] for i in subsets["full release"])) / len(subsets["full release"]) for m in MODELS]
    for name, ids in subsets.items():
        if not ids:
            continue
        acc = [sum(scores[m][i][1] for i in ids) / len(ids) for m in MODELS]
        cov = Counter((items[i]["graph_profile"], items[i]["difficulty"]) for i in ids)
        tier = {}
        for t in ("easy", "medium", "hard"):
            tid = [i for i in ids if items[i]["difficulty"] == t]
            if tid:
                accs = sorted(sum(scores[m][i][1] for i in tid) / len(tid) for m in MODELS)
                tier[t] = {"n": len(tid), "median": accs[len(accs) // 2]}
        order = sorted(MODELS, key=lambda m: -acc[MODELS.index(m)])
        out["subsets"][name] = {
            "n": len(ids), "accuracy": dict(zip(MODELS, [round(a, 4) for a in acc])),
            "median": sorted(acc)[len(acc) // 2], "kendall_tau_vs_full": kendall_tau_b(full, acc),
            "ranking": order, "coverage": {f"{g}/{t}": n for (g, t), n in sorted(cov.items())}, "tier_median": tier,
        }
        print(f"{name:28s} n={len(ids):4d} median={sorted(acc)[5]:.3f} tau_vs_full={kendall_tau_b(full, acc):.3f} top4={order[:4]}")
        print("   ", " ".join(f"{a:.2f}" for a in acc), "| tiers", {t: (v['n'], round(v['median'], 2)) for t, v in tier.items()})
    tot = sum(gap.values())
    print("strict-fail/projected-pass predictions:", tot, {k: f"{v / tot:.0%}" for k, v in gap.most_common()})
    Path(args.output).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
