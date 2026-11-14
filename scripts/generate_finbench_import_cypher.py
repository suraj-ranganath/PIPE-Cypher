#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.finbench_import import write_import_cypher


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Neo4j LOAD CSV script for LDBC FinBench snapshot files")
    parser.add_argument("--output", default="artifacts/import/finbench_load.cypher")
    parser.add_argument("--csv-base-url", default="file:///finbench/snapshot")
    parser.add_argument("--extension", default="csv")
    args = parser.parse_args()
    write_import_cypher(args.output, args.csv_base_url, args.extension)
    print(f"wrote={args.output}")


if __name__ == "__main__":
    main()

