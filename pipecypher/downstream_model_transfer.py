from __future__ import annotations

import json
from pathlib import Path
from typing import Any


METRICS = (
    "execution_accuracy",
    "answer_f1",
    "execution_success",
    "parse_valid",
    "schema_valid",
)


def build_model_transfer_report(
    run_dirs: list[Path], metadata: dict[str, dict[str, Any]] | None = None
) -> dict[str, Any]:
    metadata = metadata or {}
    runs = [summarize_model_transfer_run(path, metadata.get(path.name, {})) for path in run_dirs]
    complete = [run for run in runs if run["complete"]]
    return {
        "runs_examined": len(runs),
        "complete_count": len(complete),
        "incomplete_count": len(runs) - len(complete),
        "complete_runs": complete,
        "incomplete_runs": [run for run in runs if not run["complete"]],
        "best_zero_shot_exec_accuracy": _best_run(complete, "zero_shot", "execution_accuracy"),
        "best_few_shot_exec_accuracy": _best_run(complete, "few_shot", "execution_accuracy"),
    }


def summarize_model_transfer_run(run_dir: Path, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata = metadata or {}
    zero_summary = run_dir / "zero_shot_summary.json"
    few_summary = run_dir / "few_shot_summary.json"
    missing = [
        path.name for path in (zero_summary, few_summary) if not path.exists()
    ]
    run = {
        "run_id": run_dir.name,
        "path": str(run_dir),
        "model": metadata.get("model", _infer_model_name(run_dir.name)),
        "model_family": metadata.get("model_family", "unspecified"),
        "tuning": metadata.get("tuning", "unspecified"),
        "local_weights": bool(metadata.get("local_weights", True)),
        "complete": not missing,
        "missing": missing,
        "zero_shot": {},
        "few_shot": {},
    }
    if zero_summary.exists():
        run["zero_shot"] = _extract_overall_metrics(_read_json(zero_summary))
    if few_summary.exists():
        run["few_shot"] = _extract_overall_metrics(_read_json(few_summary))
    return run


def render_model_transfer_markdown(report: dict[str, Any]) -> str:
    rows = [
        "# Downstream Model Transfer Summary",
        "",
        f"Complete runs: {report['complete_count']} / {report['runs_examined']}",
        "",
        "| Model | Family | Tuning | Zero exec. acc. | Few-shot exec. acc. | Delta | Zero schema | Few schema |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for run in report["complete_runs"]:
        rows.append(_markdown_row(run))
    if report["incomplete_runs"]:
        rows.extend(["", "## Incomplete Runs", ""])
        for run in report["incomplete_runs"]:
            rows.append(
                f"- {run['model']} (`{run['run_id']}`) missing: {', '.join(run['missing'])}"
            )
    rows.append("")
    return "\n".join(rows)


def render_model_transfer_latex(report: dict[str, Any]) -> str:
    rows = [
        r"\begin{table*}[t]",
        r"\centering",
        r"\small",
        r"\resizebox{\textwidth}{!}{%",
        r"\begin{tabular}{llrrrr}",
        r"\toprule",
        r"Model & Tuning & Zero acc. & Few-shot acc. & $\Delta$ & Few schema \\",
        r"\midrule",
    ]
    for run in report["complete_runs"]:
        zero = run["zero_shot"]
        few = run["few_shot"]
        delta = few["execution_accuracy"] - zero["execution_accuracy"]
        rows.append(
            "{model} & {tuning} & {zero_acc} & {few_acc} & {delta} & {few_schema} \\\\".format(
                model=_escape_latex(run["model"]),
                tuning=_escape_latex(run["tuning"]),
                zero_acc=_fmt_float(zero["execution_accuracy"]),
                few_acc=_fmt_float(few["execution_accuracy"]),
                delta=_fmt_float(delta),
                few_schema=_fmt_float(few["schema_valid"]),
            )
        )
    rows.extend(
        [
            r"\bottomrule",
            r"\end{tabular}",
            r"}",
            (
                r"\caption{Local-model downstream Text2Cypher transfer stress test on the "
                r"same full held-out PIPE-Cypher test split. The table reports only runs "
                r"with completed zero-shot and retrieval few-shot summaries.}"
            ),
            r"\label{tab:downstream_model_transfer}",
            r"\end{table*}",
        ]
    )
    return "\n".join(rows) + "\n"


def _extract_overall_metrics(summary: dict[str, Any]) -> dict[str, Any]:
    overall = summary["overall"]
    extracted = {"n": int(overall["n"])}
    for metric in METRICS:
        extracted[metric] = float(overall[metric])
    return extracted


def _best_run(
    runs: list[dict[str, Any]], shot: str, metric: str
) -> dict[str, Any] | None:
    if not runs:
        return None
    run = max(runs, key=lambda item: item[shot][metric])
    return {
        "run_id": run["run_id"],
        "model": run["model"],
        metric: run[shot][metric],
    }


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _markdown_row(run: dict[str, Any]) -> str:
    zero = run["zero_shot"]
    few = run["few_shot"]
    delta = few["execution_accuracy"] - zero["execution_accuracy"]
    return (
        f"| {run['model']} | {run['model_family']} | {run['tuning']} | "
        f"{_fmt_float(zero['execution_accuracy'])} | {_fmt_float(few['execution_accuracy'])} | "
        f"{_fmt_float(delta)} | {_fmt_float(zero['schema_valid'])} | {_fmt_float(few['schema_valid'])} |"
    )


def _infer_model_name(run_id: str) -> str:
    name = run_id
    for prefix in ("20260602_downstream_", "20260603_downstream_"):
        if name.startswith(prefix):
            name = name[len(prefix) :]
    for suffix in ("_zero_fewshot", "_lora_zero_fewshot", "_transformers_zero_fewshot"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name.replace("_", "-")


def _fmt_float(value: float) -> str:
    return f"{value:.3f}"


def _escape_latex(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(ch, ch) for ch in value)
