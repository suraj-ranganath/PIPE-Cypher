"""Numbers for the human-validation appendix table that summary.json does not hold.

Reads resolved labels (``read_human_labels.py`` output), the adjudication file,
and the sampling key; prints agreement kappas with item-bootstrap intervals
(before discussion), the auditor cross-tab, auditor-split reweighted wrong
rates, and reweighted rates by graph, tier, and category.

PRIVATE inputs; the printed output holds no literal values.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipecypher.human_validation import item_outcomes  # noqa: E402


def kappa(pairs: list[tuple]) -> float:
    n = len(pairs)
    cats = sorted({x for p in pairs for x in p}, key=str)
    po = sum(a == b for a, b in pairs) / n
    pe = sum((sum(a == c for a, _ in pairs) / n) * (sum(b == c for _, b in pairs) / n) for c in cats)
    return (po - pe) / (1 - pe) if pe < 1 else float("nan")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", required=True, help="labels.jsonl from read_human_labels.py")
    parser.add_argument("--adjudication", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--auditor", default="gpt6_luna")
    parser.add_argument("--n-boot", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()

    labels = [json.loads(line) for line in Path(args.labels).read_text().splitlines() if line.strip()]
    adjudication = json.loads(Path(args.adjudication).read_text())
    key = {row["item_id"]: row for row in map(json.loads, Path(args.key).read_text().splitlines()) if row}
    outcomes = item_outcomes(labels, adjudication)

    by_item: dict[str, dict[str, dict]] = {}
    for label in labels:
        by_item.setdefault(label["item_id"], {})[label["annotator"]] = label
    shared = [item for item, group in by_item.items() if len(group) == 2]
    a_name, b_name = sorted(by_item[shared[0]]) if shared else ("A", "B")

    rng = random.Random(args.seed)
    print(f"Agreement on {len(shared)} shared items (before discussion):")
    views = {
        "reference three-way": lambda lab: lab["reference"],
        "correct vs not": lambda lab: lab["reference"] == "correct",
        "wrong vs not": lambda lab: lab["reference"] == "wrong",
    }
    for name, view in views.items():
        pairs = [(view(by_item[i][a_name]), view(by_item[i][b_name])) for i in shared]
        boots = []
        for _ in range(args.n_boot):
            sample = [pairs[rng.randrange(len(pairs))] for _ in pairs]
            value = kappa(sample)
            if value == value:
                boots.append(value)
        boots.sort()
        agree = sum(a == b for a, b in pairs) / len(pairs)
        lo, hi = boots[int(0.025 * len(boots))], boots[int(0.975 * len(boots)) - 1]
        print(f"  {name:20s} agree {agree:.1%}  kappa {kappa(pairs):.2f} [{lo:.2f}, {hi:.2f}]")

    def weighted(ids: list[str], field: str) -> float:
        total = sum(key[i]["weight"] for i in ids)
        return sum(key[i]["weight"] * outcomes[i][field] for i in ids) / total

    print(f"\nAuditor ({args.auditor}) vs resolved labels:")
    groups = {
        "flagged": [i for i in outcomes if key[i]["verdicts"].get(args.auditor) is False],
        "passed": [i for i in outcomes if key[i]["verdicts"].get(args.auditor) is True],
    }
    for name, ids in groups.items():
        o = [outcomes[i] for i in ids]
        wrong = sum(x["wrong"] for x in o)
        minor = sum(x["wrong_or_minor"] - x["wrong"] for x in o)
        correct_ambiguous = sum((1 - x["wrong_or_minor"]) * x["ambiguous"] for x in o)
        correct_clear = sum((1 - x["wrong_or_minor"]) * (1 - x["ambiguous"]) for x in o)
        print(f"  {name}: n={len(ids)} wrong={wrong:g} minor={minor:g} correct+ambiguous={correct_ambiguous:g} correct+clear={correct_clear:g}")
    for name, ids in groups.items():
        for field in ("wrong", "fail"):
            boots = sorted(weighted([ids[rng.randrange(len(ids))] for _ in ids], field) for _ in range(args.n_boot))
            print(f"  {name} reweighted {field}: {weighted(ids, field):.1%} [{boots[int(0.025 * args.n_boot)]:.1%}, {boots[int(0.975 * args.n_boot) - 1]:.1%}]")

    print("\nReweighted rates by slice (resolved labels):")
    for dim in ("graph_profile", "tier", "category"):
        for value in sorted({key[i][dim] for i in outcomes}):
            ids = [i for i in outcomes if key[i][dim] == value]
            print(
                f"  {dim}={value:20s} n={len(ids):2d} wrong {weighted(ids, 'wrong'):.1%} "
                f"wrong_or_minor {weighted(ids, 'wrong_or_minor'):.1%} ambiguous {weighted(ids, 'ambiguous'):.1%}"
            )


if __name__ == "__main__":
    main()
