from __future__ import annotations

import json
from pathlib import Path

from pipecypher.benchmark_card import render_benchmark_card
from scripts.render_benchmark_card import main as render_benchmark_card_main


def test_render_benchmark_card_includes_redacted_operational_metadata():
    card = render_benchmark_card(config_path="configs/local_smoke.yaml")

    assert "# PIPE-Cypher Benchmark Card" in card
    assert "Graph profile: `finbench`" in card
    assert "Schema fingerprint:" in card
    assert "Redact entity values: `True`" in card
    assert "Generated Cypher is treated as unsafe" in card


def test_render_benchmark_card_with_benchmark_export_summary(tmp_path):
    export_dir = tmp_path / "benchmark"
    export_dir.mkdir()
    (export_dir / "manifest.json").write_text(
        json.dumps(
            {
                "total_examples": 12,
                "split_counts": {"train": 8, "dev": 2, "test": 2},
                "sha256": "abc123",
            }
        ),
        encoding="utf-8",
    )
    (export_dir / "stats.json").write_text(
        json.dumps(
            {
                "total": 12,
                "by_graph": {"finbench": 8, "snb": 4},
                "by_category": {"simple_retrieval": 6, "ranking_topk": 6},
            }
        ),
        encoding="utf-8",
    )

    card = render_benchmark_card(
        config_path="configs/local_smoke.yaml",
        benchmark_dir=export_dir,
    )

    assert "## Export Summary" in card
    assert "Total examples: 12" in card
    assert "| finbench | 8 |" in card
    assert "| simple_retrieval | 6 |" in card


def test_render_benchmark_card_cli_writes_markdown(tmp_path):
    out = tmp_path / "card.md"

    assert render_benchmark_card_main(["--config", "configs/local_smoke.yaml", "--output", str(out)]) == 0

    assert out.exists()
    assert "PIPE-Cypher Benchmark Card" in out.read_text(encoding="utf-8")
