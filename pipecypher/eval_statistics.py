"""Cluster-aware statistics for downstream Text2Cypher evaluation.

PIPE-Cypher benchmarks are template-concentrated: many held-out items share a
canonical query signature (the 296-item reviewfix test split has 26), so a
row-level bootstrap treats near-duplicate items as independent evidence and
reports intervals that are far too narrow. Every interval here is therefore
computed twice, once resampling rows and once resampling signature clusters,
and the paired, ranking, and self-preference analyses resample clusters.

The module is pure stdlib + numpy, needs no graph or GPU access, and is
deterministic for a fixed seed. It refuses to summarize inputs that would
make a comparison dishonest: duplicate or mismatched item ids, benchmark/gold
Cypher disagreements, runs dominated by request failures, or metrics that are
present on only some rows.
"""

from __future__ import annotations

import itertools
import math
from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

from .diversity_metrics import canonical_query_signature, template_family_signature
from .downstream_model_transfer import MAX_PREDICTION_FAILURE_RATE, _escape_latex
from .evaluation_uncertainty import _derived_seed
from .io import read_jsonl

DEFAULT_ITERATIONS = 2000
DEFAULT_SEED = 13
DEFAULT_CONFIDENCE_LEVEL = 0.95
DEFAULT_PERMUTATION_ITERATIONS = 10000
CLUSTER_MODES = ("signature", "template_family", "none")
CLUSTER_CI_METRICS = (
    "execution_accuracy",
    "projected_execution_accuracy",
    "answer_f1",
    "execution_success",
    "parse_valid",
    "schema_valid",
)
PAIRED_METRICS = ("execution_accuracy", "projected_execution_accuracy", "answer_f1")
MODEL_SUMMARY_METRICS = (
    "execution_accuracy",
    "projected_execution_accuracy",
    "answer_f1",
    "execution_success",
    "parse_valid",
    "schema_valid",
    "governance_valid",
)
DEFAULT_THRESHOLDS = (0.1, 0.25, 0.5)
THRESHOLD_METRICS = ("execution_accuracy", "projected_execution_accuracy")
METRIC_LABELS = {
    "execution_accuracy": "Strict EX",
    "projected_execution_accuracy": "Projected EX",
    "governed_execution_accuracy": "Governed EX",
    "answer_f1": "Answer F1",
    "projected_answer_f1": "Projected F1",
    "execution_success": "Execution success",
    "parse_valid": "Parse valid",
    "schema_valid": "Schema valid",
    "governance_valid": "Governance valid",
    "read_only": "Read-only",
}
# Below this many clusters, percentile cluster-bootstrap intervals are known
# to under-cover; reports carry an explicit warning.
FEW_CLUSTERS = 30
EXACT_SIGN_FLIP_MAX_CLUSTERS = 16
EXACT_PERMUTATION_MAX_MODELS = 8
_TIE_TOLERANCE = 1e-12
_BOOTSTRAP_CHUNK = 256


class EvaluationInputError(ValueError):
    """Evaluation inputs cannot be summarized or compared honestly."""


class MetricUnavailableError(EvaluationInputError):
    """A requested metric is absent from every row (e.g. legacy files)."""


@dataclass
class EvaluationRun:
    label: str
    rows: list[dict[str, Any]]
    path: str = ""


@dataclass(frozen=True)
class ClusterLayout:
    """Row-to-cluster assignment, optionally nested within strata."""

    keys: tuple[tuple[str, str], ...]
    index: np.ndarray
    sizes: np.ndarray
    strata: tuple[np.ndarray, ...]
    stratum_names: tuple[str, ...]

    @property
    def n_clusters(self) -> int:
        return len(self.keys)

    @property
    def n_rows(self) -> int:
        return int(self.index.shape[0])


# ---------------------------------------------------------------------------
# Loading and validation
# ---------------------------------------------------------------------------


def parse_labeled_path(spec: str) -> tuple[str | None, str]:
    """Split ``LABEL=PATH``; a bare existing path has no label."""

    if "=" in spec and not Path(spec).exists():
        label, path = spec.split("=", 1)
        if label.strip() and path.strip():
            return label.strip(), path.strip()
    return None, spec


def load_evaluation_run(spec: str, *, label: str | None = None) -> EvaluationRun:
    parsed_label, path = parse_labeled_path(spec)
    rows = read_jsonl(path)
    if not rows:
        raise EvaluationInputError(f"{path}: evaluation file has no rows")
    return EvaluationRun(label or parsed_label or _infer_label(rows, path), rows, str(path))


def load_benchmark_index(paths: Sequence[str | Path]) -> dict[str, dict[str, Any]]:
    """Index benchmark rows by id; a package directory resolves to all.jsonl."""

    index: dict[str, dict[str, Any]] = {}
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            path = path / "all.jsonl"
        if not path.exists():
            raise EvaluationInputError(f"benchmark file not found: {path}")
        for row in read_jsonl(path):
            row_id = str(row.get("id", ""))
            if not row_id:
                raise EvaluationInputError(f"{path}: benchmark row without id")
            previous = index.get(row_id)
            if previous is not None and _benchmark_gold(previous) != _benchmark_gold(row):
                raise EvaluationInputError(
                    f"benchmark id {row_id} has conflicting gold Cypher across {list(paths)}"
                )
            index[row_id] = row
    return index


def prediction_failure_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Request-failure rate; legacy rows derive it from prediction_error."""

    n = len(rows)
    failures = sum(1 for row in rows if _row_prediction_failed(row))
    if any("prediction_failed" in row for row in rows):
        source = "prediction_failed"
    elif any("prediction_error" in row or "error" in row for row in rows):
        source = "prediction_error_with_empty_cypher"
    else:
        source = "unavailable"
    return {
        "n": n,
        "prediction_failures": failures,
        "prediction_failure_rate": failures / n if n else 0.0,
        "source": source,
    }


def check_run_validity(
    run: EvaluationRun, *, max_prediction_failure_rate: float = MAX_PREDICTION_FAILURE_RATE
) -> dict[str, Any]:
    """Raise unless ids are unique and request failures are within tolerance."""

    ids = [row.get("id") for row in run.rows]
    if any(row_id in (None, "") for row_id in ids):
        raise EvaluationInputError(f"{run.label}: evaluation rows without an id")
    duplicates = [row_id for row_id, count in Counter(map(str, ids)).items() if count > 1]
    if duplicates:
        raise EvaluationInputError(
            f"{run.label}: {len(duplicates)} duplicated item ids (e.g. {duplicates[:3]})"
        )
    summary = prediction_failure_summary(run.rows)
    summary["max_prediction_failure_rate"] = max_prediction_failure_rate
    if summary["prediction_failure_rate"] > max_prediction_failure_rate:
        raise EvaluationInputError(
            "{label}: prediction failure rate {rate:.3f} exceeds {limit:.3f}; request "
            "failures are infrastructure errors, not model accuracy".format(
                label=run.label,
                rate=summary["prediction_failure_rate"],
                limit=max_prediction_failure_rate,
            )
        )
    return summary


def cluster_keys_for_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    benchmark_index: Mapping[str, Mapping[str, Any]] | None = None,
    cluster_by: str = "signature",
) -> tuple[list[str], dict[str, int]]:
    """Cluster key per row plus a count of which source produced each key.

    ``signature`` clusters by the canonical signature of the gold Cypher
    (benchmark row first, evaluation ``gold_cypher`` second), falling back to
    the template field and finally to a singleton cluster. ``template_family``
    uses the coarser :func:`template_family_signature`. ``none`` is the
    row-level bootstrap.
    """

    if cluster_by not in CLUSTER_MODES:
        raise EvaluationInputError(f"cluster_by must be one of {CLUSTER_MODES}")
    keys: list[str] = []
    sources: Counter[str] = Counter()
    for row in rows:
        row_id = str(row.get("id"))
        bench = None
        if benchmark_index is not None:
            bench = benchmark_index.get(row_id)
            if bench is None:
                raise EvaluationInputError(f"evaluation id {row_id} not found in benchmark")
            _check_gold_consistency(row, bench)
        key, source = _cluster_key(row_id, row, bench, cluster_by)
        keys.append(key)
        sources[source] += 1
    return keys, dict(sorted(sources.items()))


def metric_available(rows: Sequence[Mapping[str, Any]], metric: str) -> bool:
    return any(row.get(metric) is not None for row in rows)


def metric_column(rows: Sequence[Mapping[str, Any]], metric: str) -> tuple[np.ndarray, bool]:
    """Return ``(values, is_binary)``; never imputes missing values."""

    present = [row.get(metric) is not None for row in rows]
    if not any(present):
        raise MetricUnavailableError(f"metric {metric!r} is absent from every row")
    if not all(present):
        raise EvaluationInputError(
            f"metric {metric!r} missing on {present.count(False)} of {len(rows)} rows; "
            "refusing to impute"
        )
    values: list[float] = []
    is_binary = True
    for row in rows:
        value = row[metric]
        if isinstance(value, bool):
            values.append(1.0 if value else 0.0)
        elif isinstance(value, (int, float)) and math.isfinite(float(value)):
            values.append(float(value))
            is_binary = False
        else:
            raise EvaluationInputError(f"metric {metric!r} has non-numeric value {value!r}")
    return np.asarray(values, dtype=float), is_binary


# ---------------------------------------------------------------------------
# Bootstrap engine
# ---------------------------------------------------------------------------


def build_cluster_layout(
    cluster_keys: Sequence[str], strata: Sequence[str] | None = None
) -> ClusterLayout:
    """Nest clusters inside strata so stratified resampling stays well defined."""

    n = len(cluster_keys)
    if n == 0:
        raise EvaluationInputError("cannot bootstrap an empty row set")
    stratum_values = [""] * n if strata is None else [str(value) for value in strata]
    if len(stratum_values) != n:
        raise EvaluationInputError("strata and cluster keys must have equal length")
    composite = [(stratum, str(key)) for stratum, key in zip(stratum_values, cluster_keys)]
    unique = tuple(sorted(set(composite)))
    position = {key: i for i, key in enumerate(unique)}
    index = np.fromiter((position[key] for key in composite), dtype=np.int64, count=n)
    sizes = np.bincount(index, minlength=len(unique)).astype(float)
    names = tuple(sorted({stratum for stratum, _ in unique}))
    members = tuple(
        np.array([i for i, (stratum, _) in enumerate(unique) if stratum == name], dtype=np.int64)
        for name in names
    )
    return ClusterLayout(unique, index, sizes, members, names)


def row_layout(n: int, strata: Sequence[str] | None = None) -> ClusterLayout:
    return build_cluster_layout([f"row:{i:09d}" for i in range(n)], strata)


def cluster_bootstrap_interval(
    values: Sequence[float] | np.ndarray,
    cluster_keys: Sequence[str],
    *,
    strata: Sequence[str] | None = None,
    iterations: int = DEFAULT_ITERATIONS,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Row-level and cluster-level percentile intervals for a row mean.

    Clusters are resampled with replacement (within strata when given) and the
    replicate estimate is the pooled row mean of the drawn clusters. The
    ``signature_macro`` entry is the equal-weight mean of per-cluster means,
    i.e. accuracy per query template rather than per item.
    """

    _check_bootstrap_args(iterations, confidence_level)
    array = np.asarray(values, dtype=float)
    if array.ndim != 1 or array.shape[0] != len(cluster_keys):
        raise EvaluationInputError("values and cluster keys must align one-to-one")
    clustered = build_cluster_layout(cluster_keys, strata)
    rows = row_layout(len(array), strata)
    point = float(array.mean())
    cluster_micro, cluster_macro = _replicate_means(
        array[None, :], clustered, iterations, np.random.default_rng(seed)
    )
    row_micro, _ = _replicate_means(array[None, :], rows, iterations, np.random.default_rng(seed))
    cluster_means = np.bincount(clustered.index, weights=array) / clustered.sizes
    cluster = _interval(point, cluster_micro[:, 0], confidence_level)
    row = _interval(point, row_micro[:, 0], confidence_level)
    design_effect = (
        (cluster["standard_error"] / row["standard_error"]) ** 2
        if row["standard_error"] > 0
        else None
    )
    return {
        "n": int(array.shape[0]),
        "n_clusters": clustered.n_clusters,
        "n_strata": len(clustered.stratum_names),
        "largest_cluster_share": float(clustered.sizes.max() / array.shape[0]),
        "singleton_clusters": int(np.sum(clustered.sizes == 1)),
        "point": point,
        "row": row,
        "cluster": cluster,
        "signature_macro": _interval(
            float(cluster_means.mean()), cluster_macro[:, 0], confidence_level
        ),
        "design_effect": design_effect,
        "effective_n": (array.shape[0] / design_effect) if design_effect else None,
    }


def cluster_sign_flip_test(
    differences: Sequence[float] | np.ndarray,
    cluster_keys: Sequence[str],
    *,
    iterations: int = DEFAULT_PERMUTATION_ITERATIONS,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Two-sided paired randomization test that flips whole clusters.

    Under H0 the two conditions are exchangeable for every item, so flipping
    the sign of a cluster's summed paired difference leaves its distribution
    unchanged even when items inside a cluster are dependent. Exact for at most
    ``EXACT_SIGN_FLIP_MAX_CLUSTERS`` informative clusters, Monte Carlo above.
    """

    array = np.asarray(differences, dtype=float)
    layout = build_cluster_layout(cluster_keys)
    sums = np.bincount(layout.index, weights=array, minlength=layout.n_clusters)
    informative = sums[np.abs(sums) > _TIE_TOLERANCE]
    k = int(informative.shape[0])
    observed = abs(float(array.sum()))
    if k == 0:
        return {"p_value": 1.0, "method": "degenerate", "informative_clusters": 0}
    threshold = observed - 1e-9 * max(1.0, observed)
    if k <= EXACT_SIGN_FLIP_MAX_CLUSTERS:
        signs = np.array(list(itertools.product((-1.0, 1.0), repeat=k)))
        stats = np.abs(signs @ informative)
        p_value = float(np.mean(stats >= threshold))
        method, draws = "exact", int(signs.shape[0])
    else:
        rng = np.random.default_rng(seed)
        signs = rng.choice(np.array([-1.0, 1.0]), size=(iterations, k))
        stats = np.abs(signs @ informative)
        p_value = float((1 + np.sum(stats >= threshold)) / (1 + iterations))
        method, draws = "monte_carlo", iterations
    return {
        "p_value": p_value,
        "method": method,
        "informative_clusters": k,
        "draws": draws,
        "minimum_attainable_p": 2.0 / (2**k) if method == "exact" else 1.0 / (1 + iterations),
    }


def mcnemar_exact(b: int, c: int) -> float:
    """Exact two-sided McNemar p-value from discordant counts ``b`` and ``c``."""

    if b < 0 or c < 0:
        raise ValueError("discordant counts must be non-negative")
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1))
    return float(min(Fraction(1), Fraction(2 * tail, 2**n)))


# ---------------------------------------------------------------------------
# Rank statistics
# ---------------------------------------------------------------------------


def kendall_tau_b(x: Sequence[float], y: Sequence[float]) -> float:
    """Kendall tau-b; NaN when either ranking is entirely tied."""

    xs, ys = _as_pair(x, y)
    return float(_tau_b_rows(xs[None, :], ys[None, :])[0])


def spearman_rho(x: Sequence[float], y: Sequence[float]) -> float:
    """Spearman rho with average ranks for ties; NaN when undefined."""

    xs, ys = _as_pair(x, y)
    return float(_pearson_rows(_average_ranks(xs)[None, :], _average_ranks(ys)[None, :])[0])


def pairwise_order_agreement(
    x: Sequence[float], y: Sequence[float], labels: Sequence[str] | None = None
) -> dict[str, Any]:
    xs, ys = _as_pair(x, y)
    names = list(labels) if labels is not None else [str(i) for i in range(len(xs))]
    counts = Counter()
    discordant_pairs: list[list[str]] = []
    for i, j in itertools.combinations(range(len(xs)), 2):
        sx = _sign(xs[i] - xs[j])
        sy = _sign(ys[i] - ys[j])
        if sx == 0 and sy == 0:
            counts["tied_both"] += 1
        elif sx == 0:
            counts["tied_a_only"] += 1
        elif sy == 0:
            counts["tied_b_only"] += 1
        elif sx == sy:
            counts["concordant"] += 1
        else:
            counts["discordant"] += 1
            discordant_pairs.append([names[i], names[j]])
    resolved = counts["concordant"] + counts["discordant"]
    return {
        "pairs": len(xs) * (len(xs) - 1) // 2,
        "concordant": counts["concordant"],
        "discordant": counts["discordant"],
        "tied_a_only": counts["tied_a_only"],
        "tied_b_only": counts["tied_b_only"],
        "tied_both": counts["tied_both"],
        "agreement_rate": counts["concordant"] / resolved if resolved else None,
        "discordant_pairs": discordant_pairs,
    }


def rank_permutation_test(
    x: Sequence[float],
    y: Sequence[float],
    *,
    iterations: int = DEFAULT_PERMUTATION_ITERATIONS,
    seed: int = DEFAULT_SEED,
) -> dict[str, Any]:
    """Two-sided permutation p-values for tau-b and rho (exact for small m)."""

    xs, ys = _as_pair(x, y)
    m = len(xs)
    if m <= EXACT_PERMUTATION_MAX_MODELS:
        perms = np.array(list(itertools.permutations(range(m))), dtype=np.int64)
        method = "exact"
    else:
        rng = np.random.default_rng(seed)
        perms = np.array([rng.permutation(m) for _ in range(iterations)], dtype=np.int64)
        method = "monte_carlo"
    permuted = ys[perms]
    taus = _tau_b_rows(np.broadcast_to(xs, permuted.shape), permuted)
    ranks_x = _average_ranks(xs)
    rhos = _pearson_rows(np.broadcast_to(ranks_x, permuted.shape), _average_ranks(ys)[perms])
    result: dict[str, Any] = {"method": method, "draws": int(perms.shape[0])}
    for name, observed, null in (
        ("tau_b", kendall_tau_b(xs, ys), taus),
        ("spearman", spearman_rho(xs, ys), rhos),
    ):
        if not math.isfinite(observed):
            result[f"{name}_p_value"] = None
            continue
        extreme = np.sum(np.abs(np.nan_to_num(null, nan=0.0)) >= abs(observed) - 1e-9)
        if method == "exact":
            result[f"{name}_p_value"] = float(extreme / null.shape[0])
        else:
            result[f"{name}_p_value"] = float((1 + extreme) / (1 + iterations))
    return result


# ---------------------------------------------------------------------------
# Analyses
# ---------------------------------------------------------------------------


def analyze_cluster_ci(
    run: EvaluationRun,
    *,
    metrics: Sequence[str] = CLUSTER_CI_METRICS,
    require_metrics: bool = False,
    benchmark_index: Mapping[str, Mapping[str, Any]] | None = None,
    cluster_by: str = "signature",
    stratify_by: str | None = None,
    group_by: Sequence[str] = (),
    iterations: int = DEFAULT_ITERATIONS,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
    seed: int = DEFAULT_SEED,
    max_prediction_failure_rate: float = MAX_PREDICTION_FAILURE_RATE,
) -> dict[str, Any]:
    validity = check_run_validity(run, max_prediction_failure_rate=max_prediction_failure_rate)
    rows = run.rows
    keys, sources = cluster_keys_for_rows(
        rows, benchmark_index=benchmark_index, cluster_by=cluster_by
    )
    strata = _strata(rows, stratify_by)
    available, unavailable = _split_available(rows, metrics, require_metrics)
    columns = {metric: metric_column(rows, metric)[0] for metric in available}
    results = {
        metric: cluster_bootstrap_interval(
            columns[metric],
            keys,
            strata=strata,
            iterations=iterations,
            confidence_level=confidence_level,
            seed=_derived_seed(seed, "cluster-ci", metric),
        )
        for metric in available
    }
    groups: dict[str, dict[str, dict[str, Any]]] = {}
    for group_key in group_by:
        groups[group_key] = {}
        for name, idx in sorted(_group_indices(rows, group_key).items()):
            sub_keys = [keys[i] for i in idx]
            sub_strata = [strata[i] for i in idx] if strata is not None else None
            groups[group_key][name] = {
                metric: cluster_bootstrap_interval(
                    columns[metric][idx],
                    sub_keys,
                    strata=sub_strata,
                    iterations=iterations,
                    confidence_level=confidence_level,
                    seed=_derived_seed(seed, "cluster-ci", group_key, name, metric),
                )
                for metric in available
            }
    layout = build_cluster_layout(keys, strata)
    return {
        "analysis": "cluster_ci",
        "label": run.label,
        "path": run.path,
        "n": len(rows),
        "validity": validity,
        **_bootstrap_settings(iterations, confidence_level, seed, cluster_by, stratify_by),
        "cluster_key_sources": sources,
        "n_clusters": layout.n_clusters,
        "cluster_sizes": sorted((int(size) for size in layout.sizes), reverse=True),
        "metrics": results,
        "unavailable_metrics": unavailable,
        "groups": groups,
        "warnings": _cluster_warnings(layout, sources, validity),
    }


def analyze_paired(
    run_a: EvaluationRun,
    run_b: EvaluationRun,
    *,
    metrics: Sequence[str] = PAIRED_METRICS,
    require_metrics: bool = False,
    benchmark_index: Mapping[str, Mapping[str, Any]] | None = None,
    cluster_by: str = "signature",
    stratify_by: str | None = None,
    iterations: int = DEFAULT_ITERATIONS,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
    seed: int = DEFAULT_SEED,
    permutation_iterations: int = DEFAULT_PERMUTATION_ITERATIONS,
    max_prediction_failure_rate: float = MAX_PREDICTION_FAILURE_RATE,
) -> dict[str, Any]:
    """Paired comparison of B against A on identical item ids (delta = B - A)."""

    validity = {
        "a": check_run_validity(run_a, max_prediction_failure_rate=max_prediction_failure_rate),
        "b": check_run_validity(run_b, max_prediction_failure_rate=max_prediction_failure_rate),
    }
    rows_a = run_a.rows
    rows_b = _align_to(rows_a, run_b.rows, run_a.label, run_b.label)
    for row_a, row_b in zip(rows_a, rows_b):
        gold_a, gold_b = row_a.get("gold_cypher"), row_b.get("gold_cypher")
        if gold_a and gold_b and str(gold_a).strip() != str(gold_b).strip():
            raise EvaluationInputError(
                f"item {row_a['id']}: gold Cypher differs between {run_a.label} and "
                f"{run_b.label}; the runs were scored on different splits/exports"
            )
    keys, sources = cluster_keys_for_rows(
        rows_a, benchmark_index=benchmark_index, cluster_by=cluster_by
    )
    strata = _strata(rows_a, stratify_by)
    results: dict[str, Any] = {}
    unavailable: list[str] = []
    for metric in metrics:
        if not (metric_available(rows_a, metric) and metric_available(rows_b, metric)):
            if require_metrics:
                raise MetricUnavailableError(f"metric {metric!r} unavailable in one or both runs")
            unavailable.append(metric)
            continue
        values_a, binary_a = metric_column(rows_a, metric)
        values_b, binary_b = metric_column(rows_b, metric)
        differences = values_b - values_a
        interval = cluster_bootstrap_interval(
            differences,
            keys,
            strata=strata,
            iterations=iterations,
            confidence_level=confidence_level,
            seed=_derived_seed(seed, "paired", metric),
        )
        entry: dict[str, Any] = {
            "n": int(values_a.shape[0]),
            "mean_a": float(values_a.mean()),
            "mean_b": float(values_b.mean()),
            "difference": interval["point"],
            "row_ci": interval["row"],
            "cluster_ci": interval["cluster"],
            "n_clusters": interval["n_clusters"],
            "design_effect": interval["design_effect"],
            "cluster_sign_flip": cluster_sign_flip_test(
                differences,
                keys,
                iterations=permutation_iterations,
                seed=_derived_seed(seed, "sign-flip", metric),
            ),
        }
        if binary_a and binary_b:
            a_only = int(np.sum((values_a == 1) & (values_b == 0)))
            b_only = int(np.sum((values_a == 0) & (values_b == 1)))
            entry["mcnemar"] = {
                "a_correct_b_wrong": a_only,
                "a_wrong_b_correct": b_only,
                "both_correct": int(np.sum((values_a == 1) & (values_b == 1))),
                "both_wrong": int(np.sum((values_a == 0) & (values_b == 0))),
                "p_value": mcnemar_exact(a_only, b_only),
                "note": "exact binomial on discordant items; assumes independent items",
            }
        results[metric] = entry
    layout = build_cluster_layout(keys, strata)
    return {
        "analysis": "paired",
        "label_a": run_a.label,
        "label_b": run_b.label,
        "path_a": run_a.path,
        "path_b": run_b.path,
        "difference_definition": "b_minus_a",
        "n": len(rows_a),
        "validity": validity,
        **_bootstrap_settings(iterations, confidence_level, seed, cluster_by, stratify_by),
        "permutation_iterations": permutation_iterations,
        "cluster_key_sources": sources,
        "n_clusters": layout.n_clusters,
        "metrics": results,
        "unavailable_metrics": unavailable,
        "warnings": _cluster_warnings(layout, sources, validity["a"], validity["b"]),
    }


def analyze_models(
    runs: Sequence[EvaluationRun],
    *,
    metrics: Sequence[str] = MODEL_SUMMARY_METRICS,
    thresholds: Sequence[float] = DEFAULT_THRESHOLDS,
    threshold_metrics: Sequence[str] = THRESHOLD_METRICS,
    benchmark_index: Mapping[str, Mapping[str, Any]] | None = None,
    cluster_by: str = "signature",
    stratify_by: str | None = None,
    iterations: int = DEFAULT_ITERATIONS,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
    seed: int = DEFAULT_SEED,
    max_prediction_failure_rate: float = MAX_PREDICTION_FAILURE_RATE,
    exclude_invalid: bool = False,
    require_same_ids: bool = True,
) -> dict[str, Any]:
    """Per-model clustered intervals plus median/IQR across models."""

    _unique_labels(runs)
    included: list[tuple[EvaluationRun, dict[str, Any]]] = []
    excluded: list[dict[str, Any]] = []
    for run in runs:
        try:
            included.append(
                (
                    run,
                    check_run_validity(
                        run, max_prediction_failure_rate=max_prediction_failure_rate
                    ),
                )
            )
        except EvaluationInputError as exc:
            if not exclude_invalid:
                raise
            excluded.append({"label": run.label, "path": run.path, "reason": str(exc)})
    if not included:
        raise EvaluationInputError("no valid evaluation runs to summarize")
    if require_same_ids:
        _require_same_id_sets([run for run, _ in included])
    models: list[dict[str, Any]] = []
    all_sources: Counter[str] = Counter()
    layouts: list[ClusterLayout] = []
    for run, validity in included:
        keys, sources = cluster_keys_for_rows(
            run.rows, benchmark_index=benchmark_index, cluster_by=cluster_by
        )
        all_sources.update(sources)
        strata = _strata(run.rows, stratify_by)
        layouts.append(build_cluster_layout(keys, strata))
        entry: dict[str, Any] = {
            "label": run.label,
            "path": run.path,
            "n": len(run.rows),
            "validity": validity,
            "metrics": {},
        }
        for metric in metrics:
            if not metric_available(run.rows, metric):
                entry["metrics"][metric] = None
                continue
            interval = cluster_bootstrap_interval(
                metric_column(run.rows, metric)[0],
                keys,
                strata=strata,
                iterations=iterations,
                confidence_level=confidence_level,
                seed=_derived_seed(seed, "models", metric),
            )
            entry["metrics"][metric] = {
                "point": interval["point"],
                "cluster_ci": interval["cluster"],
                "row_ci": interval["row"],
                "n_clusters": interval["n_clusters"],
                "design_effect": interval["design_effect"],
            }
        models.append(entry)
    aggregate = {}
    for metric in metrics:
        points = [m["metrics"][metric]["point"] for m in models if m["metrics"].get(metric)]
        aggregate[metric] = _distribution_summary(points) if points else None
    threshold_counts: dict[str, dict[str, Any]] = {}
    for metric in threshold_metrics:
        scored = [m["metrics"][metric] for m in models if m["metrics"].get(metric)]
        if not scored:
            continue
        threshold_counts[metric] = {
            _threshold_key(t): {
                "models_scored": len(scored),
                "point_above": sum(1 for s in scored if s["point"] > t),
                "cluster_ci_lower_above": sum(1 for s in scored if s["cluster_ci"]["lower"] > t),
            }
            for t in thresholds
        }
    warnings = _cluster_warnings(layouts[0], dict(all_sources), *(v for _, v in included))
    if excluded:
        warnings.append(f"{len(excluded)} invalid run(s) excluded from every aggregate")
    return {
        "analysis": "models",
        "n_models": len(models),
        **_bootstrap_settings(iterations, confidence_level, seed, cluster_by, stratify_by),
        "metrics_requested": list(metrics),
        "thresholds": list(thresholds),
        "cluster_key_sources": dict(sorted(all_sources.items())),
        "n_clusters": layouts[0].n_clusters,
        "models": models,
        "excluded_runs": excluded,
        "across_models": aggregate,
        "threshold_counts": threshold_counts,
        "warnings": warnings,
    }


def analyze_rank_agreement(
    runs_a: Sequence[EvaluationRun],
    runs_b: Sequence[EvaluationRun],
    *,
    name_a: str = "A",
    name_b: str = "B",
    metrics: Sequence[str] = ("execution_accuracy",),
    benchmark_index_a: Mapping[str, Mapping[str, Any]] | None = None,
    benchmark_index_b: Mapping[str, Mapping[str, Any]] | None = None,
    cluster_by: str = "signature",
    stratify_by: str | None = None,
    iterations: int = DEFAULT_ITERATIONS,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
    seed: int = DEFAULT_SEED,
    permutation_iterations: int = DEFAULT_PERMUTATION_ITERATIONS,
    max_prediction_failure_rate: float = MAX_PREDICTION_FAILURE_RATE,
) -> dict[str, Any]:
    """Do two benchmarks rank the same models the same way?

    Items are resampled independently within each benchmark (clustered by
    signature where available) with the same draw applied to every model, so
    the interval reflects item-sampling noise in both benchmarks. The
    permutation p-value treats model scores as fixed and tests association
    only. Overlapping items between A and B are treated as independent, which
    makes the interval conservative rather than optimistic.
    """

    labels = _matched_labels(runs_a, runs_b, name_a, name_b)
    if len(labels) < 3:
        raise EvaluationInputError("rank agreement needs at least three models")
    side_a = _model_matrix_side(
        runs_a, labels, benchmark_index_a, cluster_by, stratify_by, max_prediction_failure_rate
    )
    side_b = _model_matrix_side(
        runs_b, labels, benchmark_index_b, cluster_by, stratify_by, max_prediction_failure_rate
    )
    results: dict[str, Any] = {}
    for metric in metrics:
        matrix_a = _metric_matrix(side_a["rows"], metric)
        matrix_b = _metric_matrix(side_b["rows"], metric)
        scores_a = matrix_a.mean(axis=1)
        scores_b = matrix_b.mean(axis=1)
        rep_a, _ = _replicate_means(
            matrix_a,
            side_a["layout"],
            iterations,
            np.random.default_rng(_derived_seed(seed, "rank", name_a, metric)),
        )
        rep_b, _ = _replicate_means(
            matrix_b,
            side_b["layout"],
            iterations,
            np.random.default_rng(_derived_seed(seed, "rank", name_b, metric)),
        )
        boot_tau = _tau_b_rows(rep_a, rep_b)
        boot_rho = _pearson_rows(
            np.vstack([_average_ranks(row) for row in rep_a]),
            np.vstack([_average_ranks(row) for row in rep_b]),
        )
        tau = kendall_tau_b(scores_a, scores_b)
        rho = spearman_rho(scores_a, scores_b)
        permutation = rank_permutation_test(
            scores_a,
            scores_b,
            iterations=permutation_iterations,
            seed=_derived_seed(seed, "rank-permutation", metric),
        )
        results[metric] = {
            "scores": [
                {"label": label, name_a: float(sa), name_b: float(sb)}
                for label, sa, sb in zip(labels, scores_a, scores_b)
            ],
            "kendall_tau_b": tau,
            "kendall_tau_b_ci": _interval(tau, boot_tau, confidence_level),
            "kendall_tau_b_p_value": permutation["tau_b_p_value"],
            "spearman_rho": rho,
            "spearman_rho_ci": _interval(rho, boot_rho, confidence_level),
            "spearman_rho_p_value": permutation["spearman_p_value"],
            "permutation": permutation,
            "undefined_bootstrap_replicates": int(np.sum(~np.isfinite(boot_tau))),
            "pairwise": pairwise_order_agreement(scores_a, scores_b, labels),
        }
    warnings = []
    for name, side in ((name_a, side_a), (name_b, side_b)):
        warnings.extend(
            f"{name}: {w}"
            for w in _cluster_warnings(side["layout"], side["sources"], *side["validity"])
        )
    if len(labels) <= 5:
        warnings.append(
            f"only {len(labels)} models: the smallest attainable two-sided permutation "
            "p-value is large; report tau with its interval, not a significance verdict"
        )
    return {
        "analysis": "rank_agreement",
        "name_a": name_a,
        "name_b": name_b,
        "models": labels,
        "n_models": len(labels),
        "n_items_a": side_a["layout"].n_rows,
        "n_items_b": side_b["layout"].n_rows,
        "n_clusters_a": side_a["layout"].n_clusters,
        "n_clusters_b": side_b["layout"].n_clusters,
        **_bootstrap_settings(iterations, confidence_level, seed, cluster_by, stratify_by),
        "permutation_iterations": permutation_iterations,
        "metrics": results,
        "warnings": warnings,
    }


def analyze_self_preference(
    runs_own: Sequence[EvaluationRun],
    runs_other: Sequence[EvaluationRun],
    *,
    self_model: str,
    name_own: str = "G1",
    name_other: str = "G2",
    metric: str = "execution_accuracy",
    benchmark_index_own: Mapping[str, Mapping[str, Any]] | None = None,
    benchmark_index_other: Mapping[str, Mapping[str, Any]] | None = None,
    cluster_by: str = "signature",
    stratify_by: str | None = None,
    iterations: int = DEFAULT_ITERATIONS,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
    seed: int = DEFAULT_SEED,
    max_prediction_failure_rate: float = MAX_PREDICTION_FAILURE_RATE,
) -> dict[str, Any]:
    """Generator self-preference as a 2x2 difference-in-differences.

    ``runs_own`` are scores on the slice generated by ``self_model``'s own
    generator (G1); ``runs_other`` on the slice from another generator (G2).
    For every model, delta = score(G1) - score(G2). The self-preference
    interaction is DiD = delta_self - mean(delta_others), equivalently the
    self model's advantage over the others on its own slice minus that
    advantage on the other slice. A positive DiD means the self model gains
    more from its own generator's slice than other models do. Intervals
    resample clusters within each slice; the placebo p-value re-designates
    every model as "self" and asks how extreme the true self model is.
    """

    labels = _matched_labels(runs_own, runs_other, name_own, name_other)
    if self_model not in labels:
        raise EvaluationInputError(f"self model {self_model!r} not among {labels}")
    if len(labels) < 2:
        raise EvaluationInputError("self-preference needs the self model and at least one other")
    own = _model_matrix_side(
        runs_own, labels, benchmark_index_own, cluster_by, stratify_by, max_prediction_failure_rate
    )
    other = _model_matrix_side(
        runs_other,
        labels,
        benchmark_index_other,
        cluster_by,
        stratify_by,
        max_prediction_failure_rate,
    )
    matrix_own = _metric_matrix(own["rows"], metric)
    matrix_other = _metric_matrix(other["rows"], metric)
    self_idx = labels.index(self_model)
    rep_own, _ = _replicate_means(
        matrix_own,
        own["layout"],
        iterations,
        np.random.default_rng(_derived_seed(seed, "self-pref", name_own, metric)),
    )
    rep_other, _ = _replicate_means(
        matrix_other,
        other["layout"],
        iterations,
        np.random.default_rng(_derived_seed(seed, "self-pref", name_other, metric)),
    )
    scores_own = matrix_own.mean(axis=1)
    scores_other = matrix_other.mean(axis=1)
    point = _self_preference_stats(scores_own[None, :], scores_other[None, :], self_idx)
    boot = _self_preference_stats(rep_own, rep_other, self_idx)
    deltas = scores_own - scores_other
    boot_deltas = rep_own - rep_other
    placebo = [
        float(
            _self_preference_stats(scores_own[None, :], scores_other[None, :], j)[
                "difference_in_differences"
            ][0]
        )
        for j in range(len(labels))
    ]
    observed_did = float(point["difference_in_differences"][0])
    estimates = {
        name: {
            **_interval(float(point[name][0]), boot[name], confidence_level),
            "bootstrap_share_above_zero": float(np.mean(boot[name] > 0)),
        }
        for name in point
    }
    warnings = []
    for name, side in ((name_own, own), (name_other, other)):
        warnings.extend(
            f"{name}: {w}"
            for w in _cluster_warnings(side["layout"], side["sources"], *side["validity"])
        )
    composition = _composition(own["rows"][0], other["rows"][0], "category")
    if composition["total_variation"] > 0.1:
        warnings.append(
            "category composition differs between slices (total variation "
            f"{composition['total_variation']:.2f}); deltas mix generator and category effects"
        )
    if len(labels) < 5:
        warnings.append(
            f"placebo p-value has resolution 1/{len(labels)}; it cannot reach conventional significance"
        )
    return {
        "analysis": "self_preference",
        "metric": metric,
        "self_model": self_model,
        "name_own": name_own,
        "name_other": name_other,
        "models": labels,
        "n_models": len(labels),
        "n_items_own": own["layout"].n_rows,
        "n_items_other": other["layout"].n_rows,
        "n_clusters_own": own["layout"].n_clusters,
        "n_clusters_other": other["layout"].n_clusters,
        **_bootstrap_settings(iterations, confidence_level, seed, cluster_by, stratify_by),
        "per_model": [
            {
                "label": label,
                "is_self": idx == self_idx,
                name_own: float(scores_own[idx]),
                name_other: float(scores_other[idx]),
                "delta": _interval(float(deltas[idx]), boot_deltas[:, idx], confidence_level),
                "placebo_did": placebo[idx],
            }
            for idx, label in enumerate(labels)
        ],
        "estimates": estimates,
        "placebo": {
            "one_sided_p_value": float(np.mean(np.array(placebo) >= observed_did - 1e-12)),
            "two_sided_p_value": float(np.mean(np.abs(placebo) >= abs(observed_did) - 1e-12)),
            "note": "rank of the self model's DiD among DiDs obtained by designating each model as self",
        },
        "composition": composition,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_markdown(report: Mapping[str, Any]) -> str:
    renderer = {
        "cluster_ci": _markdown_cluster_ci,
        "paired": _markdown_paired,
        "models": _markdown_models,
        "rank_agreement": _markdown_rank,
        "self_preference": _markdown_self_preference,
    }[str(report["analysis"])]
    lines = renderer(report)
    if report.get("warnings"):
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in report["warnings"])
    return "\n".join(lines) + "\n"


def render_latex(
    report: Mapping[str, Any], *, caption: str | None = None, label: str | None = None
) -> str:
    renderer = {
        "cluster_ci": _latex_cluster_ci,
        "paired": _latex_paired,
        "models": _latex_models,
        "rank_agreement": _latex_rank,
        "self_preference": _latex_self_preference,
    }[str(report["analysis"])]
    spec, header, body, default_caption, default_label = renderer(report)
    tabular = [rf"\begin{{tabular}}{{{spec}}}", r"\toprule", header, r"\midrule", *body]
    tabular.extend([r"\bottomrule", r"\end{tabular}"])
    return "\n".join(
        [
            r"\begin{table}[t]",
            r"\centering",
            r"\small",
            r"\resizebox{\columnwidth}{!}{%",
            "\n".join(tabular),
            "}",
            rf"\caption{{{caption or default_caption}}}",
            rf"\label{{{label or default_label}}}",
            r"\end{table}",
            "",
        ]
    )


def to_jsonable(value: Any) -> Any:
    """Convert numpy scalars/arrays and non-finite floats for strict JSON."""

    if isinstance(value, Mapping):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return [to_jsonable(v) for v in value.tolist()]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _infer_label(rows: Sequence[Mapping[str, Any]], path: str) -> str:
    models = {str(row["model"]) for row in rows if row.get("model")}
    return models.pop() if len(models) == 1 else Path(path).stem


def _benchmark_gold(row: Mapping[str, Any]) -> str:
    return str(row.get("cypher") or row.get("normalized_cypher") or "")


def _check_gold_consistency(row: Mapping[str, Any], bench: Mapping[str, Any]) -> None:
    gold = str(row.get("gold_cypher") or "").strip()
    if not gold:
        return
    candidates = {str(bench.get(k) or "").strip() for k in ("cypher", "normalized_cypher")}
    if gold not in candidates:
        raise EvaluationInputError(
            f"item {row.get('id')}: evaluation gold Cypher differs from the benchmark row; "
            "the evaluation was produced on a different export or split"
        )


def _cluster_key(
    row_id: str,
    row: Mapping[str, Any],
    bench: Mapping[str, Any] | None,
    mode: str,
) -> tuple[str, str]:
    if mode == "none":
        return f"row:{row_id}", "row"
    gold = (_benchmark_gold(bench) if bench else "") or str(row.get("gold_cypher") or "")
    template = (bench or {}).get("template") or row.get("template")
    if mode == "signature":
        if gold.strip():
            return "sig:" + canonical_query_signature(gold), "signature"
        if template:
            return "tpl:" + str(template), "template"
        return f"row:{row_id}", "row"
    pseudo = (
        dict(bench)
        if bench
        else {
            "template": row.get("template"),
            "template_metadata": row.get("template_metadata") or {},
            "cypher": gold,
        }
    )
    if not (gold.strip() or template or (pseudo.get("template_metadata") or {})):
        return f"row:{row_id}", "row"
    return "fam:" + template_family_signature(pseudo), "template_family"


def _row_prediction_failed(row: Mapping[str, Any]) -> bool:
    if "prediction_failed" in row:
        return bool(row["prediction_failed"])
    error = row.get("prediction_error", row.get("error"))
    return error not in (None, "", "None") and not str(row.get("predicted_cypher") or "").strip()


def _check_bootstrap_args(iterations: int, confidence_level: float) -> None:
    if iterations <= 1:
        raise EvaluationInputError("iterations must be at least 2")
    if not 0.0 < confidence_level < 1.0:
        raise EvaluationInputError("confidence_level must be between 0 and 1")


def _bootstrap_weight_chunks(
    layout: ClusterLayout, iterations: int, rng: np.random.Generator
) -> Iterator[np.ndarray]:
    """Multinomial draw counts per cluster; equivalent to sampling clusters
    with replacement within each stratum."""

    done = 0
    while done < iterations:
        size = min(_BOOTSTRAP_CHUNK, iterations - done)
        weights = np.zeros((size, layout.n_clusters))
        for members in layout.strata:
            k = int(members.shape[0])
            weights[:, members] = rng.multinomial(k, np.full(k, 1.0 / k), size=size)
        yield weights
        done += size


def _replicate_means(
    matrix: np.ndarray, layout: ClusterLayout, iterations: int, rng: np.random.Generator
) -> tuple[np.ndarray, np.ndarray]:
    """Bootstrap replicates (iterations x models) of pooled and macro means."""

    if matrix.shape[1] != layout.n_rows:
        raise EvaluationInputError("metric matrix and cluster layout disagree on row count")
    sums = np.vstack(
        [np.bincount(layout.index, weights=row, minlength=layout.n_clusters) for row in matrix]
    )
    cluster_means = sums / layout.sizes
    micro: list[np.ndarray] = []
    macro: list[np.ndarray] = []
    for weights in _bootstrap_weight_chunks(layout, iterations, rng):
        micro.append((weights @ sums.T) / (weights @ layout.sizes)[:, None])
        macro.append((weights @ cluster_means.T) / weights.sum(axis=1)[:, None])
    return np.vstack(micro), np.vstack(macro)


def _interval(point: float, replicates: np.ndarray, confidence_level: float) -> dict[str, Any]:
    finite = np.asarray(replicates, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return {"point": point, "lower": None, "upper": None, "standard_error": None, "width": None}
    alpha = 1.0 - confidence_level
    lower, upper = np.quantile(finite, [alpha / 2.0, 1.0 - alpha / 2.0])
    return {
        "point": float(point),
        "lower": float(lower),
        "upper": float(upper),
        "standard_error": float(np.std(finite, ddof=1)) if finite.size > 1 else 0.0,
        "width": float(upper - lower),
    }


def _bootstrap_settings(
    iterations: int, confidence_level: float, seed: int, cluster_by: str, stratify_by: str | None
) -> dict[str, Any]:
    _check_bootstrap_args(iterations, confidence_level)
    return {
        "method": "percentile_bootstrap",
        "iterations": iterations,
        "confidence_level": confidence_level,
        "seed": seed,
        "cluster_by": cluster_by,
        "stratify_by": stratify_by,
    }


def _cluster_warnings(
    layout: ClusterLayout, sources: Mapping[str, int], *validities: Mapping[str, Any]
) -> list[str]:
    warnings: list[str] = []
    if layout.n_clusters < FEW_CLUSTERS:
        warnings.append(
            f"only {layout.n_clusters} clusters: percentile cluster-bootstrap intervals "
            "under-cover with few clusters; read them as a lower bound on uncertainty"
        )
    if sources.get("row") and len(sources) > 1:
        warnings.append(
            f"{sources['row']} rows had no gold Cypher or template and were treated as "
            "singleton clusters"
        )
    if sources.get("template"):
        warnings.append(f"{sources['template']} rows clustered by template field (no gold Cypher)")
    for members, name in zip(layout.strata, layout.stratum_names):
        if name and members.shape[0] < 2:
            warnings.append(f"stratum {name!r} has a single cluster and contributes no variance")
    for validity in validities:
        if validity.get("source") != "prediction_failed":
            warnings.append(
                "prediction_failed field absent (legacy file); failure rate derived from "
                f"{validity.get('source')}"
            )
            break
    return warnings


def _strata(rows: Sequence[Mapping[str, Any]], key: str | None) -> list[str] | None:
    if not key:
        return None
    return [str(row.get(key, "unknown")) for row in rows]


def _group_indices(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, np.ndarray]:
    grouped: dict[str, list[int]] = defaultdict(list)
    for i, row in enumerate(rows):
        grouped[str(row.get(key, "unknown"))].append(i)
    return {name: np.array(idx, dtype=np.int64) for name, idx in grouped.items()}


def _split_available(
    rows: Sequence[Mapping[str, Any]], metrics: Sequence[str], require: bool
) -> tuple[list[str], list[str]]:
    available = [metric for metric in metrics if metric_available(rows, metric)]
    unavailable = [metric for metric in metrics if metric not in available]
    if require and unavailable:
        raise MetricUnavailableError(f"metrics unavailable in evaluation rows: {unavailable}")
    return available, unavailable


def _align_to(
    reference: Sequence[Mapping[str, Any]],
    rows: Sequence[Mapping[str, Any]],
    reference_label: str,
    label: str,
) -> list[Mapping[str, Any]]:
    ref_ids = [str(row["id"]) for row in reference]
    by_id = {str(row["id"]): row for row in rows}
    missing = sorted(set(ref_ids) - set(by_id))
    extra = sorted(set(by_id) - set(ref_ids))
    if missing or extra:
        raise EvaluationInputError(
            f"item ids differ: {len(missing)} only in {reference_label} (e.g. {missing[:3]}), "
            f"{len(extra)} only in {label} (e.g. {extra[:3]})"
        )
    return [by_id[row_id] for row_id in ref_ids]


def _require_same_id_sets(runs: Sequence[EvaluationRun]) -> None:
    reference = runs[0]
    for run in runs[1:]:
        _align_to(reference.rows, run.rows, reference.label, run.label)


def _unique_labels(runs: Sequence[EvaluationRun]) -> None:
    duplicates = [label for label, count in Counter(r.label for r in runs).items() if count > 1]
    if duplicates:
        raise EvaluationInputError(f"duplicate model labels: {duplicates}; pass LABEL=PATH")


def _matched_labels(
    runs_a: Sequence[EvaluationRun], runs_b: Sequence[EvaluationRun], name_a: str, name_b: str
) -> list[str]:
    _unique_labels(runs_a)
    _unique_labels(runs_b)
    labels_a = [run.label for run in runs_a]
    labels_b = {run.label for run in runs_b}
    if set(labels_a) != labels_b:
        raise EvaluationInputError(
            f"model labels differ: only in {name_a} {sorted(set(labels_a) - labels_b)}, "
            f"only in {name_b} {sorted(labels_b - set(labels_a))}"
        )
    return labels_a


def _model_matrix_side(
    runs: Sequence[EvaluationRun],
    labels: Sequence[str],
    benchmark_index: Mapping[str, Mapping[str, Any]] | None,
    cluster_by: str,
    stratify_by: str | None,
    max_prediction_failure_rate: float,
) -> dict[str, Any]:
    """Validate, align all models to one item order, and build its layout."""

    by_label = {run.label: run for run in runs}
    ordered = [by_label[label] for label in labels]
    validity = [
        check_run_validity(run, max_prediction_failure_rate=max_prediction_failure_rate)
        for run in ordered
    ]
    reference = ordered[0]
    aligned = [list(reference.rows)] + [
        _align_to(reference.rows, run.rows, reference.label, run.label) for run in ordered[1:]
    ]
    keys, sources = cluster_keys_for_rows(
        reference.rows, benchmark_index=benchmark_index, cluster_by=cluster_by
    )
    return {
        "rows": aligned,
        "layout": build_cluster_layout(keys, _strata(reference.rows, stratify_by)),
        "sources": sources,
        "validity": validity,
    }


def _metric_matrix(aligned_rows: Sequence[Sequence[Mapping[str, Any]]], metric: str) -> np.ndarray:
    return np.vstack([metric_column(rows, metric)[0] for rows in aligned_rows])


def _self_preference_stats(
    own: np.ndarray, other: np.ndarray, self_idx: int
) -> dict[str, np.ndarray]:
    mask = np.ones(own.shape[1], dtype=bool)
    mask[self_idx] = False
    deltas = own - other
    own_advantage = own[:, self_idx] - own[:, mask].mean(axis=1)
    other_advantage = other[:, self_idx] - other[:, mask].mean(axis=1)
    return {
        "self_advantage_own_slice": own_advantage,
        "self_advantage_other_slice": other_advantage,
        "difference_in_differences": own_advantage - other_advantage,
        "difference_in_differences_vs_median": deltas[:, self_idx]
        - np.median(deltas[:, mask], axis=1),
    }


def _composition(
    rows_a: Sequence[Mapping[str, Any]], rows_b: Sequence[Mapping[str, Any]], key: str
) -> dict[str, Any]:
    counts_a = Counter(str(row.get(key, "unknown")) for row in rows_a)
    counts_b = Counter(str(row.get(key, "unknown")) for row in rows_b)
    names = sorted(set(counts_a) | set(counts_b))
    tv = 0.5 * sum(
        abs(counts_a[n] / max(1, len(rows_a)) - counts_b[n] / max(1, len(rows_b))) for n in names
    )
    return {
        "key": key,
        "own": dict(sorted(counts_a.items())),
        "other": dict(sorted(counts_b.items())),
        "total_variation": tv,
    }


def _distribution_summary(values: Sequence[float]) -> dict[str, Any]:
    array = np.sort(np.asarray(values, dtype=float))
    q1, median, q3 = np.quantile(array, [0.25, 0.5, 0.75])
    return {
        "n_models": int(array.size),
        "median": float(median),
        "q1": float(q1),
        "q3": float(q3),
        "iqr": float(q3 - q1),
        "min": float(array[0]),
        "max": float(array[-1]),
        "mean": float(array.mean()),
        "sorted_values": [float(v) for v in array],
    }


def _threshold_key(value: float) -> str:
    return f"{value:g}"


def _as_pair(x: Sequence[float], y: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
    xs = np.asarray(x, dtype=float)
    ys = np.asarray(y, dtype=float)
    if xs.ndim != 1 or xs.shape != ys.shape:
        raise EvaluationInputError("rank statistics need two equal-length score vectors")
    if xs.size < 2:
        raise EvaluationInputError("rank statistics need at least two models")
    return xs, ys


def _sign(value: float) -> int:
    if abs(value) <= _TIE_TOLERANCE:
        return 0
    return 1 if value > 0 else -1


def _sign_array(values: np.ndarray) -> np.ndarray:
    signs = np.sign(values)
    signs[np.abs(values) <= _TIE_TOLERANCE] = 0.0
    return signs


def _tau_b_rows(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Row-wise Kendall tau-b for score matrices of shape (rows, models)."""

    i, j = np.triu_indices(x.shape[1], k=1)
    sx = _sign_array(x[:, i] - x[:, j])
    sy = _sign_array(y[:, i] - y[:, j])
    pairs = i.shape[0]
    tied_x = np.sum(sx == 0, axis=1)
    tied_y = np.sum(sy == 0, axis=1)
    denominator = np.sqrt((pairs - tied_x) * (pairs - tied_y).astype(float))
    numerator = np.sum(sx * sy, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(
            denominator > 0, numerator / np.where(denominator > 0, denominator, 1.0), np.nan
        )


def _average_ranks(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(values.shape[0])
    sorted_values = values[order]
    start = 0
    while start < values.shape[0]:
        end = start
        while (
            end + 1 < values.shape[0]
            and abs(sorted_values[end + 1] - sorted_values[start]) <= _TIE_TOLERANCE
        ):
            end += 1
        ranks[order[start : end + 1]] = (start + end) / 2.0 + 1.0
        start = end + 1
    return ranks


def _pearson_rows(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    xc = x - x.mean(axis=1, keepdims=True)
    yc = y - y.mean(axis=1, keepdims=True)
    denominator = np.sqrt(np.sum(xc * xc, axis=1) * np.sum(yc * yc, axis=1))
    numerator = np.sum(xc * yc, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(
            denominator > 0, numerator / np.where(denominator > 0, denominator, 1.0), np.nan
        )


def _label(metric: str) -> str:
    return METRIC_LABELS.get(metric, metric.replace("_", " ").title())


def _fmt(value: Any, digits: int = 3) -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "--"
    return f"{float(value):.{digits}f}"


def _fmt_ci(interval: Mapping[str, Any] | None, digits: int = 3) -> str:
    if not interval or interval.get("lower") is None:
        return "--"
    return f"[{_fmt(interval['lower'], digits)}, {_fmt(interval['upper'], digits)}]"


def _fmt_signed(value: Any, digits: int = 3) -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "--"
    return f"{float(value):+.{digits}f}"


def _fmt_p(value: Any, *, latex: bool = False) -> str:
    if value is None:
        return "--"
    if float(value) < 0.001:
        return "$<$0.001" if latex else "<0.001"
    return f"{float(value):.3f}"


def _tex(value: str) -> str:
    return _escape_latex(str(value))


def _ci_percent(report: Mapping[str, Any]) -> str:
    return f"{round(float(report['confidence_level']) * 100)}"


def _method_line(report: Mapping[str, Any]) -> str:
    strat = f", stratified by {report['stratify_by']}" if report.get("stratify_by") else ""
    return (
        f"Percentile bootstrap, {report['iterations']:,} resamples, seed {report['seed']}, "
        f"{_ci_percent(report)}% intervals, clusters = {report['cluster_by']}{strat}."
    )


def _markdown_cluster_ci(report: Mapping[str, Any]) -> list[str]:
    lines = [
        f"# Clustered Bootstrap Intervals: {report['label']}",
        "",
        _method_line(report),
        (
            f"Items: {report['n']}; clusters: {report['n_clusters']}; "
            f"largest cluster sizes: {report['cluster_sizes'][:8]}."
        ),
        "",
        "| Metric | N | K | Point | Row CI | Cluster CI | Row width | Cluster width | DEff | Eff. N | Signature-macro (CI) |",
        "| --- | ---: | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    lines.extend(
        _markdown_interval_row(metric, interval) for metric, interval in report["metrics"].items()
    )
    if report.get("unavailable_metrics"):
        lines.extend(["", f"Unavailable metrics: {', '.join(report['unavailable_metrics'])}."])
    for group_key, groups in report.get("groups", {}).items():
        lines.extend(["", f"## By {group_key}", ""])
        lines.append("| Group | Metric | N | K | Point | Row CI | Cluster CI | DEff |")
        lines.append("| --- | --- | ---: | ---: | ---: | --- | --- | ---: |")
        for name, metrics in groups.items():
            for metric, interval in metrics.items():
                lines.append(
                    f"| {name} | {_label(metric)} | {interval['n']} | {interval['n_clusters']} | "
                    f"{_fmt(interval['point'])} | {_fmt_ci(interval['row'])} | "
                    f"{_fmt_ci(interval['cluster'])} | {_fmt(interval['design_effect'], 2)} |"
                )
    return lines


def _markdown_interval_row(metric: str, interval: Mapping[str, Any]) -> str:
    macro = interval["signature_macro"]
    return (
        f"| {_label(metric)} | {interval['n']} | {interval['n_clusters']} | {_fmt(interval['point'])} | "
        f"{_fmt_ci(interval['row'])} | {_fmt_ci(interval['cluster'])} | "
        f"{_fmt(interval['row']['width'])} | {_fmt(interval['cluster']['width'])} | "
        f"{_fmt(interval['design_effect'], 2)} | {_fmt(interval['effective_n'], 1)} | "
        f"{_fmt(macro['point'])} {_fmt_ci(macro)} |"
    )


def _latex_cluster_ci(report: Mapping[str, Any]):
    pct = _ci_percent(report)
    header = rf"Metric & Point & Row {pct}\% CI & Cluster {pct}\% CI & DEff & $N$/$K$ \\"
    body = [
        "{metric} & {point} & {row} & {cluster} & {deff} & {n}/{k} \\\\".format(
            metric=_tex(_label(metric)),
            point=_fmt(interval["point"]),
            row=_fmt_ci(interval["row"]),
            cluster=_fmt_ci(interval["cluster"]),
            deff=_fmt(interval["design_effect"], 1),
            n=interval["n"],
            k=interval["n_clusters"],
        )
        for metric, interval in report["metrics"].items()
    ]
    caption = (
        f"Row-level versus query-signature-clustered bootstrap intervals for {_tex(report['label'])} "
        f"on {report['n']} held-out items in {report['n_clusters']} canonical signature clusters "
        f"({report['iterations']:,} resamples, seed {report['seed']}). DEff is the clustered-to-row "
        "variance ratio: row-level intervals treat template-sharing items as independent and "
        "understate uncertainty."
    )
    return "lrrrrr", header, body, caption, "tab:downstream_cluster_ci"


def _markdown_paired(report: Mapping[str, Any]) -> list[str]:
    a, b = report["label_a"], report["label_b"]
    lines = [
        f"# Paired Comparison: {b} minus {a}",
        "",
        _method_line(report),
        f"Items: {report['n']} (identical ids); clusters: {report['n_clusters']}.",
        (
            "McNemar p assumes independent items; the cluster sign-flip p flips whole "
            "signature clusters and is the template-robust test."
        ),
        "",
        f"| Metric | {a} | {b} | Delta | Row CI | Cluster CI | DEff | b (A only) | c (B only) | McNemar p | Cluster sign-flip p |",
        "| --- | ---: | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for metric, entry in report["metrics"].items():
        mcnemar = entry.get("mcnemar") or {}
        lines.append(
            f"| {_label(metric)} | {_fmt(entry['mean_a'])} | {_fmt(entry['mean_b'])} | "
            f"{_fmt_signed(entry['difference'])} | {_fmt_ci(entry['row_ci'])} | "
            f"{_fmt_ci(entry['cluster_ci'])} | {_fmt(entry['design_effect'], 2)} | "
            f"{mcnemar.get('a_correct_b_wrong', '--')} | {mcnemar.get('a_wrong_b_correct', '--')} | "
            f"{_fmt_p(mcnemar.get('p_value'))} | {_fmt_p(entry['cluster_sign_flip']['p_value'])} "
            f"({entry['cluster_sign_flip']['method']}, {entry['cluster_sign_flip']['informative_clusters']} clusters) |"
        )
    if report.get("unavailable_metrics"):
        lines.extend(["", f"Unavailable metrics: {', '.join(report['unavailable_metrics'])}."])
    return lines


def _latex_paired(report: Mapping[str, Any]):
    pct = _ci_percent(report)
    header = (
        rf"Metric & {_tex(report['label_a'])} & {_tex(report['label_b'])} & $\Delta$ & "
        rf"Cluster {pct}\% CI & $b$/$c$ & McNemar $p$ & Cluster $p$ \\"
    )
    body = []
    for metric, entry in report["metrics"].items():
        mcnemar = entry.get("mcnemar")
        discordant = (
            f"{mcnemar['a_correct_b_wrong']}/{mcnemar['a_wrong_b_correct']}" if mcnemar else "--"
        )
        body.append(
            f"{_tex(_label(metric))} & {_fmt(entry['mean_a'])} & {_fmt(entry['mean_b'])} & "
            f"{_fmt_signed(entry['difference'])} & {_fmt_ci(entry['cluster_ci'])} & {discordant} & "
            f"{_fmt_p(mcnemar['p_value'] if mcnemar else None, latex=True)} & "
            f"{_fmt_p(entry['cluster_sign_flip']['p_value'], latex=True)} \\\\"
        )
    caption = (
        f"Paired comparison on {report['n']} identical held-out items ($\\Delta$ = "
        f"{_tex(report['label_b'])} $-$ {_tex(report['label_a'])}). $b$/$c$ count items solved only "
        "by the first/second condition. McNemar assumes independent items; the cluster $p$ flips "
        f"whole query-signature clusters ({report['n_clusters']}) and is robust to template sharing."
    )
    return "lrrrrrrr", header, body, caption, "tab:downstream_paired"


def _markdown_models(report: Mapping[str, Any]) -> list[str]:
    metrics = report["metrics_requested"]
    lines = [
        "# Multi-Model Downstream Summary",
        "",
        _method_line(report),
        (
            f"Models: {report['n_models']}; clusters: {report['n_clusters']}. "
            "Cells show point estimate and clustered CI."
        ),
        "",
        "| Model | " + " | ".join(_label(m) for m in metrics) + " |",
        "| --- | " + " | ".join("---" for _ in metrics) + " |",
    ]
    for model in report["models"]:
        cells = []
        for metric in metrics:
            entry = model["metrics"].get(metric)
            cells.append(
                f"{_fmt(entry['point'])} {_fmt_ci(entry['cluster_ci'])}" if entry else "--"
            )
        lines.append(f"| {model['label']} | " + " | ".join(cells) + " |")
    lines.extend(["", "## Across models (median and IQR; mean shown only alongside)", ""])
    lines.append("| Metric | Models | Median | Q1 | Q3 | IQR | Min | Max | Mean |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for metric in metrics:
        agg = report["across_models"].get(metric)
        if not agg:
            lines.append(f"| {_label(metric)} | 0 | -- | -- | -- | -- | -- | -- | -- |")
            continue
        lines.append(
            f"| {_label(metric)} | {agg['n_models']} | {_fmt(agg['median'])} | {_fmt(agg['q1'])} | "
            f"{_fmt(agg['q3'])} | {_fmt(agg['iqr'])} | {_fmt(agg['min'])} | {_fmt(agg['max'])} | "
            f"{_fmt(agg['mean'])} |"
        )
    if report["threshold_counts"]:
        lines.extend(["", "## Models above thresholds", ""])
        lines.append("| Metric | Threshold | Scored | Point above | Cluster CI lower above |")
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        for metric, by_threshold in report["threshold_counts"].items():
            for threshold, counts in by_threshold.items():
                lines.append(
                    f"| {_label(metric)} | {threshold} | {counts['models_scored']} | "
                    f"{counts['point_above']} | {counts['cluster_ci_lower_above']} |"
                )
    if report["excluded_runs"]:
        lines.extend(["", "## Excluded runs", ""])
        lines.extend(f"- {run['label']}: {run['reason']}" for run in report["excluded_runs"])
    return lines


def _latex_models(report: Mapping[str, Any]):
    metrics = report["metrics_requested"]
    pct = _ci_percent(report)
    with_ci = [m for m in metrics if m in THRESHOLD_METRICS]
    header_cells = ["Model"] + [
        f"{_tex(_label(m))} [{pct}\\% CI]" if m in with_ci else _tex(_label(m)) for m in metrics
    ]
    body = []
    for model in report["models"]:
        cells = [_tex(model["label"])]
        for metric in metrics:
            entry = model["metrics"].get(metric)
            if not entry:
                cells.append("--")
            elif metric in with_ci:
                cells.append(f"{_fmt(entry['point'])} {_fmt_ci(entry['cluster_ci'], 2)}")
            else:
                cells.append(_fmt(entry["point"]))
        body.append(" & ".join(cells) + r" \\")
    body.append(r"\midrule")
    median_cells = [r"Median [IQR]"]
    for metric in metrics:
        agg = report["across_models"].get(metric)
        median_cells.append(
            f"{_fmt(agg['median'])} [{_fmt(agg['q1'], 2)}, {_fmt(agg['q3'], 2)}]" if agg else "--"
        )
    body.append(" & ".join(median_cells) + r" \\")
    for metric, by_threshold in report["threshold_counts"].items():
        if metric != "execution_accuracy":
            continue
        for threshold in by_threshold:
            cells = [f"Models $>$ {threshold} (CI lower $>$ {threshold})"]
            for m in metrics:
                if m in report["threshold_counts"] and threshold in report["threshold_counts"][m]:
                    c = report["threshold_counts"][m][threshold]
                    cells.append(
                        f"{c['point_above']}/{c['models_scored']} ({c['cluster_ci_lower_above']})"
                    )
                else:
                    cells.append("")
            body.append(" & ".join(cells) + r" \\")
    caption = (
        f"Per-model downstream results with query-signature-clustered {pct}\\% intervals "
        f"({report['n_clusters']} clusters, {report['iterations']:,} resamples). The model set is "
        "heterogeneous, so the cross-model summary reports the median and interquartile range "
        "rather than a mean; threshold rows count models whose point estimate (and clustered lower "
        "bound) exceeds the threshold."
    )
    return (
        "l" + "r" * len(metrics),
        " & ".join(header_cells) + r" \\",
        body,
        caption,
        "tab:downstream_models",
    )


def _markdown_rank(report: Mapping[str, Any]) -> list[str]:
    a, b = report["name_a"], report["name_b"]
    lines = [
        f"# Ranking Agreement: {a} vs {b}",
        "",
        _method_line(report),
        (
            f"Models: {report['n_models']}; items {a}={report['n_items_a']} "
            f"({report['n_clusters_a']} clusters), {b}={report['n_items_b']} "
            f"({report['n_clusters_b']} clusters)."
        ),
    ]
    for metric, entry in report["metrics"].items():
        pairwise = entry["pairwise"]
        lines.extend(
            [
                "",
                f"## {_label(metric)}",
                "",
                "| Statistic | Value | CI | Permutation p |",
                "| --- | ---: | --- | ---: |",
                (
                    f"| Kendall tau-b | {_fmt(entry['kendall_tau_b'])} | "
                    f"{_fmt_ci(entry['kendall_tau_b_ci'])} | "
                    f"{_fmt_p(entry['kendall_tau_b_p_value'])} ({entry['permutation']['method']}) |"
                ),
                (
                    f"| Spearman rho | {_fmt(entry['spearman_rho'])} | "
                    f"{_fmt_ci(entry['spearman_rho_ci'])} | "
                    f"{_fmt_p(entry['spearman_rho_p_value'])} |"
                ),
                "",
                (
                    f"Pairwise order: {pairwise['concordant']} concordant, "
                    f"{pairwise['discordant']} discordant, {pairwise['tied_a_only']} tied in {a} "
                    f"only, {pairwise['tied_b_only']} tied in {b} only, {pairwise['tied_both']} "
                    f"tied in both (of {pairwise['pairs']} pairs)."
                ),
                "",
                f"| Model | {a} | {b} |",
                "| --- | ---: | ---: |",
            ]
        )
        lines.extend(
            f"| {score['label']} | {_fmt(score[a])} | {_fmt(score[b])} |"
            for score in entry["scores"]
        )
        if pairwise["discordant_pairs"]:
            lines.extend(
                [
                    "",
                    "Discordant pairs: "
                    + "; ".join(" vs ".join(p) for p in pairwise["discordant_pairs"]),
                ]
            )
    return lines


def _latex_rank(report: Mapping[str, Any]):
    pct = _ci_percent(report)
    header = (
        rf"Metric & $m$ & Kendall $\tau_b$ [{pct}\% CI] & $p$ & Spearman $\rho$ [{pct}\% CI] & $p$ & "
        r"Conc./Disc./Tied \\"
    )
    body = []
    for metric, entry in report["metrics"].items():
        pairwise = entry["pairwise"]
        tied = pairwise["tied_a_only"] + pairwise["tied_b_only"] + pairwise["tied_both"]
        body.append(
            f"{_tex(_label(metric))} & {report['n_models']} & {_fmt(entry['kendall_tau_b'])} "
            f"{_fmt_ci(entry['kendall_tau_b_ci'], 2)} & {_fmt_p(entry['kendall_tau_b_p_value'], latex=True)} & "
            f"{_fmt(entry['spearman_rho'])} {_fmt_ci(entry['spearman_rho_ci'], 2)} & "
            f"{_fmt_p(entry['spearman_rho_p_value'], latex=True)} & "
            f"{pairwise['concordant']}/{pairwise['discordant']}/{tied} \\\\"
        )
    caption = (
        f"Agreement between model rankings on {_tex(report['name_a'])} and {_tex(report['name_b'])}. "
        "Intervals resample items independently within each benchmark (clustered by query "
        "signature) with the same draw applied to every model; $p$-values are two-sided "
        "permutation tests over model labels and ignore item-sampling noise."
    )
    return "lrrrrrr", header, body, caption, "tab:rank_agreement"


def _markdown_self_preference(report: Mapping[str, Any]) -> list[str]:
    own, other = report["name_own"], report["name_other"]
    lines = [
        f"# Generator Self-Preference: {report['self_model']}",
        "",
        _method_line(report),
        (
            f"Metric: {_label(report['metric'])}. {own} is the self model's generator slice "
            f"({report['n_items_own']} items, {report['n_clusters_own']} clusters); {other} is "
            f"the comparison slice ({report['n_items_other']} items, "
            f"{report['n_clusters_other']} clusters)."
        ),
        "",
        f"| Model | {own} | {other} | Delta ({own} - {other}) | Delta CI | Placebo DiD |",
        "| --- | ---: | ---: | ---: | --- | ---: |",
    ]
    for model in report["per_model"]:
        name = f"**{model['label']}** (self)" if model["is_self"] else model["label"]
        lines.append(
            f"| {name} | {_fmt(model[own])} | {_fmt(model[other])} | {_fmt_signed(model['delta']['point'])} | "
            f"{_fmt_ci(model['delta'])} | {_fmt_signed(model['placebo_did'])} |"
        )
    lines.extend(
        ["", "| Estimate | Point | CI | Bootstrap share > 0 |", "| --- | ---: | --- | ---: |"]
    )
    for name, estimate in report["estimates"].items():
        lines.append(
            f"| {name.replace('_', ' ')} | {_fmt_signed(estimate['point'])} | {_fmt_ci(estimate)} | "
            f"{_fmt(estimate['bootstrap_share_above_zero'])} |"
        )
    placebo = report["placebo"]
    lines.extend(
        [
            "",
            (
                "Placebo p-values (self model's DiD ranked against every model designated as "
                f"self): one-sided {_fmt(placebo['one_sided_p_value'])}, two-sided "
                f"{_fmt(placebo['two_sided_p_value'])}."
            ),
        ]
    )
    return lines


def _latex_self_preference(report: Mapping[str, Any]):
    own, other = report["name_own"], report["name_other"]
    pct = _ci_percent(report)
    header = rf"Model & {_tex(own)} & {_tex(other)} & $\Delta$ [{pct}\% CI] \\"
    body = []
    for model in report["per_model"]:
        name = rf"\textbf{{{_tex(model['label'])}}}" if model["is_self"] else _tex(model["label"])
        body.append(
            f"{name} & {_fmt(model[own])} & {_fmt(model[other])} & "
            f"{_fmt_signed(model['delta']['point'])} {_fmt_ci(model['delta'], 2)} \\\\"
        )
    body.append(r"\midrule")
    labels = {
        "self_advantage_own_slice": f"Self advantage on {_tex(own)}",
        "self_advantage_other_slice": f"Self advantage on {_tex(other)}",
        "difference_in_differences": "Difference-in-differences",
    }
    for name, text in labels.items():
        estimate = report["estimates"][name]
        body.append(
            rf"\multicolumn{{3}}{{l}}{{{text}}} & {_fmt_signed(estimate['point'])} {_fmt_ci(estimate, 2)} \\"
        )
    placebo = report["placebo"]
    body.append(
        rf"\multicolumn{{3}}{{l}}{{Placebo $p$ (one-/two-sided)}} & {_fmt(placebo['one_sided_p_value'])} / "
        rf"{_fmt(placebo['two_sided_p_value'])} \\"
    )
    caption = (
        f"Generator self-preference for {_tex(report['self_model'])} (bold) on {_tex(_label(report['metric']))}. "
        f"$\\Delta$ is each model's score on the self-generated slice ({_tex(own)}) minus the comparison "
        f"slice ({_tex(other)}); the difference-in-differences is the self model's $\\Delta$ minus the "
        "mean $\\Delta$ of the other models, with clustered bootstrap intervals and a placebo $p$-value "
        "obtained by designating every model as self."
    )
    return "lrrr", header, body, caption, "tab:self_preference"
