#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.judge_audit_packet import audit_packet_snapshot, render_audit_html
from pipecypher.paper_tables import render_judge_audit_coverage_table


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render a browser-reviewable HTML packet for judge calibration."
    )
    parser.add_argument("--audit", required=True)
    parser.add_argument("--output-html", required=True)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-tex", default="")
    parser.add_argument("--title", default="PIPE-Cypher Judge Audit")
    args = parser.parse_args()

    output_html = Path(args.output_html)
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_html.write_text(
        render_audit_html(args.audit, title=args.title),
        encoding="utf-8",
    )
    print(f"wrote {output_html}")

    if args.output_json:
        output_json = Path(args.output_json)
        output_json.parent.mkdir(parents=True, exist_ok=True)
        snapshot = audit_packet_snapshot(args.audit, html_path=output_html)
        output_json.write_text(
            json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {output_json}")
    if args.output_tex:
        output_tex = Path(args.output_tex)
        output_tex.parent.mkdir(parents=True, exist_ok=True)
        snapshot = audit_packet_snapshot(args.audit, html_path=output_html)
        output_tex.write_text(
            render_judge_audit_coverage_table(snapshot),
            encoding="utf-8",
        )
        print(f"wrote {output_tex}")


if __name__ == "__main__":
    main()
