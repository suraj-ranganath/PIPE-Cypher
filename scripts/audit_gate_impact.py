#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.gate_impact import summarize_gate_impact
from pipecypher.governance_audit import load_jsonl
from pipecypher.paper_tables import render_gate_impact_table


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize counterfactual gate impact.")
    parser.add_argument("--records", nargs="+", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-tex", default="")
    args = parser.parse_args()

    summary = summarize_gate_impact(load_jsonl(args.records))
    out = Path(args.output_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    if args.output_tex:
        tex = Path(args.output_tex)
        tex.parent.mkdir(parents=True, exist_ok=True)
        tex.write_text(render_gate_impact_table(summary), encoding="utf-8")
        print(f"wrote {tex}")


if __name__ == "__main__":
    main()
