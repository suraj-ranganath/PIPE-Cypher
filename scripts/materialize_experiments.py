#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.experiments import (
    apply_variant,
    build_experiment_variants,
    dump_yaml,
    load_yaml,
    variant_applies_to_graph,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Materialize PIPE-Cypher experiment configs and commands")
    parser.add_argument("--matrix", default="configs/experiment_matrix.yaml")
    parser.add_argument("--base-config", default="configs/finbench_full.yaml")
    parser.add_argument("--output-dir", default="configs/generated")
    parser.add_argument("--target-per-category", type=int, default=0)
    args = parser.parse_args()

    matrix = load_yaml(args.matrix)
    base = load_yaml(args.base_config)
    graph_profile = str(base.get("generation", {}).get("graph_profile", ""))
    variants = [
        variant
        for variant in build_experiment_variants(matrix)
        if variant_applies_to_graph(variant, graph_profile)
    ]
    output_dir = Path(args.output_dir)
    command_lines = []
    for variant in variants:
        if args.target_per_category:
            variant["target_per_category"] = args.target_per_category
        cfg = apply_variant(base, variant)
        path = output_dir / f"{variant['name']}.yaml"
        dump_yaml(cfg, path)
        command_lines.append(
            f"python scripts/run_pipeline.py --config {path} --run-name {variant['name']}"
        )
    commands_path = output_dir / "run_commands.sh"
    commands_path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n\n" + "\n".join(command_lines) + "\n", encoding="utf-8")
    commands_path.chmod(0o755)
    print(f"wrote_configs={len(variants)} output_dir={output_dir}")
    print(f"commands={commands_path}")


if __name__ == "__main__":
    main()
