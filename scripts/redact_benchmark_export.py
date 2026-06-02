#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.io import read_jsonl, write_jsonl
from pipecypher.privacy import PrivacyPolicy, redact_examples


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a value-redacted copy of a PIPE-Cypher benchmark export."
    )
    parser.add_argument("--input", required=True, help="Input JSONL file or benchmark export directory.")
    parser.add_argument("--output", required=True, help="Output JSONL file or directory.")
    parser.add_argument("--placeholder-prefix", default="VALUE")
    parser.add_argument("--hash-placeholders", action="store_true")
    parser.add_argument("--redact-numeric-literals", action="store_true")
    parser.add_argument(
        "--include-private-mapping",
        action="store_true",
        help="Include placeholder-to-raw-value maps. Do not use for externally shared artifacts.",
    )
    args = parser.parse_args()

    policy = PrivacyPolicy(
        placeholder_prefix=args.placeholder_prefix,
        hash_placeholders=args.hash_placeholders,
        redact_numeric_literals=args.redact_numeric_literals,
        include_private_mapping=args.include_private_mapping,
    )

    input_path = Path(args.input)
    output_path = Path(args.output)
    if input_path.is_dir():
        manifest = _redact_directory(input_path, output_path, policy=policy)
    else:
        manifest = _redact_jsonl(input_path, output_path, policy=policy)

    manifest_path = output_path / "privacy_manifest.json" if output_path.is_dir() else output_path.with_suffix(".privacy.json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {manifest_path}")


def _redact_directory(
    input_dir: Path,
    output_dir: Path,
    *,
    policy: PrivacyPolicy,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    files = [path for path in input_dir.glob("*.jsonl") if path.name in {"all.jsonl", "train.jsonl", "dev.jsonl", "test.jsonl"}]
    written = []
    for source in sorted(files):
        target = output_dir / source.name
        file_manifest = _redact_jsonl(source, target, policy=policy)
        written.append(file_manifest)
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input": str(input_dir),
        "output": str(output_dir),
        "files": written,
        "policy": _policy_manifest(policy),
    }


def _redact_jsonl(
    input_jsonl: Path,
    output_jsonl: Path,
    *,
    policy: PrivacyPolicy,
) -> dict[str, object]:
    rows = read_jsonl(input_jsonl)
    redacted = redact_examples(rows, policy=policy)
    write_jsonl(output_jsonl, redacted)
    return {
        "input": str(input_jsonl),
        "output": str(output_jsonl),
        "rows": len(redacted),
        "redacted": True,
    }


def _policy_manifest(policy: PrivacyPolicy) -> dict[str, object]:
    return {
        "redact_questions": policy.redact_questions,
        "redact_cypher_literals": policy.redact_cypher_literals,
        "redact_reverse_cypher": policy.redact_reverse_cypher,
        "redact_entity_values": policy.redact_entity_values,
        "redact_result_samples": policy.redact_result_samples,
        "redact_numeric_literals": policy.redact_numeric_literals,
        "hash_placeholders": policy.hash_placeholders,
        "placeholder_prefix": policy.placeholder_prefix,
        "include_private_mapping": policy.include_private_mapping,
    }


if __name__ == "__main__":
    main()
