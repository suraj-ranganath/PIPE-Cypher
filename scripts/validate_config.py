#!/usr/bin/env python3
"""Validate PIPE-Cypher run configs before launching long GPU jobs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipecypher.config import ConfigValidationError, load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("configs", nargs="+", help="Run YAML config file(s) to validate")
    parser.add_argument(
        "--check-paths",
        action="store_true",
        help="Also require schema_path and seed_examples_path to exist when configured",
    )
    args = parser.parse_args(argv)

    failures: list[str] = []
    for raw_path in args.configs:
        path = Path(raw_path)
        if not path.exists():
            failures.append(f"{path}: file does not exist")
            continue
        try:
            config = load_config(path, strict=True, validate=True, check_paths=args.check_paths)
        except (ConfigValidationError, ValueError) as exc:
            failures.append(f"{path}: {exc}")
            continue
        categories = ",".join(config.generation.categories)
        print(
            f"ok {path}: graph={config.generation.graph_profile} "
            f"target_per_category={config.generation.target_per_category} "
            f"categories={categories}"
        )

    if failures:
        for failure in failures:
            print(f"error {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
