#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.paper_tables import (
    render_benchmark_export_table,
    render_downstream_table,
    render_full_artifact_distribution_table,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render LaTeX paper tables from exported benchmark/evaluation artifacts."
    )
    parser.add_argument(
        "--benchmark-dir",
        default="artifacts/benchmarks/20260601_live_full_qwen9b",
    )
    parser.add_argument(
        "--evaluation-summary",
        default="artifacts/evaluations/20260601_full_qwen9b_test_summary.json",
    )
    parser.add_argument("--paper-dir", default="paper_emnlp2026_industry")
    args = parser.parse_args()

    benchmark_dir = Path(args.benchmark_dir)
    paper_dir = Path(args.paper_dir)
    stats = _read_json(benchmark_dir / "stats.json")
    manifest = _read_json(benchmark_dir / "manifest.json")
    evaluation = _read_json(args.evaluation_summary)

    outputs = {
        "tables_benchmark_export.tex": render_benchmark_export_table(stats, manifest),
        "tables_full_artifact_distribution.tex": render_full_artifact_distribution_table(stats),
        "tables_downstream_smoke.tex": render_downstream_table(evaluation),
    }
    paper_dir.mkdir(parents=True, exist_ok=True)
    for name, text in outputs.items():
        path = paper_dir / name
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path}")


def _read_json(path: str | Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
