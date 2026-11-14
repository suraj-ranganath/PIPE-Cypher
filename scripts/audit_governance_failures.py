#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.governance_audit import (
    load_json,
    load_jsonl,
    merge_governance_audits,
    summarize_ablation_governance,
    summarize_downstream_governance,
    summarize_governance_records,
)
from pipecypher.paper_tables import render_governance_audit_table


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize Cypher governance failures across generation, ablation, and downstream artifacts."
    )
    parser.add_argument("--records", nargs="*", default=[])
    parser.add_argument("--ablation-summary", default="")
    parser.add_argument("--downstream-error-report", default="")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-tex", default="")
    args = parser.parse_args()

    generation = summarize_governance_records(load_jsonl(args.records)) if args.records else {}
    ablation = (
        summarize_ablation_governance(load_json(args.ablation_summary))
        if args.ablation_summary
        else {}
    )
    downstream = (
        summarize_downstream_governance(load_json(args.downstream_error_report))
        if args.downstream_error_report
        else {}
    )
    summary = merge_governance_audits(
        generation_records=generation,
        ablation=ablation,
        downstream=downstream,
    )

    out = Path(args.output_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out}")

    if args.output_tex:
        tex = Path(args.output_tex)
        tex.parent.mkdir(parents=True, exist_ok=True)
        tex.write_text(render_governance_audit_table(summary), encoding="utf-8")
        print(f"wrote {tex}")


if __name__ == "__main__":
    main()
