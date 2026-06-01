from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from scripts.fill_missing_categories import (
    accepted_by_category,
    fill_run_name,
    latest_run_dir,
    missing_by_category,
    patched_config_for_category,
)
from scripts.run_pipeline import load_seen_question_keys


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_accepted_by_category_reads_run_dirs_and_records_files(tmp_path: Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_jsonl(
        run_dir / "records.jsonl",
        [
            {
                "graph_profile": "finbench",
                "category": "simple_retrieval",
                "question": "Which accounts are owned by person 'A'?",
                "accepted": True,
            },
            {
                "graph_profile": "finbench",
                "category": "simple_retrieval",
                "question": "Which accounts are owned by person 'A'?",
                "accepted": True,
            },
            {
                "graph_profile": "finbench",
                "category": "simple_retrieval",
                "question": "Which accounts are owned by person 'B'?",
                "accepted": False,
            },
        ],
    )
    records_path = tmp_path / "extra.jsonl"
    _write_jsonl(
        records_path,
        [
            {
                "graph_profile": "finbench",
                "category": "ranking_topk",
                "question": "Which account sent the highest total transfer amount?",
                "accepted": True,
            }
        ],
    )

    counts = accepted_by_category([str(run_dir), str(records_path)])

    assert counts == Counter({"simple_retrieval": 1, "ranking_topk": 1})


def test_load_seen_question_keys_reads_accepted_questions(tmp_path: Path):
    records_path = tmp_path / "records.jsonl"
    _write_jsonl(
        records_path,
        [
            {"category": "ranking_topk", "question": "Which account ranked first?", "accepted": True},
            {"category": "ranking_topk", "question": "Which account ranked last?", "accepted": False},
        ],
    )

    keys = load_seen_question_keys([str(records_path)])

    assert keys == {("ranking_topk", "which account ranked first?")}


def test_missing_by_category_reports_only_underfilled_categories():
    counts = Counter({"simple_retrieval": 3, "ranking_topk": 1})

    missing = missing_by_category(
        counts=counts,
        categories=["simple_retrieval", "ranking_topk", "path_temporal"],
        target_per_category=2,
    )

    assert missing == {"ranking_topk": 1, "path_temporal": 2}


def test_patched_config_for_category_preserves_base_config():
    base = {
        "models": {"generation_model": "Qwen/Qwen3.5-9B"},
        "generation": {
            "graph_profile": "finbench",
            "categories": ["simple_retrieval", "ranking_topk"],
            "target_per_category": 250,
        },
    }

    patched = patched_config_for_category(base, category="ranking_topk", target=7)

    assert patched["models"] == base["models"]
    assert patched["generation"]["graph_profile"] == "finbench"
    assert patched["generation"]["categories"] == ["ranking_topk"]
    assert patched["generation"]["target_per_category"] == 7
    assert base["generation"]["target_per_category"] == 250


def test_fill_run_name_keeps_first_pass_compatible():
    assert fill_run_name("fill", category="ranking_topk", pass_idx=1) == "fill_ranking_topk"
    assert fill_run_name("fill", category="ranking_topk", pass_idx=2) == "fill_pass2_ranking_topk"


def test_latest_run_dir_finds_timestamped_output(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    older = runs_dir / "20260601_010101_fill_ranking_topk"
    newer = runs_dir / "20260601_020202_fill_ranking_topk"
    older.mkdir(parents=True)
    newer.mkdir()

    assert latest_run_dir(runs_dir, "fill_ranking_topk") == newer
