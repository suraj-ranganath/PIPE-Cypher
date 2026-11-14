#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.io import read_jsonl
from pipecypher.paper_tables import render_redaction_audit_table
from pipecypher.privacy import PrivacyPolicy
from pipecypher.redaction_audit import RedactionAuditConfig, audit_redaction


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit redaction residuals for benchmark exports.")
    parser.add_argument("--benchmark", required=True, help="Input benchmark JSONL, usually all.jsonl.")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-tex", default="")
    parser.add_argument("--min-sensitive-chars", type=int, default=3)
    parser.add_argument("--include-numeric-literals", action="store_true")
    parser.add_argument("--hash-placeholders", action="store_true", default=True)
    parser.add_argument("--redact-numeric-literals", action="store_true")
    args = parser.parse_args()

    policy = PrivacyPolicy(
        hash_placeholders=args.hash_placeholders,
        redact_numeric_literals=args.redact_numeric_literals,
    )
    summary = audit_redaction(
        read_jsonl(args.benchmark),
        policy=policy,
        config=RedactionAuditConfig(
            min_sensitive_chars=args.min_sensitive_chars,
            include_numeric_literals=args.include_numeric_literals,
        ),
    )
    out = Path(args.output_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    if args.output_tex:
        tex = Path(args.output_tex)
        tex.parent.mkdir(parents=True, exist_ok=True)
        tex.write_text(render_redaction_audit_table(summary), encoding="utf-8")
        print(f"wrote {tex}")


if __name__ == "__main__":
    main()
