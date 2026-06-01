#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.capacity import estimate_seed_capacity
from pipecypher.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Estimate built-in seed-template capacity for a PIPE-Cypher config"
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--format", choices=["json", "markdown"], default="markdown")
    args = parser.parse_args()

    cfg = load_config(args.config)
    estimate = estimate_seed_capacity(
        profile=cfg.generation.graph_profile,
        categories=cfg.generation.categories,
        target_per_category=cfg.generation.target_per_category,
        binding_limit=cfg.generation.generated_query_limit,
    )
    if args.format == "json":
        print(json.dumps(estimate, indent=2, sort_keys=True))
        return
    print("| Category | Target | Seeds | Slotted | No-slot | Binding limit | Est. capacity | Meets |")
    print("|---|---:|---:|---:|---:|---:|---:|---|")
    for row in estimate["categories"]:
        print(
            "| {category} | {target} | {seed_templates} | {slotted_templates} | "
            "{no_slot_templates} | {binding_limit} | {estimated_capacity} | {meets} |".format(
                **row,
                meets="yes" if row["meets_target"] else "no",
            )
        )
    print(f"\nall_meet_target={str(estimate['all_meet_target']).lower()}")


if __name__ == "__main__":
    main()
