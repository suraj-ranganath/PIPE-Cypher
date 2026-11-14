#!/usr/bin/env python3
"""Map checklist-audit rows (scripts/audit_checklist_judge.py) to export item ids.

Audit rows are keyed by graph|category|question|cypher of the run record; the
export keeps the same question and reference Cypher, so the key identifies the
exported item. Writes one verdict row per exported item that was audited:
``{"item_id", "passed", "failure_reason"}``, the format read by
pipecypher.human_validation.load_verdicts, and prints coverage.

Example:
  python scripts/audit_to_verdicts.py --export artifacts/benchmarks/naacl_v3_full \
      --audit artifacts/naacl_v3/audit/full_gpt6luna_checklist.jsonl \
      --output artifacts/naacl_v3/audit/full_gpt6luna_verdicts.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--export", required=True)
    parser.add_argument("--audit", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    audit = {}
    for line in Path(args.audit).open(encoding="utf-8"):
        if line.strip():
            row = json.loads(line)
            audit[row["key"]] = row
    exported = [json.loads(line) for line in (Path(args.export) / "all.jsonl").open(encoding="utf-8") if line.strip()]
    written = 0
    with Path(args.output).open("w", encoding="utf-8") as handle:
        for item in exported:
            key = f"{item.get('graph_profile')}|{item.get('category')}|{item.get('question')}|{item.get('cypher')}"
            row = audit.get(key)
            if row is None and item.get("question_normalization"):
                # The export may have normalized the question wording; the audit saw the original.
                before = item["question_normalization"].get("before")
                row = audit.get(f"{item.get('graph_profile')}|{item.get('category')}|{before}|{item.get('cypher')}")
            if row is None:
                continue
            handle.write(json.dumps({
                "item_id": item["id"],
                "passed": bool(row.get("auditor_passed")),
                "failure_reason": row.get("auditor_failure_reason") or "",
                "auditor": row.get("auditor"),
            }) + "\n")
            written += 1
    print(f"{written} of {len(exported)} exported items have an audit verdict -> {args.output}")


if __name__ == "__main__":
    main()
