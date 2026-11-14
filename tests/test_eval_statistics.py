from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from pipecypher.eval_statistics import (
    EvaluationInputError,
    EvaluationRun,
    MetricUnavailableError,
    analyze_cluster_ci,
    analyze_models,
    analyze_paired,
    analyze_rank_agreement,
    analyze_self_preference,
    cluster_bootstrap_interval,
    cluster_keys_for_rows,
    cluster_sign_flip_test,
    kendall_tau_b,
    mcnemar_exact,
    metric_column,
    pairwise_order_agreement,
    rank_permutation_test,
    render_latex,
    render_markdown,
    spearman_rho,
)
from scripts.analyze_downstream_statistics import main as stats_main


def _row(item: int, cluster: int, correct: bool, **extra):
    row = {
        "id": f"q{item:04d}",
        # Numeric literals are masked by the canonical signature, so items in
        # the same cluster collapse to one signature while labels separate
        # clusters.
        "gold_cypher": f"MATCH (n:Label{cluster} {{id: {item}}}) RETURN n.name",
        "graph_profile": "finbench" if cluster % 2 == 0 else "snb",
        "category": "simple_retrieval",
        "difficulty": "easy",
        "execution_accuracy": bool(correct),
        "projected_execution_accuracy": bool(correct),
        "answer_f1": 1.0 if correct else 0.0,
        "execution_success": True,
        "parse_valid": True,
        "schema_valid": True,
        "governance_valid": True,
        "prediction_failed": False,
    }
    row.update(extra)
    return row


def _homogeneous_rows(n_clusters: int = 10, size: int = 20, offset: int = 0):
    """Half the clusters all-correct, half all-wrong."""

    rows = []
    for cluster in range(n_clusters):
        for j in range(size):
            item = offset + cluster * size + j
            rows.append(_row(item, cluster, cluster % 2 == 0))
    return rows


def _rows_with_rates(rates, *, n_clusters=12, size=10, offset=0, cluster_offset=0):
    """Deterministic rows where a fraction ``rate`` of every cluster is correct."""

    rows = []
    for cluster in range(n_clusters):
        for j in range(size):
            item = offset + cluster * size + j
            rows.append(_row(item, cluster_offset + cluster, j < round(rates * size)))
    return rows


# --- exact tests -----------------------------------------------------------


def test_mcnemar_exact_known_values():
    # Two-sided exact binomial on discordant pairs, doubling the smaller tail.
    assert mcnemar_exact(1, 9) == pytest.approx(22 / 1024)
    assert mcnemar_exact(9, 1) == pytest.approx(22 / 1024)
    assert mcnemar_exact(0, 5) == pytest.approx(2 / 32)
    assert mcnemar_exact(3, 3) == 1.0
    assert mcnemar_exact(0, 0) == 1.0
    # 2 * sum_{i<=2} C(12, i) / 2^12 = 2 * 79 / 4096
    assert mcnemar_exact(2, 10) == pytest.approx(158 / 4096)
    # Large counts must not overflow float conversion.
    assert 0.0 <= mcnemar_exact(400, 700) < 1e-15


def test_kendall_tau_b_hand_computed_cases():
    assert kendall_tau_b([1, 2, 3, 4], [1, 2, 3, 4]) == pytest.approx(1.0)
    assert kendall_tau_b([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    # 6 concordant, 4 discordant of 10 pairs, no ties.
    assert kendall_tau_b([1, 2, 3, 4, 5], [3, 4, 1, 2, 5]) == pytest.approx(0.2)
    # One tie in x: nc=5, nd=0, n0=6, n1=1, n2=0 -> 5 / sqrt(5 * 6).
    assert kendall_tau_b([1, 2, 2, 3], [1, 3, 2, 4]) == pytest.approx(5 / math.sqrt(30))
    # Ties in both: nc=3, nd=0, n1=1, n2=3 -> 3 / sqrt(5 * 3).
    assert kendall_tau_b([1, 1, 2, 3], [1, 1, 1, 2]) == pytest.approx(3 / math.sqrt(15))
    assert math.isnan(kendall_tau_b([1, 1, 1], [1, 2, 3]))


def test_spearman_rho_with_average_ranks():
    assert spearman_rho([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    # x ranks [1, 2.5, 2.5, 4] against y ranks [1, 2, 3, 4].
    assert spearman_rho([1, 2, 2, 3], [1, 2, 3, 4]) == pytest.approx(4.5 / math.sqrt(4.5 * 5.0))


def test_pairwise_order_agreement_counts_ties_and_discordant_pairs():
    result = pairwise_order_agreement([1, 2, 2, 3], [1, 3, 2, 2], ["a", "b", "c", "d"])
    assert result["pairs"] == 6
    assert result["concordant"] == 3
    assert result["discordant"] == 1
    assert result["tied_a_only"] == 1
    assert result["tied_b_only"] == 1
    assert result["tied_both"] == 0
    assert result["discordant_pairs"] == [["b", "d"]]
    assert result["agreement_rate"] == pytest.approx(0.75)


def test_rank_permutation_test_is_exact_for_small_model_counts():
    result = rank_permutation_test([1, 2, 3, 4], [1, 2, 3, 4])
    assert result["method"] == "exact"
    assert result["draws"] == 24
    # Only the identity and the full reversal reach |tau| = 1.
    assert result["tau_b_p_value"] == pytest.approx(2 / 24)


# --- bootstrap behaviour ---------------------------------------------------


def test_cluster_bootstrap_widens_when_clusters_are_homogeneous():
    rows = _homogeneous_rows()
    keys, sources = cluster_keys_for_rows(rows)
    assert sources == {"signature": 200}
    values, is_binary = metric_column(rows, "execution_accuracy")
    assert is_binary
    interval = cluster_bootstrap_interval(values, keys, iterations=1000, seed=7)
    assert interval["n"] == 200
    assert interval["n_clusters"] == 10
    assert interval["point"] == pytest.approx(0.5)
    assert interval["cluster"]["width"] > 2.5 * interval["row"]["width"]
    assert interval["design_effect"] > 10
    assert interval["effective_n"] < 20


def test_cluster_bootstrap_matches_row_bootstrap_for_singleton_clusters():
    rows = [_row(i, i, i % 3 == 0) for i in range(60)]
    keys, _ = cluster_keys_for_rows(rows)
    values, _ = metric_column(rows, "execution_accuracy")
    interval = cluster_bootstrap_interval(values, keys, iterations=500, seed=3)
    assert interval["n_clusters"] == 60
    assert interval["cluster"]["lower"] == pytest.approx(interval["row"]["lower"], abs=0.05)
    assert interval["cluster"]["upper"] == pytest.approx(interval["row"]["upper"], abs=0.05)


def test_cluster_ci_report_is_deterministic_for_a_fixed_seed():
    run = EvaluationRun("model", _homogeneous_rows())
    first = analyze_cluster_ci(run, iterations=300, seed=11, group_by=("graph_profile",))
    second = analyze_cluster_ci(run, iterations=300, seed=11, group_by=("graph_profile",))
    assert first == second
    other = analyze_cluster_ci(run, iterations=300, seed=12)
    assert (
        other["metrics"]["execution_accuracy"]["cluster"]
        != first["metrics"]["execution_accuracy"]["cluster"]
    )
    assert first["n_clusters"] == 10
    assert any("only 10 clusters" in warning for warning in first["warnings"])


def test_stratified_cluster_bootstrap_nests_clusters_in_strata():
    rows = _homogeneous_rows()
    report = analyze_cluster_ci(
        EvaluationRun("m", rows), iterations=200, stratify_by="graph_profile"
    )
    interval = report["metrics"]["execution_accuracy"]
    assert interval["n_strata"] == 2
    # Every finbench cluster is correct and every snb cluster wrong, so
    # stratified resampling has zero variance.
    assert interval["cluster"]["width"] == pytest.approx(0.0)


def test_signature_fallbacks_and_benchmark_consistency():
    rows = [_row(1, 1, True), _row(2, 1, False)]
    rows.append({**_row(3, 2, True), "gold_cypher": "", "template": "Which {x}?"})
    rows.append({**_row(4, 3, True), "gold_cypher": ""})
    keys, sources = cluster_keys_for_rows(rows)
    assert keys[0] == keys[1]
    assert sources == {"row": 1, "signature": 2, "template": 1}

    bench = {row["id"]: {"id": row["id"], "cypher": row["gold_cypher"]} for row in rows[:2]}
    keys_b, _ = cluster_keys_for_rows(rows[:2], benchmark_index=bench)
    assert keys_b == keys[:2]
    with pytest.raises(EvaluationInputError, match="not found in benchmark"):
        cluster_keys_for_rows(rows[:3], benchmark_index=bench)
    bench[rows[0]["id"]] = {"id": rows[0]["id"], "cypher": "MATCH (x:Other) RETURN x"}
    with pytest.raises(EvaluationInputError, match="differs from the benchmark"):
        cluster_keys_for_rows(rows[:2], benchmark_index=bench)


def test_metric_column_refuses_partial_metrics():
    rows = [_row(1, 1, True), _row(2, 1, False)]
    del rows[1]["projected_execution_accuracy"]
    with pytest.raises(EvaluationInputError, match="refusing to impute"):
        metric_column(rows, "projected_execution_accuracy")
    with pytest.raises(MetricUnavailableError):
        metric_column(rows, "no_such_metric")


# --- paired comparison -----------------------------------------------------


def test_paired_comparison_counts_discordant_items_and_tests_clusters():
    rows_a = _homogeneous_rows(n_clusters=6, size=5)
    rows_b = [dict(row) for row in rows_a]
    flipped = 0
    for row in rows_b:
        if not row["execution_accuracy"]:
            row["execution_accuracy"] = True
            row["answer_f1"] = 1.0
            flipped += 1
    rows_b[0] = {**rows_b[0], "execution_accuracy": False, "answer_f1": 0.0}
    report = analyze_paired(
        EvaluationRun("zero", rows_a),
        EvaluationRun("few", list(reversed(rows_b))),
        metrics=("execution_accuracy", "answer_f1"),
        iterations=300,
    )
    strict = report["metrics"]["execution_accuracy"]
    assert strict["mcnemar"]["a_wrong_b_correct"] == flipped == 15
    assert strict["mcnemar"]["a_correct_b_wrong"] == 1
    assert strict["mcnemar"]["p_value"] == pytest.approx(mcnemar_exact(1, 15))
    assert strict["difference"] == pytest.approx(14 / 30)
    assert strict["cluster_sign_flip"]["method"] == "exact"
    assert strict["cluster_sign_flip"]["informative_clusters"] == 4
    # Four informative clusters cannot give p below 2 / 2^4 even though
    # McNemar on 16 discordant items is highly significant.
    assert strict["cluster_sign_flip"]["p_value"] >= 2 / 16
    assert strict["mcnemar"]["p_value"] < 0.001
    assert "mcnemar" not in report["metrics"]["answer_f1"]
    assert "Paired Comparison" in render_markdown(report)
    assert r"\toprule" in render_latex(report)


def test_paired_comparison_fails_on_mismatched_ids():
    rows_a = _homogeneous_rows(n_clusters=4, size=5)
    rows_b = [dict(row) for row in rows_a[:-1]] + [_row(9999, 0, True)]
    with pytest.raises(EvaluationInputError, match="item ids differ"):
        analyze_paired(EvaluationRun("a", rows_a), EvaluationRun("b", rows_b), iterations=50)


def test_paired_comparison_fails_on_different_gold_cypher():
    rows_a = _homogeneous_rows(n_clusters=4, size=5)
    rows_b = [dict(row) for row in rows_a]
    rows_b[3]["gold_cypher"] = "MATCH (z:Different) RETURN z"
    with pytest.raises(EvaluationInputError, match="different splits"):
        analyze_paired(EvaluationRun("a", rows_a), EvaluationRun("b", rows_b), iterations=50)


def test_paired_comparison_fails_when_prediction_failures_exceed_one_percent():
    rows_a = _homogeneous_rows(n_clusters=10, size=10)
    rows_b = [dict(row) for row in rows_a]
    for row in rows_b[:2]:
        row["prediction_failed"] = True
    with pytest.raises(EvaluationInputError, match="prediction failure rate 0.020"):
        analyze_paired(EvaluationRun("a", rows_a), EvaluationRun("b", rows_b), iterations=50)
    # Legacy rows: derived from prediction_error with empty Cypher.
    legacy = [{k: v for k, v in row.items() if k != "prediction_failed"} for row in rows_a]
    for row in legacy[:2]:
        row.update({"prediction_error": "HTTP 404", "predicted_cypher": ""})
    with pytest.raises(EvaluationInputError, match="infrastructure errors"):
        analyze_paired(EvaluationRun("a", rows_a), EvaluationRun("legacy", legacy), iterations=50)


def test_cluster_sign_flip_uses_cluster_sums():
    keys = ["a"] * 5 + ["b"] * 5 + ["c"] * 5
    result = cluster_sign_flip_test([1.0] * 15, keys)
    assert result["method"] == "exact"
    assert result["p_value"] == pytest.approx(2 / 8)
    assert cluster_sign_flip_test([0.0] * 15, keys)["p_value"] == 1.0


# --- multi-model summary ---------------------------------------------------


def test_models_summary_reports_median_iqr_and_threshold_counts():
    runs = []
    for label, rate in (("m1", 0.0), ("m2", 0.1), ("m3", 0.3), ("m4", 0.9)):
        rows = _rows_with_rates(rate)
        if label == "m4":
            for row in rows:
                del row["projected_execution_accuracy"]
                del row["governance_valid"]
        runs.append(EvaluationRun(label, rows))
    report = analyze_models(runs, iterations=200, thresholds=(0.05, 0.5))
    across = report["across_models"]["execution_accuracy"]
    assert across["median"] == pytest.approx(0.2)
    assert across["q1"] == pytest.approx(0.075)
    assert across["q3"] == pytest.approx(0.45)
    assert across["mean"] == pytest.approx(0.325)
    assert report["across_models"]["projected_execution_accuracy"]["n_models"] == 3
    counts = report["threshold_counts"]["execution_accuracy"]
    assert counts["0.05"]["point_above"] == 3
    assert counts["0.5"]["point_above"] == 1
    assert counts["0.5"]["cluster_ci_lower_above"] == 1
    m4 = next(m for m in report["models"] if m["label"] == "m4")
    assert m4["metrics"]["governance_valid"] is None
    assert "--" in render_markdown(report)
    assert "Median [IQR]" in render_latex(report)


def test_models_summary_rejects_invalid_runs_unless_excluded():
    good = EvaluationRun("good", _rows_with_rates(0.5))
    bad_rows = _rows_with_rates(0.5)
    for row in bad_rows[:5]:
        row["prediction_failed"] = True
    bad = EvaluationRun("bad", bad_rows)
    with pytest.raises(EvaluationInputError):
        analyze_models([good, bad], iterations=50)
    report = analyze_models([good, bad], iterations=50, exclude_invalid=True)
    assert report["n_models"] == 1
    assert report["excluded_runs"][0]["label"] == "bad"


# --- ranking agreement and self-preference --------------------------------


def test_rank_agreement_perfect_and_reversed_orders():
    rates = (0.1, 0.3, 0.5, 0.7)
    runs_a = [EvaluationRun(f"m{i}", _rows_with_rates(r)) for i, r in enumerate(rates)]
    runs_b = [
        EvaluationRun(f"m{i}", _rows_with_rates(r, offset=5000, cluster_offset=100))
        for i, r in enumerate(rates)
    ]
    report = analyze_rank_agreement(runs_a, runs_b, name_a="PIPE", name_b="Curated", iterations=200)
    entry = report["metrics"]["execution_accuracy"]
    assert entry["kendall_tau_b"] == pytest.approx(1.0)
    assert entry["spearman_rho"] == pytest.approx(1.0)
    assert entry["kendall_tau_b_p_value"] == pytest.approx(2 / 24)
    assert entry["pairwise"]["concordant"] == 6
    # Every cluster has the same within-cluster rate, so resampling cannot
    # reorder models.
    assert entry["kendall_tau_b_ci"]["lower"] == pytest.approx(1.0)

    reversed_b = [
        EvaluationRun(f"m{i}", _rows_with_rates(r, offset=5000, cluster_offset=100))
        for i, r in enumerate(reversed(rates))
    ]
    reversed_report = analyze_rank_agreement(runs_a, reversed_b, iterations=100)
    assert reversed_report["metrics"]["execution_accuracy"]["kendall_tau_b"] == pytest.approx(-1.0)

    with pytest.raises(EvaluationInputError, match="model labels differ"):
        analyze_rank_agreement(runs_a, runs_b[:3] + [EvaluationRun("zz", runs_b[3].rows)])


def _self_preference_runs(self_own, self_other, others=(0.4, 0.4, 0.4), other_slice=0.5):
    own = [EvaluationRun("qwen", _rows_with_rates(self_own))]
    other = [EvaluationRun("qwen", _rows_with_rates(self_other, offset=5000, cluster_offset=100))]
    for i, rate in enumerate(others):
        own.append(EvaluationRun(f"m{i}", _rows_with_rates(rate)))
        other.append(
            EvaluationRun(f"m{i}", _rows_with_rates(other_slice, offset=5000, cluster_offset=100))
        )
    return own, other


def test_self_preference_sign_on_synthetic_case():
    own, other = _self_preference_runs(self_own=0.8, self_other=0.5)
    report = analyze_self_preference(own, other, self_model="qwen", iterations=300)
    did = report["estimates"]["difference_in_differences"]
    assert did["point"] == pytest.approx((0.8 - 0.4) - (0.5 - 0.5))
    assert did["lower"] > 0
    assert report["estimates"]["self_advantage_own_slice"]["point"] == pytest.approx(0.4)
    assert report["placebo"]["one_sided_p_value"] == pytest.approx(1 / 4)
    self_row = next(m for m in report["per_model"] if m["is_self"])
    assert self_row["delta"]["point"] == pytest.approx(0.3)

    own_r, other_r = _self_preference_runs(self_own=0.2, self_other=0.5)
    reversed_report = analyze_self_preference(own_r, other_r, self_model="qwen", iterations=300)
    assert reversed_report["estimates"]["difference_in_differences"]["point"] < 0
    assert reversed_report["estimates"]["difference_in_differences"]["upper"] < 0
    assert r"\textbf{qwen}" in render_latex(report)

    with pytest.raises(EvaluationInputError, match="self model"):
        analyze_self_preference(own, other, self_model="missing", iterations=50)


# --- CLI -------------------------------------------------------------------


def _write_jsonl(path: Path, rows) -> str:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return str(path)


def test_cli_subcommands_write_json_markdown_and_latex(tmp_path):
    rows = _homogeneous_rows(n_clusters=6, size=5)
    bench = _write_jsonl(
        tmp_path / "bench.jsonl", [{"id": r["id"], "cypher": r["gold_cypher"]} for r in rows]
    )
    a = _write_jsonl(tmp_path / "a.jsonl", rows)
    b = _write_jsonl(tmp_path / "b.jsonl", [{**r, "execution_accuracy": True} for r in rows])
    c = _write_jsonl(tmp_path / "c.jsonl", _rows_with_rates(0.4, n_clusters=6, size=5))
    out = tmp_path / "out"
    common = ["--output-dir", str(out), "--iterations", "100"]
    assert stats_main(["cluster-ci", "--evaluation", f"m={a}", "--benchmark", bench, *common]) == 0
    assert (
        stats_main(["paired", "--a", f"zero={a}", "--b", f"few={b}", "--benchmark", bench, *common])
        == 0
    )
    assert (
        stats_main(
            [
                "models",
                "--evaluation",
                f"m1={a}",
                "--label",
                f"m2={b}",
                "--evaluation",
                f"m3={c}",
                *common,
            ]
        )
        == 0
    )
    assert (
        stats_main(
            [
                "rank-agreement",
                "--a",
                f"m1={a}",
                "--a",
                f"m2={b}",
                "--a",
                f"m3={c}",
                "--b",
                f"m1={a}",
                "--b",
                f"m2={b}",
                "--b",
                f"m3={c}",
                *common,
            ]
        )
        == 0
    )
    assert (
        stats_main(
            [
                "self-preference",
                "--g1",
                f"m1={a}",
                "--g1",
                f"m2={b}",
                "--g2",
                f"m1={c}",
                "--g2",
                f"m2={c}",
                "--self-model",
                "m1",
                *common,
            ]
        )
        == 0
    )
    for stem in ("cluster_ci", "paired", "models", "rank_agreement", "self_preference"):
        report = json.loads((out / f"{stem}.json").read_text(encoding="utf-8"))
        assert report["command"]["subcommand"] == stem.replace("_", "-")
        assert (out / f"{stem}.md").read_text(encoding="utf-8").startswith("# ")
        tex = (out / f"{stem}.tex").read_text(encoding="utf-8")
        assert r"\toprule" in tex and r"\bottomrule" in tex and r"\label{" in tex

    mismatched = _write_jsonl(tmp_path / "mismatch.jsonl", rows[:-1])
    assert stats_main(["paired", "--a", f"a={a}", "--b", f"b={mismatched}", *common]) == 2
