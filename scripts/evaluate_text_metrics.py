#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.io import read_jsonl, write_jsonl
from pipecypher.text_metrics import (
    DETERMINISTIC_TEXT_METRIC_KEYS,
    OPTIONAL_TEXT_METRIC_KEYS,
    compute_text_pair_metrics,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compute supplementary reference-based text metrics for JSONL rows"
    )
    parser.add_argument("--input", required=True, help="Input JSONL")
    parser.add_argument("--prediction-field", default="prediction")
    parser.add_argument("--reference-field", default="reference")
    parser.add_argument("--id-field", default="id")
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary-output", default="")
    parser.add_argument(
        "--optional-text-metrics",
        action="store_true",
        help="Also attempt optional BERTScore and FrugalScore integrations when installed",
    )
    args = parser.parse_args(argv)

    outputs = []
    for row in read_jsonl(args.input):
        if args.prediction_field not in row:
            raise SystemExit(f"missing prediction field {args.prediction_field!r}")
        if args.reference_field not in row:
            raise SystemExit(f"missing reference field {args.reference_field!r}")
        metrics = compute_text_pair_metrics(
            str(row.get(args.prediction_field, "")),
            str(row.get(args.reference_field, "")),
            include_optional=args.optional_text_metrics,
        )
        output = dict(metrics)
        if args.id_field in row:
            output[args.id_field] = row[args.id_field]
        outputs.append(output)

    write_jsonl(args.output, outputs)
    summary = summarize_text_metric_rows(outputs)
    if args.summary_output:
        out = Path(args.summary_output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "evaluated={n} exact_match={exact_match:.3f} rougeL_f1={rougeL_f1:.3f} "
        "bleu={bleu:.3f} meteor={meteor:.3f}".format(**summary)
    )
    return 0


def summarize_text_metric_rows(rows: list[dict[str, Any]]) -> dict[str, float | int]:
    summary: dict[str, float | int] = {"n": len(rows)}
    for key in [*DETERMINISTIC_TEXT_METRIC_KEYS, *OPTIONAL_TEXT_METRIC_KEYS]:
        values = [row.get(key) for row in rows if isinstance(row.get(key), int | float)]
        if values:
            summary[key] = sum(float(value) for value in values) / len(values)
    for key in DETERMINISTIC_TEXT_METRIC_KEYS:
        summary.setdefault(key, 0.0)
    return summary


if __name__ == "__main__":
    raise SystemExit(main())
