#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.paper_evidence_audit import (
    APPROVED_PAPER_MODELS,
    CLEAN_BENCHMARK_DIR,
    CLEAN_DOWNSTREAM_MANIFEST,
    CLEAN_EVIDENCE_MANIFEST,
    format_paper_evidence_audit,
    run_paper_evidence_audit,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Audit final paper evidence provenance: manuscript-facing text, "
            "clean benchmark export, generation/judge manifest, and downstream "
            "control readiness."
        )
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--benchmark-dir", default=str(CLEAN_BENCHMARK_DIR))
    parser.add_argument("--evidence-manifest", default=str(CLEAN_EVIDENCE_MANIFEST))
    parser.add_argument("--downstream-manifest", default=str(CLEAN_DOWNSTREAM_MANIFEST))
    parser.add_argument("--approved-model", action="append", default=[])
    parser.add_argument("--expected-total", type=int, default=3000)
    parser.add_argument("--expected-model-records", type=int, default=4925)
    parser.add_argument("--expected-downstream-zero-runs", type=int, default=11)
    parser.add_argument("--expected-downstream-control-runs", type=int, default=45)
    parser.add_argument("--expected-downstream-rows", type=int, default=296)
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args()

    report = run_paper_evidence_audit(
        root=Path(args.root),
        benchmark_dir=Path(args.benchmark_dir),
        evidence_manifest=Path(args.evidence_manifest),
        downstream_manifest=Path(args.downstream_manifest),
        expected_total=args.expected_total,
        expected_model_records=args.expected_model_records,
        expected_downstream_zero_runs=args.expected_downstream_zero_runs,
        expected_downstream_control_runs=args.expected_downstream_control_runs,
        expected_downstream_rows=args.expected_downstream_rows,
        approved_models=set(args.approved_model or APPROVED_PAPER_MODELS),
    )
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_paper_evidence_audit(report))
    if not report["pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
