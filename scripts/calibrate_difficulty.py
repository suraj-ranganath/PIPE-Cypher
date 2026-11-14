#!/usr/bin/env python3
"""Calibrate the structural difficulty score on v2 held-out solve rates.

Target: the fraction of downstream models whose zero-shot (standard prompt)
prediction is projected-execution correct on each v2 held-out test item.
Fits a non-negative ridge regression of hardness (1 - solve rate) on
structural Cypher features, with 5-fold cross-validation grouped by query
signature, then rounds the weights to integers and sets easy/medium/hard
thresholds at the 35th/70th score percentiles of the v2 test set.

Writes configs/difficulty_v3.json (weights, caps, thresholds, quotas) and a
JSON report. No model calls.

Example:
  python scripts/calibrate_difficulty.py \
      --test artifacts/benchmarks/naacl_v2_heldout/test.jsonl \
      --all artifacts/benchmarks/naacl_v2_heldout/all.jsonl \
      --eval-glob 'artifacts/evaluations/naacl_v2_heldout_downstream_*/zero_shot_evaluation.jsonl' \
      --output configs/difficulty_v3.json \
      --report experiments/snapshots/20261113_naacl_v3/difficulty_calibration.json
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipecypher.difficulty import TIERS, DifficultyModel, difficulty_features  # noqa: E402

# Candidate features (raw units). tokens_10 = query length in tokens / 10.
CANDIDATES = [
    "return_arity",
    "hops",
    "var_length",
    "stages",
    "grouping_keys",
    "negation",
    "temporal_refs",
    "rel_props",
    "order_by",
    "unwind_collect",
    "predicates",
    "optional_match",
    "aggregations",
    "labels",
]
CAPS = {
    "return_arity": 6,
    "hops": 4,
    "var_length": 2,
    "stages": 2,
    "grouping_keys": 3,
    "negation": 2,
    "temporal_refs": 3,
    "rel_props": 3,
    "unwind_collect": 2,
    "predicates": 4,
    "optional_match": 2,
    "aggregations": 3,
    "labels": 4,
    "tokens_10": 12,
}
SIMPLE = {"simple_retrieval", "simple_aggregation", "boolean_existence"}
GRAPH_ORDER = ("finbench", "snb")


def load_jsonl(path: str | Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).open() if line.strip()]


def solve_rates(paths: list[str], ids: set[str], field: str = "projected_execution_accuracy") -> tuple[dict[str, float], int]:
    solved: Counter[str] = Counter()
    seen: Counter[str] = Counter()
    for path in paths:
        for row in load_jsonl(path):
            if row["id"] in ids:
                seen[row["id"]] += 1
                solved[row["id"]] += bool(row.get(field))
    n_models = len(paths)
    missing = [i for i in ids if seen[i] != n_models]
    if missing:
        raise SystemExit(f"{len(missing)} items lack predictions from all {n_models} models")
    return {i: solved[i] / n_models for i in ids}, n_models


def capped(features: dict[str, float], names: list[str]) -> list[float]:
    return [min(features[name], CAPS.get(name, float("inf"))) for name in names]


def rank(values: np.ndarray) -> np.ndarray:
    order = values.argsort(kind="mergesort")
    ranks = np.empty(len(values))
    sorted_vals = values[order]
    i = 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and sorted_vals[j + 1] == sorted_vals[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2
        i = j + 1
    return ranks


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.corrcoef(rank(a), rank(b))[0, 1])


def nn_ridge(X: np.ndarray, y: np.ndarray, lam: float, iters: int = 3000) -> tuple[np.ndarray, float]:
    """Non-negative ridge by projected coordinate descent on standardized X."""

    mu = X.mean(axis=0)
    sd = X.std(axis=0)
    sd[sd == 0] = 1.0
    Z = (X - mu) / sd
    yc = y - y.mean()
    n, p = Z.shape
    beta = np.zeros(p)
    col_sq = (Z**2).sum(axis=0) + lam * n
    resid = yc - Z @ beta
    for _ in range(iters):
        delta = 0.0
        for k in range(p):
            old = beta[k]
            rho = Z[:, k] @ resid + (Z[:, k] ** 2).sum() * old
            new = max(0.0, rho / col_sq[k])
            if new != old:
                resid -= Z[:, k] * (new - old)
                beta[k] = new
                delta = max(delta, abs(new - old))
        if delta < 1e-9:
            break
    raw = beta / sd
    intercept = float(y.mean() - mu @ raw)
    return raw, intercept


def group_folds(groups: list[str], k: int = 5) -> list[int]:
    """Assign whole signature groups to folds, balancing fold sizes."""

    sizes = Counter(groups)
    ordered = sorted(sizes, key=lambda g: (-sizes[g], hashlib.sha1(g.encode()).hexdigest()))
    load = [0] * k
    fold_of: dict[str, int] = {}
    for group in ordered:
        fold = min(range(k), key=lambda f: (load[f], f))
        fold_of[group] = fold
        load[fold] += sizes[group]
    return [fold_of[g] for g in groups]


def integer_weights(raw: np.ndarray, names: list[str], scale: float) -> dict[str, float]:
    weights = {}
    for name, value in zip(names, raw):
        w = round(float(value) * scale)
        if w > 0:
            weights[name] = float(w)
    return weights


def score_rows(feats: list[dict[str, float]], model: DifficultyModel) -> np.ndarray:
    return np.array([model.score(f) for f in feats])


def pick_thresholds(scores: np.ndarray, shares=(0.35, 0.35, 0.30)) -> tuple[float, float]:
    """Thresholds t1 < t2 (tier = easy if s < t1, medium if s < t2) closest to the target shares."""

    values = sorted(set(scores.tolist()))
    cuts = [v for v in values] + [values[-1] + 1]
    best = None
    n = len(scores)
    for i, t1 in enumerate(cuts):
        for t2 in cuts[i + 1 :]:
            easy = float(np.mean(scores < t1))
            medium = float(np.mean((scores >= t1) & (scores < t2)))
            hard = 1 - easy - medium
            err = abs(easy - shares[0]) + abs(medium - shares[1]) + abs(hard - shares[2])
            if best is None or err < best[0] - 1e-12:
                best = (err, t1, t2)
    assert best is not None and n
    return float(best[1]), float(best[2])


def cluster_bootstrap_mean(values: list[float], groups: list[str], reps: int = 2000, seed: int = 13) -> tuple[float, float, float]:
    by_group: dict[str, list[float]] = defaultdict(list)
    for value, group in zip(values, groups):
        by_group[group].append(value)
    keys = list(by_group)
    rng = random.Random(seed)
    means = []
    for _ in range(reps):
        sample = [v for key in (rng.choice(keys) for _ in keys) for v in by_group[key]]
        means.append(sum(sample) / len(sample))
    means.sort()
    return (sum(values) / len(values), means[int(0.025 * reps)], means[int(0.975 * reps) - 1])


# Feasibility-aware tier shares per category. Each row sums to 1 and, with
# equal per-category targets, the overall mix is 35/35/30. Shares follow the
# v2 release's natural tier rates (all_release_per_category in the report),
# pushed toward balance: simple categories lean easy, path/complex retrieval
# lean hard, and ranking/negation sit in the middle. Cells whose v2 natural
# rate is far below the quota need tier-targeted template induction.
QUOTAS = {
    "simple_retrieval": {"easy": 0.65, "medium": 0.30, "hard": 0.05},
    "simple_aggregation": {"easy": 0.60, "medium": 0.28, "hard": 0.12},
    "boolean_existence": {"easy": 0.60, "medium": 0.32, "hard": 0.08},
    "complex_aggregation": {"easy": 0.50, "medium": 0.30, "hard": 0.20},
    "ranking_topk": {"easy": 0.15, "medium": 0.50, "hard": 0.35},
    "negation_difference": {"easy": 0.15, "medium": 0.50, "hard": 0.35},
    "complex_retrieval": {"easy": 0.10, "medium": 0.35, "hard": 0.55},
    "path_temporal": {"easy": 0.05, "medium": 0.25, "hard": 0.70},
    "_default": {"easy": 0.35, "medium": 0.35, "hard": 0.30},
}


def recommend_quotas(feasible: dict[str, Counter]) -> dict[str, dict[str, float]]:
    quotas = {cat: dict(shares) for cat, shares in QUOTAS.items()}
    for category in feasible:
        quotas.setdefault(category, dict(QUOTAS["_default"]))
    return quotas


def thin_cells(
    feasible_graph: dict[str, Counter], quotas: dict[str, dict[str, float]], target_per_cell: int
) -> list[dict]:
    """Cells where the v2 natural tier rate is below half the quota share."""

    rows = []
    for key, counter in sorted(feasible_graph.items()):
        graph, category = key.split(":", 1)
        total = sum(counter.values()) or 1
        shares = quotas.get(category, quotas["_default"])
        for tier in TIERS:
            natural = counter.get(tier, 0) / total
            need = shares.get(tier, 0.0)
            if need > 0 and natural < 0.5 * need:
                rows.append(
                    {
                        "graph": graph,
                        "category": category,
                        "tier": tier,
                        "v2_count": counter.get(tier, 0),
                        "v2_natural_share": round(natural, 3),
                        "quota_share": need,
                        "items_needed_at_target": round(need * target_per_cell),
                    }
                )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--test", required=True)
    parser.add_argument("--all", required=True)
    parser.add_argument("--eval-glob", required=True, help="zero-shot standard evaluations (calibration target)")
    parser.add_argument("--check-glob", action="append", default=[], help="NAME=GLOB other conditions to validate tiers on")
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--lambdas", default="0.01,0.1,0.3,1.0,3.0")
    parser.add_argument("--target-per-cell", type=int, default=200, help="planned items per (graph, category) in v3")
    args = parser.parse_args()

    test = load_jsonl(args.test)
    ids = {row["id"] for row in test}
    rates, n_models = solve_rates(sorted(glob.glob(args.eval_glob)), ids)
    y_solve = np.array([rates[row["id"]] for row in test])
    hardness = 1.0 - y_solve
    groups = [row.get("query_signature") or row["id"] for row in test]
    feats = [difficulty_features(row["cypher"]) for row in test]

    feature_sets = {
        "structural": list(CANDIDATES),
        "structural_plus_length": list(CANDIDATES) + ["tokens_10"],
    }
    folds = group_folds(groups)
    lambdas = [float(x) for x in args.lambdas.split(",")]
    cv_results: dict[str, dict[str, float]] = {}
    for set_name, names in feature_sets.items():
        X = np.array([capped(f, names) for f in feats])
        for lam in lambdas:
            oof = np.zeros(len(test))
            for fold in range(5):
                train = np.array([f != fold for f in folds])
                raw, intercept = nn_ridge(X[train], hardness[train], lam)
                oof[~train] = X[~train] @ raw + intercept
            cv_results[f"{set_name}@{lam}"] = {"cv_spearman_hardness": spearman(oof, hardness)}

    best_key = max(cv_results, key=lambda key: cv_results[key]["cv_spearman_hardness"])
    best_set, best_lam = best_key.split("@")
    # Prefer the structural-only set when it is within 0.02 rho of the best:
    # it is easier to explain and does not reward verbose aliasing.
    struct_best = max(
        (key for key in cv_results if key.startswith("structural@")),
        key=lambda key: cv_results[key]["cv_spearman_hardness"],
    )
    if cv_results[best_key]["cv_spearman_hardness"] - cv_results[struct_best]["cv_spearman_hardness"] <= 0.02:
        best_key = struct_best
        best_set, best_lam = best_key.split("@")
    names = feature_sets[best_set]
    lam = float(best_lam)
    X = np.array([capped(f, names) for f in feats])
    raw, intercept = nn_ridge(X, hardness, lam)

    # Integer weights: scale so the weight of one returned column is 2 points
    # when return_arity is selected; otherwise the largest weight becomes 4.
    if "return_arity" in names and raw[names.index("return_arity")] > 0:
        scale = 2.0 / raw[names.index("return_arity")]
    else:
        scale = 4.0 / max(raw.max(), 1e-9)
    weights = integer_weights(raw, names, scale)
    caps = {name: float(CAPS[name]) for name in weights if name in CAPS}
    provisional = DifficultyModel(weights=weights, caps=caps, thresholds=(0.0, 0.0))
    scores = score_rows(feats, provisional)

    # Integer-weight model, cross-validated: refit weights per fold, round, score held-out fold.
    oof_int = np.zeros(len(test))
    for fold in range(5):
        train = np.array([f != fold for f in folds])
        fold_raw, _ = nn_ridge(X[train], hardness[train], lam)
        fs = (2.0 / fold_raw[names.index("return_arity")]) if ("return_arity" in names and fold_raw[names.index("return_arity")] > 0) else scale
        fold_model = DifficultyModel(weights=integer_weights(fold_raw, names, fs), caps=caps)
        oof_int[~train] = score_rows([feats[i] for i in np.where(~train)[0]], fold_model)

    thresholds = pick_thresholds(scores)
    model = DifficultyModel(weights=weights, caps=caps, thresholds=thresholds)
    tiers = [model.tier(s) for s in scores]

    def tier_table(rate_map: dict[str, float]) -> dict[str, dict[str, float]]:
        table = {}
        for tier in TIERS:
            idx = [i for i, t in enumerate(tiers) if t == tier]
            if not idx:
                table[tier] = {"n": 0}
                continue
            mean, lo, hi = cluster_bootstrap_mean([rate_map[test[i]["id"]] for i in idx], [groups[i] for i in idx])
            table[tier] = {"n": len(idx), "mean_solve_rate": round(mean, 3), "ci95": [round(lo, 3), round(hi, 3)]}
        return table

    tier_solve = {"zero_shot_standard": tier_table(rates)}
    for item in args.check_glob:
        name, pattern = item.split("=", 1)
        paths = sorted(glob.glob(pattern))
        if paths:
            other, _ = solve_rates(paths, ids)
            tier_solve[name] = tier_table(other)

    # Out-of-fold tiers: weights AND thresholds fit on the other four folds.
    oof_tiers = [""] * len(test)
    for fold in range(5):
        train_idx = [i for i, f in enumerate(folds) if f != fold]
        test_idx = [i for i, f in enumerate(folds) if f == fold]
        fold_raw, _ = nn_ridge(X[train_idx], hardness[train_idx], lam)
        fs = (2.0 / fold_raw[names.index("return_arity")]) if ("return_arity" in names and fold_raw[names.index("return_arity")] > 0) else scale
        fold_model = DifficultyModel(weights=integer_weights(fold_raw, names, fs), caps=caps)
        fold_thresholds = pick_thresholds(score_rows([feats[i] for i in train_idx], fold_model))
        fold_model = DifficultyModel(weights=fold_model.weights, caps=caps, thresholds=fold_thresholds)
        for i in test_idx:
            oof_tiers[i] = fold_model.tier(fold_model.score(feats[i]))
    oof_table = {}
    for tier in TIERS:
        idx = [i for i, t in enumerate(oof_tiers) if t == tier]
        if idx:
            mean, lo, hi = cluster_bootstrap_mean([rates[test[i]["id"]] for i in idx], [groups[i] for i in idx])
            oof_table[tier] = {"n": len(idx), "mean_solve_rate": round(mean, 3), "ci95": [round(lo, 3), round(hi, 3)]}
    tier_solve["zero_shot_standard_out_of_fold"] = oof_table

    per_model: dict[str, dict[str, float]] = {}
    for path in sorted(glob.glob(args.eval_glob)):
        rows = {r["id"]: bool(r.get("projected_execution_accuracy")) for r in load_jsonl(path) if r["id"] in ids}
        model_name = Path(path).parent.name.replace("naacl_v2_heldout_downstream_", "")
        per_model[model_name] = {
            tier: round(sum(rows[test[i]["id"]] for i, t in enumerate(tiers) if t == tier) / max(1, tiers.count(tier)), 3)
            for tier in TIERS
        }
    monotone = sum(1 for v in per_model.values() if v["easy"] >= v["medium"] >= v["hard"])

    solve_counts = Counter()
    for tier, row in zip(tiers, test):
        k = round(rates[row["id"]] * n_models)
        bucket = "0" if k == 0 else "1-3" if k <= 3 else "4-7" if k <= 7 else "8-11"
        solve_counts[f"{tier}:{bucket}"] += 1

    confusion = Counter(f"{row.get('difficulty')}->{tier}" for row, tier in zip(test, tiers))
    per_category = defaultdict(Counter)
    for row, tier in zip(test, tiers):
        per_category[row["category"]][tier] += 1

    # Feasibility on the full v2 release.
    all_rows = load_jsonl(args.all)
    feasible: dict[str, Counter] = defaultdict(Counter)
    feasible_graph: dict[str, Counter] = defaultdict(Counter)
    for row in all_rows:
        tier = model.tier(model.score(difficulty_features(row["cypher"])))
        feasible[row["category"]][tier] += 1
        feasible_graph[f"{row['graph_profile']}:{row['category']}"][tier] += 1
    overall_all = Counter()
    for counter in feasible.values():
        overall_all.update(counter)

    quotas = recommend_quotas(feasible)
    config = {
        **model.to_dict(),
        "quotas": quotas,
        "metadata": {
            "description": "Structural difficulty score: sum(weight * min(feature, cap)); easy < t1 <= medium < t2 <= hard.",
            "calibration_target": f"fraction of {n_models} models solving each v2 held-out test item (zero-shot standard prompt, projected EX)",
            "calibration_items": len(test),
            "feature_set": best_set,
            "ridge_lambda": lam,
            "cv_spearman_hardness_continuous": round(cv_results[best_key]["cv_spearman_hardness"], 3),
            "cv_spearman_hardness_integer": round(spearman(oof_int, hardness), 3),
            "in_sample_spearman_hardness_integer": round(spearman(scores, hardness), 3),
            "target_tier_shares": {"easy": 0.35, "medium": 0.35, "hard": 0.30},
            "source": "scripts/calibrate_difficulty.py",
        },
    }
    Path(args.output).write_text(json.dumps(config, indent=2) + "\n")

    report = {
        "n_test": len(test),
        "n_models": n_models,
        "n_signature_groups": len(set(groups)),
        "cv": {k: round(v["cv_spearman_hardness"], 3) for k, v in cv_results.items()},
        "selected": best_key,
        "raw_coefficients_per_unit_hardness": {n: round(float(c), 4) for n, c in zip(names, raw)},
        "intercept": round(intercept, 4),
        "weights": weights,
        "caps": caps,
        "thresholds": list(thresholds),
        "test_tier_counts": dict(Counter(tiers)),
        "tier_solve_rates": tier_solve,
        "tier_by_solve_bucket": dict(sorted(solve_counts.items())),
        "per_model_tier_accuracy": per_model,
        "models_monotone_easy_ge_medium_ge_hard": f"{monotone}/{len(per_model)}",
        "single_feature_spearman_hardness": {
            "tokens": round(spearman(np.array([f["tokens"] for f in feats]), hardness), 3),
            "return_arity": round(spearman(np.array([f["return_arity"] for f in feats]), hardness), 3),
            "hops": round(spearman(np.array([f["hops"] for f in feats]), hardness), 3),
            "old_heuristic": round(spearman(np.array([{"easy": 0, "medium": 1, "hard": 2}.get(r.get("difficulty"), 0) for r in test], dtype=float), hardness), 3),
        },
        "old_heuristic_to_new": dict(sorted(confusion.items())),
        "test_per_category": {k: dict(v) for k, v in sorted(per_category.items())},
        "all_release_overall": dict(overall_all),
        "all_release_per_category": {k: dict(v) for k, v in sorted(feasible.items())},
        "all_release_per_graph_category": {k: dict(v) for k, v in sorted(feasible_graph.items())},
        "quotas": quotas,
        "thin_cells_at_target": thin_cells(feasible_graph, quotas, args.target_per_cell),
        "metadata": config["metadata"],
    }
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("selected", "weights", "thresholds", "test_tier_counts", "tier_solve_rates", "models_monotone_easy_ge_medium_ge_hard", "single_feature_spearman_hardness", "all_release_overall")}, indent=1))
    print("cv:", report["cv"])
    print("integer cv rho:", config["metadata"]["cv_spearman_hardness_integer"])


if __name__ == "__main__":
    main()
