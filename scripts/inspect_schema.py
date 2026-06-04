#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.config import load_config
from pipecypher.cypher_client import Neo4jCypherClient
from pipecypher.graph_profiles import reference_schema
from pipecypher.schema import introspect_schema, save_schema


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect a Neo4j graph schema for PIPE-Cypher")
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", default="")
    parser.add_argument("--reference-only", action="store_true")
    parser.add_argument(
        "--categorical-max-values",
        type=int,
        default=None,
        help=(
            "Infer string properties with at most this many distinct values as categorical; "
            "use 0 to disable. Defaults to privacy.categorical_max_values from the config."
        ),
    )
    parser.add_argument(
        "--categorical-max-value-chars",
        type=int,
        default=None,
        help=(
            "Maximum string length allowed in schema categorical value samples. "
            "Defaults to privacy.categorical_max_value_chars from the config."
        ),
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    categorical_max_values = (
        args.categorical_max_values
        if args.categorical_max_values is not None
        else cfg.privacy.categorical_max_values
    )
    categorical_max_value_chars = (
        args.categorical_max_value_chars
        if args.categorical_max_value_chars is not None
        else cfg.privacy.categorical_max_value_chars
    )
    if args.reference_only:
        schema = reference_schema(cfg.generation.graph_profile)
    else:
        client = Neo4jCypherClient(
            cfg.neo4j.uri,
            cfg.neo4j.user,
            cfg.neo4j.password,
            database=cfg.neo4j.database,
            timeout_sec=cfg.neo4j.query_timeout_sec,
            enforce_read_transactions=cfg.neo4j.enforce_read_transactions,
        )
        schema = introspect_schema(
            client,
            graph_name=cfg.generation.graph_profile,
            categorical_max_values=categorical_max_values,
            categorical_max_value_chars=categorical_max_value_chars,
            categorical_omitted_properties=cfg.privacy.categorical_omitted_properties,
        )
        client.close()

    output = Path(args.output or cfg.paths.schema_path or f"configs/schema_{cfg.generation.graph_profile}.json")
    save_schema(schema, output)
    print(schema.to_prompt(max_items=80))
    print(f"\nSchema saved to {output}")


if __name__ == "__main__":
    main()
