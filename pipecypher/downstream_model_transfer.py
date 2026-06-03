from __future__ import annotations

import json
import math
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


def build_fewshot_control_report(
    *,
    zero_shot_dirs: list[Path],
    control_dirs: list[Path],
    metadata: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    metadata = metadata or {}
    zero_by_slug: dict[str, Path] = {}
    zero_metadata: dict[str, dict[str, Any]] = {}
    for path in zero_shot_dirs:
        slug = _control_slug_from_zero_run(path.name)
        zero_by_slug[slug] = path
        zero_metadata[slug] = metadata.get(path.name, {})

    controls_by_slug: dict[str, dict[str, Path]] = {}
    for path in control_dirs:
        parsed = _parse_control_run_id(path.name)
        if not parsed:
            continue
        slug, mode_key = parsed
        controls_by_slug.setdefault(slug, {})[mode_key] = path

    model_reports = []
    for slug, zero_dir in sorted(zero_by_slug.items()):
        controls = controls_by_slug.get(slug, {})
        report = _summarize_control_model(
            slug=slug,
            zero_dir=zero_dir,
            control_dirs=controls,
            metadata=zero_metadata.get(slug, {}),
        )
        model_reports.append(report)

    complete_models = [
        item
        for item in model_reports
        if item["complete"]
    ]
    return {
        "models_examined": len(model_reports),
        "complete_model_count": len(complete_models),
        "incomplete_model_count": len(model_reports) - len(complete_models),
        "models": model_reports,
        "aggregate": _aggregate_control_models(complete_models),
    }


def summarize_model_transfer_run(run_dir: Path, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata = {**_read_json(run_dir / "metadata.json"), **(metadata or {})}
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
        "few_shot_mode": metadata.get("few_shot_mode", "ordered_same_category"),
        "few_shot_seed": metadata.get("few_shot_seed"),
        "few_shot_k": metadata.get("few_shot_k"),
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


def render_fewshot_control_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Downstream Few-Shot Control Summary",
        "",
        f"Complete models: {report['complete_model_count']} / {report['models_examined']}",
        "",
        "| Model | Tuning | Zero | Ordered | Scored no-sig | Random mean | Random std | Best control |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for model in report["models"]:
        lines.append(_control_markdown_row(model))
    aggregate = report.get("aggregate", {})
    if aggregate:
        lines.extend(
            [
                "",
                "## Aggregate",
                "",
                "| Metric | Value |",
                "|---|---:|",
                f"| Mean zero-shot exec. acc. | {_fmt_float(aggregate['mean_zero_execution_accuracy'])} |",
                f"| Mean ordered exec. acc. | {_fmt_float(aggregate['mean_ordered_execution_accuracy'])} |",
                f"| Mean scored no-signature exec. acc. | {_fmt_float(aggregate['mean_scored_execution_accuracy'])} |",
                f"| Mean random exec. acc. | {_fmt_float(aggregate['mean_random_execution_accuracy'])} |",
                f"| Models improved by ordered | {aggregate['ordered_improved_models']} / {aggregate['complete_models']} |",
                f"| Models improved by scored no-signature | {aggregate['scored_improved_models']} / {aggregate['complete_models']} |",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def render_fewshot_control_latex(report: dict[str, Any]) -> str:
    rows = [
        r"\begin{table*}[t]",
        r"\centering",
        r"\small",
        r"\resizebox{\textwidth}{!}{%",
        r"\begin{tabular}{llrrrrrr}",
        r"\toprule",
        r"Model & Tuning & Zero & Ordered & No-sig & Random $\mu$ & Random $\sigma$ & Best \\",
        r"\midrule",
    ]
    for model in report["models"]:
        zero = model["zero_shot"].get("execution_accuracy")
        ordered = _metric(model, "ordered", "execution_accuracy")
        scored = _metric(model, "scored_no_signature", "execution_accuracy")
        random_mean = model.get("random", {}).get("mean", {}).get("execution_accuracy")
        random_std = model.get("random", {}).get("std", {}).get("execution_accuracy")
        rows.append(
            "{model} & {tuning} & {zero} & {ordered} & {scored} & {random_mean} & {random_std} & {best_mode} \\\\".format(
                model=_escape_latex(str(model["model"])),
                tuning=_escape_latex(str(model["tuning"])),
                zero=_fmt_optional(zero),
                ordered=_fmt_optional(ordered),
                scored=_fmt_optional(scored),
                random_mean=_fmt_optional(random_mean),
                random_std=_fmt_optional(random_std),
                best_mode=_escape_latex(_format_best_control(model)),
            )
        )
    rows.extend(
        [
            r"\bottomrule",
            r"\end{tabular}",
            r"}",
            (
                r"\caption{Few-shot demonstration-bank controls for local downstream "
                r"Text2Cypher evaluation. Ordered uses the deterministic same-graph, "
                r"same-category example bank; scored excludes exact query-signature "
                r"matches and near-duplicate questions; random reports the mean and "
                r"standard deviation across seeds 13, 17, and 23. ``No gain'' means "
                r"no few-shot control exceeded that model's zero-shot execution accuracy.}"
            ),
            r"\label{tab:downstream_fewshot_controls}",
            r"\end{table*}",
        ]
    )
    return "\n".join(rows) + "\n"


def build_fewshot_control_uncertainty_report(
    report: dict[str, Any],
    *,
    iterations: int = 10000,
    seed: int = 13,
    confidence_level: float = 0.95,
) -> dict[str, Any]:
    if iterations <= 0:
        raise ValueError("iterations must be positive")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence_level must be between 0 and 1")

    models = [model for model in report.get("models", []) if model.get("complete")]
    rows = []
    for mode, label in (
        ("ordered", "Ordered same-category"),
        ("scored_no_signature", "Scored no-signature"),
        ("random_mean", "Random same-category mean"),
    ):
        values: list[float] = []
        deltas: list[float] = []
        improved = 0
        for model in models:
            zero = float(model["zero_shot"]["execution_accuracy"])
            value = _control_accuracy_for_uncertainty(model, mode)
            if value is None:
                continue
            value = float(value)
            values.append(value)
            delta = value - zero
            deltas.append(delta)
            if delta > 0.0:
                improved += 1
        interval = _bootstrap_mean_interval(
            deltas,
            iterations=iterations,
            seed=_derived_int_seed(seed, mode),
            confidence_level=confidence_level,
        )
        rows.append(
            {
                "mode": mode,
                "label": label,
                "models": len(deltas),
                "mean_accuracy": _mean(values),
                "mean_delta": _mean(deltas),
                "delta_ci_lower": interval["lower"],
                "delta_ci_upper": interval["upper"],
                "delta_standard_error": interval["standard_error"],
                "improved_models": improved,
            }
        )
    return {
        "method": "model_level_paired_bootstrap",
        "iterations": iterations,
        "seed": seed,
        "confidence_level": confidence_level,
        "zero_shot_mean_accuracy": report.get("aggregate", {}).get(
            "mean_zero_execution_accuracy", 0.0
        ),
        "rows": rows,
    }


def render_fewshot_control_uncertainty_markdown(report: dict[str, Any]) -> str:
    confidence = int(round(float(report.get("confidence_level", 0.95)) * 100))
    lines = [
        "# Few-Shot Control Uncertainty",
        "",
        (
            f"Method: model-level paired bootstrap over downstream checkpoints "
            f"with {report['iterations']:,} resamples and {confidence}% percentile intervals."
        ),
        "",
        f"Zero-shot mean execution accuracy: {_fmt_float(report['zero_shot_mean_accuracy'])}",
        "",
        "| Control | Mean acc. | Delta vs zero | Delta CI | Improved models |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in report["rows"]:
        lines.append(
            "| {label} | {mean_acc} | {delta} | [{lower}, {upper}] | {improved}/{models} |".format(
                label=row["label"],
                mean_acc=_fmt_float(row["mean_accuracy"]),
                delta=_fmt_float(row["mean_delta"]),
                lower=_fmt_float(row["delta_ci_lower"]),
                upper=_fmt_float(row["delta_ci_upper"]),
                improved=row["improved_models"],
                models=row["models"],
            )
        )
    lines.append("")
    return "\n".join(lines)


def render_fewshot_control_uncertainty_latex(report: dict[str, Any]) -> str:
    confidence = int(round(float(report.get("confidence_level", 0.95)) * 100))
    rows = [
        r"\begin{table}[t]",
        r"\centering",
        r"\small",
        r"\resizebox{\columnwidth}{!}{%",
        r"\begin{tabular}{lrrrr}",
        r"\toprule",
        f"Control & Mean acc. & $\\Delta$ vs zero & {confidence}\\% $\\Delta$ CI & Models improved \\\\",
        r"\midrule",
    ]
    for row in report["rows"]:
        rows.append(
            "{label} & {mean_acc} & {delta} & [{lower}, {upper}] & {improved}/{models} \\\\".format(
                label=_escape_latex(row["label"]),
                mean_acc=_fmt_float(row["mean_accuracy"]),
                delta=_fmt_float(row["mean_delta"]),
                lower=_fmt_float(row["delta_ci_lower"]),
                upper=_fmt_float(row["delta_ci_upper"]),
                improved=row["improved_models"],
                models=row["models"],
            )
        )
    rows.extend(
        [
            r"\bottomrule",
            r"\end{tabular}",
            r"}",
            (
                r"\caption{Model-level paired bootstrap uncertainty for downstream "
                r"few-shot controls. The unit of resampling is the local checkpoint, "
                r"not an individual question, so the interval is a conservative check "
                r"on whether gains are broad across model families. Zero-shot mean "
                f"execution accuracy is {_fmt_float(report['zero_shot_mean_accuracy'])}.}}"
            ),
            r"\label{tab:downstream_fewshot_control_uncertainty}",
            r"\end{table}",
        ]
    )
    return "\n".join(rows) + "\n"


def render_model_transfer_markdown(report: dict[str, Any]) -> str:
    rows = [
        "# Downstream Model Transfer Summary",
        "",
        f"Complete runs: {report['complete_count']} / {report['runs_examined']}",
        "",
        "| Model | Family | Tuning | Mode | Seed | N | Zero exec. acc. | Few exec. acc. | Delta | Few exec. success | Few schema | Few F1 |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
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
        r"\begin{tabular}{lllrrrrrrr}",
        r"\toprule",
        r"Model & Tuning & Mode & N & Zero acc. & Few acc. & $\Delta$ & Few exec. & Few F1 & Few schema \\",
        r"\midrule",
    ]
    for run in report["complete_runs"]:
        zero = run["zero_shot"]
        few = run["few_shot"]
        delta = few["execution_accuracy"] - zero["execution_accuracy"]
        rows.append(
            "{model} & {tuning} & {mode} & {n} & {zero_acc} & {few_acc} & {delta} & {few_exec} & {few_f1} & {few_schema} \\\\".format(
                model=_escape_latex(run["model"]),
                tuning=_escape_latex(run["tuning"]),
                mode=_escape_latex(_short_mode(str(run.get("few_shot_mode", "")))),
                n=_fmt_int(few["n"]),
                zero_acc=_fmt_float(zero["execution_accuracy"]),
                few_acc=_fmt_float(few["execution_accuracy"]),
                delta=_fmt_float(delta),
                few_exec=_fmt_float(few["execution_success"]),
                few_f1=_fmt_float(few["answer_f1"]),
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
                r"with completed zero-shot and same-graph few-shot demonstration summaries.}"
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


def _summarize_control_model(
    *,
    slug: str,
    zero_dir: Path,
    control_dirs: dict[str, Path],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    zero_summary = zero_dir / "zero_shot_summary.json"
    missing = []
    if not zero_summary.exists():
        missing.append(str(zero_summary))
    required = ["ordered", "scored_no_signature", "random_seed13", "random_seed17", "random_seed23"]
    for key in required:
        if key not in control_dirs:
            missing.append(key)
        elif not (control_dirs[key] / "few_shot_summary.json").exists():
            missing.append(f"{key}/few_shot_summary.json")

    controls: dict[str, Any] = {}
    control_metadata = _control_metadata(control_dirs)
    for key, path in sorted(control_dirs.items()):
        summary_path = path / "few_shot_summary.json"
        if summary_path.exists():
            controls[key] = _extract_overall_metrics(_read_json(summary_path))
            controls[key]["run_id"] = path.name
            controls[key]["path"] = str(path)

    merged_metadata = {**control_metadata, **metadata}
    model_name = _display_model_name(str(merged_metadata.get("model", slug.replace("_", "-"))))
    random_runs = [
        controls[key]
        for key in ("random_seed13", "random_seed17", "random_seed23")
        if key in controls
    ]
    report = {
        "slug": slug,
        "model": model_name,
        "model_family": merged_metadata.get("model_family", _infer_model_family(model_name)),
        "tuning": merged_metadata.get("tuning", _infer_tuning(model_name)),
        "zero_shot_run_id": zero_dir.name,
        "complete": not missing,
        "missing": missing,
        "zero_shot": _extract_overall_metrics(_read_json(zero_summary))
        if zero_summary.exists()
        else {},
        "controls": controls,
        "random": {
            "seeds": [13, 17, 23],
            "mean": _mean_metrics(random_runs),
            "std": _std_metrics(random_runs),
        },
    }
    report["best_control"] = _best_control(report)
    return report


def _aggregate_control_models(models: list[dict[str, Any]]) -> dict[str, Any]:
    if not models:
        return {}
    zero = [float(model["zero_shot"]["execution_accuracy"]) for model in models]
    ordered = [_metric(model, "ordered", "execution_accuracy") for model in models]
    scored = [_metric(model, "scored_no_signature", "execution_accuracy") for model in models]
    random_mean = [
        model.get("random", {}).get("mean", {}).get("execution_accuracy")
        for model in models
    ]
    ordered_f = [float(value) for value in ordered if value is not None]
    scored_f = [float(value) for value in scored if value is not None]
    random_f = [float(value) for value in random_mean if value is not None]
    return {
        "complete_models": len(models),
        "mean_zero_execution_accuracy": _mean(zero),
        "mean_ordered_execution_accuracy": _mean(ordered_f),
        "mean_scored_execution_accuracy": _mean(scored_f),
        "mean_random_execution_accuracy": _mean(random_f),
        "ordered_improved_models": sum(
            1
            for model in models
            if (_metric(model, "ordered", "execution_accuracy") or 0.0)
            > float(model["zero_shot"]["execution_accuracy"])
        ),
        "scored_improved_models": sum(
            1
            for model in models
            if (_metric(model, "scored_no_signature", "execution_accuracy") or 0.0)
            > float(model["zero_shot"]["execution_accuracy"])
        ),
        "random_improved_models": sum(
            1
            for model in models
            if float(model.get("random", {}).get("mean", {}).get("execution_accuracy") or 0.0)
            > float(model["zero_shot"]["execution_accuracy"])
        ),
    }


def _mean_metrics(runs: list[dict[str, Any]]) -> dict[str, float]:
    if not runs:
        return {}
    return {
        metric: _mean([float(run[metric]) for run in runs if metric in run])
        for metric in METRICS
    }


def _std_metrics(runs: list[dict[str, Any]]) -> dict[str, float]:
    if not runs:
        return {}
    means = _mean_metrics(runs)
    values: dict[str, float] = {}
    for metric in METRICS:
        metric_values = [float(run[metric]) for run in runs if metric in run]
        if not metric_values:
            continue
        mean = means[metric]
        if len(metric_values) == 1:
            values[metric] = 0.0
        else:
            values[metric] = math.sqrt(
                sum((value - mean) ** 2 for value in metric_values)
                / (len(metric_values) - 1)
            )
    return values


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if q <= 0.0:
        return float(values[0])
    if q >= 1.0:
        return float(values[-1])
    position = q * (len(values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(values[lower])
    fraction = position - lower
    return float(values[lower] * (1.0 - fraction) + values[upper] * fraction)


def _std(values: list[float]) -> float:
    if len(values) <= 1:
        return 0.0
    mean = _mean(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))


def _derived_int_seed(seed: int, *parts: str) -> int:
    import hashlib

    digest = hashlib.sha256("|".join([str(seed), *parts]).encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


def _bootstrap_mean_interval(
    values: list[float],
    *,
    iterations: int,
    seed: int,
    confidence_level: float,
) -> dict[str, float]:
    if not values:
        return {"lower": 0.0, "upper": 0.0, "standard_error": 0.0}
    import random

    rng = random.Random(seed)
    n = len(values)
    estimates = []
    for _ in range(iterations):
        estimates.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    estimates.sort()
    alpha = 1.0 - confidence_level
    return {
        "lower": _quantile(estimates, alpha / 2.0),
        "upper": _quantile(estimates, 1.0 - alpha / 2.0),
        "standard_error": _std(estimates),
    }


def _best_control(model: dict[str, Any]) -> dict[str, Any]:
    candidates = []
    for key in ("ordered", "scored_no_signature"):
        if key in model["controls"]:
            candidates.append((key, float(model["controls"][key]["execution_accuracy"])))
    if model.get("random", {}).get("mean"):
        candidates.append(
            (
                "random_mean",
                float(model["random"]["mean"].get("execution_accuracy", 0.0)),
            )
        )
    if not candidates:
        return {}
    mode, value = max(candidates, key=lambda item: item[1])
    return {"mode": mode, "execution_accuracy": value}


def _metric(model: dict[str, Any], mode: str, metric: str) -> float | None:
    if mode in model.get("controls", {}):
        return float(model["controls"][mode][metric])
    return None


def _control_accuracy_for_uncertainty(model: dict[str, Any], mode: str) -> float | None:
    if mode == "random_mean":
        return model.get("random", {}).get("mean", {}).get("execution_accuracy")
    return _metric(model, mode, "execution_accuracy")


def _control_markdown_row(model: dict[str, Any]) -> str:
    zero = model["zero_shot"].get("execution_accuracy")
    ordered = _metric(model, "ordered", "execution_accuracy")
    scored = _metric(model, "scored_no_signature", "execution_accuracy")
    random_mean = model.get("random", {}).get("mean", {}).get("execution_accuracy")
    random_std = model.get("random", {}).get("std", {}).get("execution_accuracy")
    best = model.get("best_control", {})
    return (
        f"| {model['model']} | {model['tuning']} | {_fmt_optional(zero)} | "
        f"{_fmt_optional(ordered)} | {_fmt_optional(scored)} | "
        f"{_fmt_optional(random_mean)} | {_fmt_optional(random_std)} | "
        f"{_format_best_control(model)} |"
    )


def _control_slug_from_zero_run(run_id: str) -> str:
    name = run_id
    for prefix in ("20260602_downstream_", "20260603_downstream_"):
        if name.startswith(prefix):
            name = name[len(prefix) :]
    if name.endswith("_zero_fewshot"):
        name = name[: -len("_zero_fewshot")]
    return {
        "google_gemma2_9b_it": "gemma2_9b_it",
        "stable_cypher_instruct3b_transformers": "stable_cypher_instruct3b_transformers",
    }.get(name, name)


def _parse_control_run_id(run_id: str) -> tuple[str, str] | None:
    prefix = "20260603_control_"
    if not run_id.startswith(prefix):
        return None
    body = run_id[len(prefix) :]
    suffixes = {
        "_ordered_logged": "ordered",
        "_scored_no_signature": "scored_no_signature",
        "_random_seed13": "random_seed13",
        "_random_seed17": "random_seed17",
        "_random_seed23": "random_seed23",
    }
    for suffix, mode in suffixes.items():
        if body.endswith(suffix):
            return body[: -len(suffix)], mode
    return None


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _control_metadata(control_dirs: dict[str, Path]) -> dict[str, Any]:
    for key in ("ordered", "scored_no_signature", "random_seed13", "random_seed17", "random_seed23"):
        metadata = _read_json(control_dirs.get(key, Path()) / "metadata.json") if key in control_dirs else {}
        if metadata:
            return metadata
    return {}


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


def _markdown_row(run: dict[str, Any]) -> str:
    zero = run["zero_shot"]
    few = run["few_shot"]
    delta = few["execution_accuracy"] - zero["execution_accuracy"]
    return (
        f"| {run['model']} | {run['model_family']} | {run['tuning']} | "
        f"{run.get('few_shot_mode', '')} | {run.get('few_shot_seed') or ''} | "
        f"{few['n']} | "
        f"{_fmt_float(zero['execution_accuracy'])} | {_fmt_float(few['execution_accuracy'])} | "
        f"{_fmt_float(delta)} | {_fmt_float(few['execution_success'])} | "
        f"{_fmt_float(few['schema_valid'])} | {_fmt_float(few['answer_f1'])} |"
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


def _display_model_name(model_name: str) -> str:
    aliases = {
        "aigentx_llama31_cypher": "aigentx/Llama-3.1-8B Cypher LoRA",
        "aigentx_llama31_cypher_mixed": "aigentx/Llama-3.1-8B Cypher mixed LoRA",
        "google/gemma-2-9b-it": "Gemma-2-9B-IT",
        "neo4j_gemma2_text2cypher_lora": "neo4j/Gemma-2-9B Text2Cypher LoRA",
        "neo4j/text-to-cypher-Gemma-3-4B-Instruct-2025.04.0": "neo4j/Gemma-3-4B Text2Cypher",
        "projectwilsen_llama31_text2cypher_template": "projectwilsen/Llama-3.1-8B Text2Cypher LoRA",
        "Qwen/Qwen2.5-Coder-7B-Instruct": "Qwen2.5-Coder-7B-Instruct",
        "Qwen/Qwen3.5-9B": "Qwen3.5-9B",
        "stable-cypher-instruct3b-transformers": "ragraph-ai/stable-cypher-instruct-3b",
        "saiprasanth_llama31_text2cypher_template": "Saiprasanth15/Llama-3.1-8B Text2Cypher LoRA",
    }
    return aliases.get(model_name, model_name)


def _infer_model_family(model_name: str) -> str:
    lowered = model_name.lower()
    if "qwen" in lowered:
        return "Qwen"
    if "gemma" in lowered:
        return "Gemma"
    if "llama" in lowered:
        return "Llama"
    if "stable-cypher" in lowered or "stable" in lowered:
        return "StableLM"
    return "unspecified"


def _infer_tuning(model_name: str) -> str:
    lowered = model_name.lower()
    if "coder" in lowered:
        return "code instruction"
    if "cypher" in lowered and "lora" in lowered and "mixed" in lowered:
        return "Cypher mixed LoRA"
    if "text2cypher" in lowered and "lora" in lowered:
        return "Text2Cypher LoRA"
    if "cypher" in lowered and "lora" in lowered:
        return "Cypher LoRA"
    if "text2cypher" in lowered:
        return "Text2Cypher fine-tuned"
    if "stable-cypher" in lowered or ("cypher" in lowered and "instruct" in lowered):
        return "Cypher instruction"
    return "general instruction"


def _fmt_float(value: float) -> str:
    return f"{value:.3f}"


def _fmt_optional(value: Any) -> str:
    if value is None:
        return "--"
    return _fmt_float(float(value))


def _fmt_int(value: int | float) -> str:
    return f"{int(value):,}"


def _format_best_control(model: dict[str, Any]) -> str:
    best = model.get("best_control", {})
    best_acc = best.get("execution_accuracy")
    zero_acc = model.get("zero_shot", {}).get("execution_accuracy")
    if best_acc is None:
        return "--"
    if zero_acc is not None and float(best_acc) <= float(zero_acc):
        return "no gain"
    return f"{_short_mode(str(best.get('mode', '')))} ({_fmt_optional(best_acc)})"


def _short_mode(value: str) -> str:
    return {
        "ordered_same_category": "ordered",
        "random_same_category": "random",
        "random_mean": "random mean",
        "scored_no_signature": "scored no-sig",
    }.get(value, value or "--")


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
