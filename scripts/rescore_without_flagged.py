#!/usr/bin/env python3
"""Re-score v2 held-out downstream results without items an audit flagged.

Reads the flagged ids from an audit's items.jsonl (rows whose `--split-field`
equals 'test') and recomputes projected EX per model and condition, the
median shift, the largest per-model shift, and Kendall tau between the full
and clean model rankings.
"""
from __future__ import annotations

import argparse
import glob
import itertools
import json
import statistics
from pathlib import Path

CONDITIONS = {
    "zero_standard": ("artifacts/evaluations/naacl_v2_heldout_downstream_*/zero_shot_evaluation.jsonl", "naacl_v2_heldout_downstream_", ""),
    "zero_governed": ("artifacts/evaluations/naacl_v2_heldout_promptfmt_*_zero_pipe_governed/*evaluation.jsonl", "naacl_v2_heldout_promptfmt_", "_zero_pipe_governed"),
    "few_shot": ("artifacts/evaluations/naacl_v2_heldout_control_*_ordered_logged/few_shot_evaluation.jsonl", "naacl_v2_heldout_control_", "_ordered_logged"),
}


def tau(a: dict, b: dict) -> float:
    c = d = 0
    for i, j in itertools.combinations(list(a), 2):
        s = (a[i] - a[j]) * (b[i] - b[j])
        c += s > 0
        d += s < 0
    return (c - d) / max(1, c + d)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flagged", required=True)
    parser.add_argument("--split-field", default="heldout")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    flag = {json.loads(l)["id"] for l in open(args.flagged) if l.strip() and json.loads(l).get(args.split_field) == "test"}
    out = {"dropped_flagged_test_items": len(flag), "conditions": {}}
    for cond, (pattern, prefix, suffix) in CONDITIONS.items():
        per = {}
        for f in sorted(glob.glob(pattern)):
            model = Path(f).parent.name.replace(prefix, "").replace(suffix, "")
            rows = [json.loads(l) for l in open(f) if l.strip()]
            clean = [r for r in rows if r["id"] not in flag]
            flagged = [r for r in rows if r["id"] in flag]
            per[model] = {
                "full": round(statistics.mean(bool(r["projected_execution_accuracy"]) for r in rows), 4),
                "clean": round(statistics.mean(bool(r["projected_execution_accuracy"]) for r in clean), 4),
                "n_full": len(rows), "n_clean": len(clean),
                "acc_on_flagged": round(statistics.mean(bool(r["projected_execution_accuracy"]) for r in flagged), 4) if flagged else None,
            }
        full = {m: v["full"] for m, v in per.items()}
        clean = {m: v["clean"] for m, v in per.items()}
        out["conditions"][cond] = {
            "models": len(per), "median_full": statistics.median(full.values()), "median_clean": statistics.median(clean.values()),
            "max_abs_delta": max(abs(full[m] - clean[m]) for m in per), "kendall_tau_full_vs_clean": tau(full, clean),
            "median_acc_on_flagged": statistics.median(v["acc_on_flagged"] for v in per.values() if v["acc_on_flagged"] is not None),
            "per_model": per,
        }
        print(cond, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in out["conditions"][cond].items() if k != "per_model"})
    Path(args.output).write_text(json.dumps(out, indent=2) + "\n")


if __name__ == "__main__":
    main()
