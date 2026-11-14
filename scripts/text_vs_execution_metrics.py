#!/usr/bin/env python3
"""How well do text-overlap metrics on Cypher track execution correctness?

For each stored zero-shot prediction on the v3 release: normalized exact string match and
Google-BLEU (1-4 gram, min of precision and recall) against the reference Cypher, compared with
projected execution accuracy. No model calls and no graph access.

Example: python scripts/text_vs_execution_metrics.py --output artifacts/naacl_results/text_vs_execution.json
"""
from __future__ import annotations
import argparse, itertools, json, re, statistics
from collections import Counter
from pathlib import Path

MODELS = ["gpt6_luna", "glm53_flash", "gemma4_26b_a4b", "gpt_oss_20b", "mistral_small32_24b", "qwen3_coder_30b_a3b",
          "phi4", "qwen35_9b", "llama31_8b", "gemma3_12b", "gemma3_4b"]
TOK = re.compile(r"[A-Za-z_][A-Za-z_0-9]*|\d+(?:\.\d+)?|'[^']*'|\"[^\"]*\"|<>|<=|>=|->|<-|[^\sA-Za-z_0-9]")


def norm(q: str) -> str:
    return re.sub(r"\s+", " ", q.strip().rstrip(";")).lower()


def gleu(pred: str, ref: str) -> float:
    p, r = TOK.findall(pred), TOK.findall(ref)
    match = tp = tr = 0
    for n in range(1, 5):
        cp = Counter(tuple(p[i:i + n]) for i in range(len(p) - n + 1))
        cr = Counter(tuple(r[i:i + n]) for i in range(len(r) - n + 1))
        match += sum((cp & cr).values()); tp += sum(cp.values()); tr += sum(cr.values())
    return 0.0 if not tp or not tr else min(match / tp, match / tr)


def tau(x, y):
    c = d = tx = ty = 0
    for i, j in itertools.combinations(range(len(x)), 2):
        a, b = x[i] - x[j], y[i] - y[j]
        if a == 0 and b == 0: continue
        if a == 0: tx += 1
        elif b == 0: ty += 1
        elif a * b > 0: c += 1
        else: d += 1
    return (c - d) / (((c + d + tx) * (c + d + ty)) ** 0.5)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eval-root", default="artifacts/evaluations")
    ap.add_argument("--eval-prefix", default="naacl_v3_all")
    ap.add_argument("--output", default="artifacts/naacl_results/text_vs_execution.json")
    args = ap.parse_args()
    good, bad, em_good, em_bad = [], [], 0, 0
    per_model = {}
    for m in MODELS:
        g, acc, n = [], 0, 0
        for line in open(Path(args.eval_root) / f"{args.eval_prefix}_downstream_{m}" / "zero_shot_evaluation.jsonl"):
            r = json.loads(line)
            if not r.get("predicted_cypher"):
                s, em = 0.0, False
            else:
                s, em = gleu(r["predicted_cypher"], r["gold_cypher"]), norm(r["predicted_cypher"]) == norm(r["gold_cypher"])
            ok = bool(r.get("projected_execution_accuracy"))
            (good if ok else bad).append(s)
            em_good += em and ok; em_bad += em and not ok
            g.append(s); acc += ok; n += 1
        per_model[m] = {"gleu": statistics.mean(g), "projected_ex": acc / n}
    med_good = statistics.median(good)
    out = {
        "predictions": len(good) + len(bad), "execution_correct": len(good),
        "exact_text_match_among_correct": em_good / len(good), "exact_text_match_among_wrong": em_bad / len(bad),
        "gleu_mean_correct": statistics.mean(good), "gleu_mean_wrong": statistics.mean(bad),
        "gleu_median_correct": med_good,
        "wrong_with_gleu_at_or_above_median_correct": sum(s >= med_good for s in bad) / len(bad),
        "correct_with_gleu_below_0.5": sum(s < 0.5 for s in good) / len(good),
        "model_rank_tau_gleu_vs_projected_ex": tau([per_model[m]["gleu"] for m in MODELS], [per_model[m]["projected_ex"] for m in MODELS]),
        "per_model": per_model,
    }
    for k, v in out.items():
        if k != "per_model": print(k, round(v, 4) if isinstance(v, float) else v)
    print({m: (round(v["gleu"], 3), round(v["projected_ex"], 3)) for m, v in per_model.items()})
    Path(args.output).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
