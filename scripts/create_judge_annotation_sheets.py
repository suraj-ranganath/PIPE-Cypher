#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.judge_audit_packet import write_annotation_sheets


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create independent human-annotation sheets for a frozen judge audit CSV."
    )
    parser.add_argument("--audit", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--prefix", default="judge_audit")
    parser.add_argument(
        "--annotator",
        action="append",
        default=[],
        help="Annotator ID. Repeat for multiple annotators; defaults to annotator_a and annotator_b.",
    )
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument(
        "--blind-judge",
        action="store_true",
        help="Omit judge_accept from annotation and adjudication sheets.",
    )
    parser.add_argument("--manifest-json", default="")
    args = parser.parse_args()

    annotators = tuple(args.annotator or ["annotator_a", "annotator_b"])
    manifest = write_annotation_sheets(
        args.audit,
        args.output_dir,
        prefix=args.prefix,
        annotators=annotators,
        seed=args.seed,
        include_judge_accept=not args.blind_judge,
    )
    if args.manifest_json:
        output = Path(args.manifest_json)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {output}")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
