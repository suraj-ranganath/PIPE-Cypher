#!/usr/bin/env python3
"""Cluster-aware significance and uncertainty for downstream Text2Cypher runs.

Subcommands (each writes <stem>.json, <stem>.md and <stem>.tex to --output-dir):

  cluster-ci       row-level vs signature-clustered bootstrap CIs for one run
  paired           exact McNemar + cluster sign-flip test + clustered paired delta
  models           per-model clustered CIs with median/IQR across models
  rank-agreement   Kendall tau-b / Spearman between model rankings on two benchmarks
  self-preference  generator self-preference difference-in-differences

Evaluation inputs are evaluation JSONL files written by
scripts/evaluate_benchmark_predictions.py, given as LABEL=PATH (or a bare path,
in which case the label is the rows' ``model`` field). Benchmark JSONL files or
package directories supply gold Cypher for query-signature clustering; without
them the evaluation rows' ``gold_cypher`` is used.

Examples:
  python scripts/analyze_downstream_statistics.py cluster-ci \
      --evaluation qwen=artifacts/evaluations/RUN/zero_shot_evaluation.jsonl \
      --benchmark artifacts/benchmarks/20260604_live_full_qwen9b_reviewfix/test.jsonl \
      --group-by graph_profile --output-dir OUT
  python scripts/analyze_downstream_statistics.py paired \
      --a zero_shot=RUN/zero_shot_evaluation.jsonl --b few_shot=RUN/few_shot_evaluation.jsonl \
      --benchmark BENCH/test.jsonl --output-dir OUT
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.downstream_model_transfer import MAX_PREDICTION_FAILURE_RATE
from pipecypher.eval_statistics import (
    CLUSTER_CI_METRICS,
    CLUSTER_MODES,
    DEFAULT_CONFIDENCE_LEVEL,
    DEFAULT_ITERATIONS,
    DEFAULT_PERMUTATION_ITERATIONS,
    DEFAULT_SEED,
    DEFAULT_THRESHOLDS,
    MODEL_SUMMARY_METRICS,
    PAIRED_METRICS,
    EvaluationInputError,
    analyze_cluster_ci,
    analyze_models,
    analyze_paired,
    analyze_rank_agreement,
    analyze_self_preference,
    load_benchmark_index,
    load_evaluation_run,
    render_latex,
    render_markdown,
    to_jsonable,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        report = _dispatch(args)
    except EvaluationInputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    report["command"] = {
        "subcommand": args.command,
        "argv": list(argv) if argv is not None else sys.argv[1:],
    }
    stem = args.stem or args.command.replace("-", "_")
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "json": out_dir / f"{stem}.json",
        "md": out_dir / f"{stem}.md",
        "tex": out_dir / f"{stem}.tex",
    }
    outputs["json"].write_text(
        json.dumps(to_jsonable(report), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    outputs["md"].write_text(render_markdown(report), encoding="utf-8")
    outputs["tex"].write_text(
        render_latex(report, caption=args.caption or None, label=args.table_label or None),
        encoding="utf-8",
    )
    for path in outputs.values():
        print(f"wrote {path}")
    for warning in report.get("warnings", []):
        print(f"warning: {warning}", file=sys.stderr)
    return 0


def _dispatch(args: argparse.Namespace) -> dict[str, Any]:
    common = {
        "cluster_by": args.cluster_by,
        "stratify_by": args.stratify_by or None,
        "iterations": args.iterations,
        "confidence_level": args.confidence_level,
        "seed": args.seed,
        "max_prediction_failure_rate": args.max_prediction_failure_rate,
    }
    if args.command == "cluster-ci":
        return analyze_cluster_ci(
            load_evaluation_run(args.evaluation),
            metrics=tuple(args.metrics or CLUSTER_CI_METRICS),
            require_metrics=bool(args.metrics),
            benchmark_index=_index(args.benchmark),
            group_by=tuple(args.group_by or ()),
            **common,
        )
    if args.command == "paired":
        return analyze_paired(
            load_evaluation_run(args.a),
            load_evaluation_run(args.b),
            metrics=tuple(args.metrics or PAIRED_METRICS),
            require_metrics=bool(args.metrics),
            benchmark_index=_index(args.benchmark),
            permutation_iterations=args.permutation_iterations,
            **common,
        )
    if args.command == "models":
        return analyze_models(
            [load_evaluation_run(spec) for spec in args.evaluations],
            metrics=tuple(args.metrics or MODEL_SUMMARY_METRICS),
            thresholds=tuple(args.thresholds or DEFAULT_THRESHOLDS),
            benchmark_index=_index(args.benchmark),
            exclude_invalid=args.exclude_invalid,
            require_same_ids=not args.allow_different_ids,
            **common,
        )
    if args.command == "rank-agreement":
        return analyze_rank_agreement(
            [load_evaluation_run(spec) for spec in args.a],
            [load_evaluation_run(spec) for spec in args.b],
            name_a=args.name_a,
            name_b=args.name_b,
            metrics=tuple(args.metrics or ("execution_accuracy",)),
            benchmark_index_a=_index(args.benchmark_a),
            benchmark_index_b=_index(args.benchmark_b),
            permutation_iterations=args.permutation_iterations,
            **common,
        )
    if args.command == "self-preference":
        return analyze_self_preference(
            [load_evaluation_run(spec) for spec in args.own],
            [load_evaluation_run(spec) for spec in args.other],
            self_model=args.self_model,
            name_own=args.name_own,
            name_other=args.name_other,
            metric=args.metric,
            benchmark_index_own=_index(args.benchmark_own),
            benchmark_index_other=_index(args.benchmark_other),
            **common,
        )
    raise EvaluationInputError(f"unknown subcommand {args.command}")


def _index(paths: Sequence[str] | None):
    return load_benchmark_index(paths) if paths else None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("\n\n", 1)[1],
    )
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--output-dir", required=True, help="Directory for <stem>.json/.md/.tex")
    shared.add_argument("--stem", default="", help="Output file stem; defaults to the subcommand")
    shared.add_argument(
        "--cluster-by",
        choices=CLUSTER_MODES,
        default="signature",
        help="signature (default), coarser template_family, or none (row bootstrap)",
    )
    shared.add_argument(
        "--stratify-by", default="", help="Row field for stratified resampling, e.g. graph_profile"
    )
    shared.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    shared.add_argument("--confidence-level", type=float, default=DEFAULT_CONFIDENCE_LEVEL)
    shared.add_argument("--seed", type=int, default=DEFAULT_SEED)
    shared.add_argument(
        "--max-prediction-failure-rate",
        type=float,
        default=MAX_PREDICTION_FAILURE_RATE,
        help="Fail when a run's request-failure rate exceeds this fraction",
    )
    shared.add_argument("--caption", default="", help="Override the LaTeX caption")
    shared.add_argument("--table-label", default="", help="Override the LaTeX \\label")

    sub = parser.add_subparsers(dest="command", required=True)

    cluster = sub.add_parser("cluster-ci", parents=[shared], help="Row vs clustered bootstrap CIs")
    cluster.add_argument(
        "--evaluation", "--label", dest="evaluation", required=True, help="LABEL=PATH or PATH"
    )
    cluster.add_argument(
        "--benchmark", action="append", help="Benchmark JSONL/package for signatures"
    )
    cluster.add_argument("--metric", action="append", dest="metrics")
    cluster.add_argument(
        "--group-by", action="append", help="Also report CIs per value of this field"
    )

    paired = sub.add_parser(
        "paired", parents=[shared], help="Paired comparison of two runs (B - A)"
    )
    paired.add_argument("--a", required=True, help="Baseline run, LABEL=PATH")
    paired.add_argument("--b", required=True, help="Comparison run, LABEL=PATH")
    paired.add_argument("--benchmark", action="append")
    paired.add_argument("--metric", action="append", dest="metrics")
    paired.add_argument(
        "--permutation-iterations", type=int, default=DEFAULT_PERMUTATION_ITERATIONS
    )

    models = sub.add_parser("models", parents=[shared], help="Multi-model clustered summary")
    models.add_argument(
        "--evaluation",
        "--label",
        dest="evaluations",
        action="append",
        required=True,
        help="Repeat once per model: LABEL=PATH",
    )
    models.add_argument("--benchmark", action="append")
    models.add_argument("--metric", action="append", dest="metrics")
    models.add_argument("--threshold", action="append", type=float, dest="thresholds")
    models.add_argument(
        "--exclude-invalid",
        action="store_true",
        help="Drop (and list) runs above the failure-rate limit instead of failing",
    )
    models.add_argument(
        "--allow-different-ids",
        action="store_true",
        help="Permit models scored on different item sets (not comparable; diagnostic only)",
    )

    rank = sub.add_parser(
        "rank-agreement", parents=[shared], help="Model-ranking agreement across two benchmarks"
    )
    rank.add_argument(
        "--a", action="append", required=True, help="Benchmark A run per model, LABEL=PATH"
    )
    rank.add_argument(
        "--b", action="append", required=True, help="Benchmark B run per model, LABEL=PATH"
    )
    rank.add_argument("--name-a", default="A")
    rank.add_argument("--name-b", default="B")
    rank.add_argument("--benchmark-a", action="append")
    rank.add_argument("--benchmark-b", action="append")
    rank.add_argument("--metric", action="append", dest="metrics")
    rank.add_argument("--permutation-iterations", type=int, default=DEFAULT_PERMUTATION_ITERATIONS)

    selfpref = sub.add_parser(
        "self-preference", parents=[shared], help="Generator self-preference DiD"
    )
    selfpref.add_argument(
        "--own",
        "--g1",
        dest="own",
        action="append",
        required=True,
        help="Run per model on the slice generated by the self model's generator, LABEL=PATH",
    )
    selfpref.add_argument(
        "--other",
        "--g2",
        dest="other",
        action="append",
        required=True,
        help="Run per model on the comparison generator's slice, LABEL=PATH",
    )
    selfpref.add_argument("--self-model", required=True, help="Label of the generator's own model")
    selfpref.add_argument("--name-own", "--name-g1", dest="name_own", default="G1")
    selfpref.add_argument("--name-other", "--name-g2", dest="name_other", default="G2")
    selfpref.add_argument(
        "--benchmark-own", "--benchmark-g1", dest="benchmark_own", action="append"
    )
    selfpref.add_argument(
        "--benchmark-other", "--benchmark-g2", dest="benchmark_other", action="append"
    )
    selfpref.add_argument("--metric", default="execution_accuracy")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
