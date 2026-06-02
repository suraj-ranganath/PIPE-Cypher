from __future__ import annotations

import json
import math
from pathlib import Path

from pipecypher.text_metrics import (
    compute_text_pair_metrics,
    jaro_winkler_similarity,
    meteor_score,
    normalize_answer,
    rouge_l,
    sentence_bleu,
    tokenize,
)
from scripts.evaluate_text_metrics import main as evaluate_text_metrics_main


def test_compute_text_pair_metrics_reports_requested_metric_family():
    metrics = compute_text_pair_metrics(
        "Account A sent 10 transfers",
        "Account A sent 10 transfers",
    )

    assert metrics["exact_match"] == 1.0
    assert metrics["normalized_exact_match"] == 1.0
    assert metrics["rouge1_f1"] == 1.0
    assert metrics["rouge2_f1"] == 1.0
    assert metrics["rougeL_f1"] == 1.0
    assert metrics["bleu"] == 1.0
    assert metrics["meteor"] > 0.99
    assert math.isclose(metrics["cosine"], 1.0)
    assert metrics["jaro_winkler"] == 1.0
    assert "bertscore_status" in metrics
    assert "frugalscore_status" in metrics


def test_text_metrics_capture_partial_overlap():
    metrics = compute_text_pair_metrics(
        "account sent transfers",
        "account received transfers",
    )

    assert 0 < metrics["rouge1_f1"] < 1
    assert metrics["rouge2_f1"] == 0
    assert 0 < metrics["cosine"] < 1
    assert metrics["exact_match"] == 0


def test_metric_helpers_match_known_behavior():
    assert normalize_answer("The Account!") == "account"
    assert rouge_l(tokenize("a b c"), tokenize("a x c"))["f1"] == 2 / 3
    assert sentence_bleu(tokenize("a b c"), tokenize("a b c")) == 1.0
    assert meteor_score(tokenize("a b c"), tokenize("a b c")) > 0.98
    assert round(jaro_winkler_similarity("martha", "marhta"), 3) == 0.961


def test_evaluate_text_metrics_cli(tmp_path: Path):
    source = tmp_path / "rows.jsonl"
    output = tmp_path / "metrics.jsonl"
    summary = tmp_path / "summary.json"
    source.write_text(
        json.dumps({"id": "1", "prediction": "a b c", "reference": "a b c"}) + "\n"
        + json.dumps({"id": "2", "prediction": "a b", "reference": "x y"}) + "\n",
        encoding="utf-8",
    )

    assert (
        evaluate_text_metrics_main(
            [
                "--input",
                str(source),
                "--output",
                str(output),
                "--summary-output",
                str(summary),
            ]
        )
        == 0
    )

    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    payload = json.loads(summary.read_text(encoding="utf-8"))
    assert rows[0]["exact_match"] == 1.0
    assert payload["n"] == 2
    assert payload["exact_match"] == 0.5
