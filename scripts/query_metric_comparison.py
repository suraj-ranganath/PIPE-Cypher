#!/usr/bin/env python3
"""Compare common query-evaluation metrics against execution correctness on stored predictions.

Metric families: text overlap (normalized exact string match, Google-BLEU, BLEU-4, ROUGE-L,
Jaro-Winkler), structure (same query signature: literals and names abstracted), and execution
(strict EX, answer F1, projected EX). Correctness is projected EX. No model calls, no graph access.

Example: python scripts/query_metric_comparison.py --output artifacts/naacl_results/query_metric_comparison.json
"""
from __future__ import annotations
import argparse, itertools, json, re, statistics, sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipecypher.diversity_metrics import canonical_query_signature  # noqa: E402
from pipecypher.text_metrics import jaro_winkler_similarity, rouge_l, sentence_bleu  # noqa: E402

MODELS = ["gpt6_luna", "glm53_flash", "gemma4_26b_a4b", "gpt_oss_20b", "mistral_small32_24b", "qwen3_coder_30b_a3b",
          "phi4", "qwen35_9b", "llama31_8b", "gemma3_12b", "gemma3_4b"]
TOK = re.compile(r"[A-Za-z_][A-Za-z_0-9]*|\d+(?:\.\d+)?|'[^']*'|\"[^\"]*\"|<>|<=|>=|->|<-|[^\sA-Za-z_0-9]")


def norm(q): return re.sub(r"\s+", " ", q.strip().rstrip(";")).lower()


def gleu(p, r):
    match = tp = tr = 0
    for n in range(1, 5):
        cp = Counter(tuple(p[i:i + n]) for i in range(len(p) - n + 1)); cr = Counter(tuple(r[i:i + n]) for i in range(len(r) - n + 1))
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


def auc(pos, neg):
    allv = sorted([(v, 1) for v in pos] + [(v, 0) for v in neg])
    rank_sum, i = 0.0, 0
    while i < len(allv):
        j = i
        while j < len(allv) and allv[j][0] == allv[i][0]: j += 1
        avg = (i + 1 + j) / 2
        rank_sum += avg * sum(lab for _, lab in allv[i:j]); i = j
    return (rank_sum - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eval-root", default="artifacts/evaluations"); ap.add_argument("--eval-prefix", default="naacl_v3_all")
    ap.add_argument("--output", default="artifacts/naacl_results/query_metric_comparison.json")
    args = ap.parse_args()
    names = ["exact_text", "same_signature", "google_bleu", "bleu4", "rouge_l", "jaro_winkler", "strict_ex", "answer_f1", "projected_ex"]
    vals = {n: {"pos": [], "neg": []} for n in names}
    per_model = {n: {} for n in names}
    for m in MODELS:
        acc = {n: [] for n in names}
        for line in open(Path(args.eval_root) / f"{args.eval_prefix}_downstream_{m}" / "zero_shot_evaluation.jsonl"):
            r = json.loads(line); pred, gold = r.get("predicted_cypher") or "", r["gold_cypher"]
            ok = bool(r.get("projected_execution_accuracy"))
            if pred.strip():
                pt, gt = TOK.findall(pred), TOK.findall(gold)
                try: sig = canonical_query_signature(pred) == canonical_query_signature(gold)
                except Exception: sig = False
                row = {"exact_text": float(norm(pred) == norm(gold)), "same_signature": float(sig), "google_bleu": gleu(pt, gt),
                       "bleu4": sentence_bleu(pt, gt), "rouge_l": rouge_l(pt, gt)["f1"], "jaro_winkler": jaro_winkler_similarity(norm(pred), norm(gold))}
            else:
                row = {n: 0.0 for n in names[:6]}
            row.update(strict_ex=float(bool(r.get("execution_accuracy"))), answer_f1=float(r.get("projected_answer_f1") or 0.0), projected_ex=float(ok))
            for n in names:
                vals[n]["pos" if ok else "neg"].append(row[n]); acc[n].append(row[n])
        for n in names: per_model[n][m] = statistics.mean(acc[n])
    ex = [per_model["projected_ex"][m] for m in MODELS]
    out = {}
    for n in names:
        pos, neg = vals[n]["pos"], vals[n]["neg"]; pm = [per_model[n][m] for m in MODELS]
        out[n] = {"mean_when_right": statistics.mean(pos), "mean_when_wrong": statistics.mean(neg), "auc": auc(pos, neg),
                  "model_min": min(pm), "model_max": max(pm), "rank_tau_vs_projected_ex": tau(pm, ex),
                  "glm_minus_gpt6luna": per_model[n]["glm53_flash"] - per_model[n]["gpt6_luna"]}
        print(f"{n:15s} right={out[n]['mean_when_right']:.3f} wrong={out[n]['mean_when_wrong']:.3f} auc={out[n]['auc']:.3f} "
              f"models {min(pm):.2f}-{max(pm):.2f} tau={out[n]['rank_tau_vs_projected_ex']:.2f} glm-gpt={out[n]['glm_minus_gpt6luna']:+.3f}")
    out["n_predictions"] = sum(len(vals["projected_ex"][k]) for k in ("pos", "neg")); out["n_right"] = len(vals["projected_ex"]["pos"])
    Path(args.output).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
