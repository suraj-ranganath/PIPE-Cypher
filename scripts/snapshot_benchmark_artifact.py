#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.artifact_snapshot import build_artifact_snapshot


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a tracked manifest/sample snapshot for an ignored benchmark export"
    )
    parser.add_argument("--export-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--source-export-dir",
        help="Stable display path to record in the snapshot manifest. Defaults to --export-dir.",
    )
    parser.add_argument("--sample-per-graph-category", type=int, default=1)
    args = parser.parse_args()

    snapshot = build_artifact_snapshot(
        export_dir=args.export_dir,
        output_dir=args.output_dir,
        source_export_dir=args.source_export_dir,
        sample_per_graph_category=args.sample_per_graph_category,
    )
    print(json.dumps(snapshot, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
