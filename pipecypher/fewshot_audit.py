from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .diversity_metrics import canonical_query_signature
from .io import read_jsonl
from .retrieval import cosine_counts, tokenize
from .text2cypher import choose_few_shots, selection_metadata


def audit_fewshot_leakage(
    *,
    train_rows: list[dict[str, Any]],
    test_rows: list[dict[str, Any]],
    prediction_rows: list[dict[str, Any]] | None = None,
    selection_rows: list[dict[str, Any]] | None = None,
    high_similarity_threshold: float = 0.90,
    max_examples: int = 20,
) -> dict[str, Any]:
    prediction_rows = prediction_rows or []
    explicit_selection_rows = selection_rows or []
    selection_rows = explicit_selection_rows or [
        row["few_shot_selection"]
        for row in prediction_rows
        if isinstance(row.get("few_shot_selection"), dict)
    ]
    train_questions = {_normalized_question(row): row for row in train_rows}
    train_signatures = {_signature(row) for row in train_rows}
    test_by_id = {str(row.get("id", "")): row for row in test_rows}

    exact_question_overlap = []
    signature_overlap = []
    for row in test_rows:
        normalized = _normalized_question(row)
        signature = _signature(row)
        if normalized in train_questions:
            exact_question_overlap.append(str(row.get("id", "")))
        if signature in train_signatures:
            signature_overlap.append(str(row.get("id", "")))

    selected_total = 0
    selected_signature_matches = 0
    selected_high_similarity = 0
    selected_similarities: list[float] = []
    selected_count_hist = Counter()
    mode_counts = Counter()
    by_graph: dict[str, Counter[str]] = defaultdict(Counter)
    by_category: dict[str, Counter[str]] = defaultdict(Counter)
    risk_examples: list[dict[str, Any]] = []

    for selection in selection_rows:
        current_id = str(selection.get("current_id", ""))
        test_row = test_by_id.get(current_id, {})
        graph = str(selection.get("current_graph_profile") or test_row.get("graph_profile") or "unknown")
        category = str(selection.get("current_category") or test_row.get("category") or "unknown")
        mode = str(selection.get("mode") or "unknown")
        selected = selection.get("selected", []) or []
        selected_count_hist[str(len(selected))] += 1
        mode_counts[mode] += 1
        by_graph[graph]["rows"] += 1
        by_category[category]["rows"] += 1
        row_has_signature_match = False
        row_has_high_similarity = False
        max_similarity = 0.0
        for item in selected:
            selected_total += 1
            similarity = float(item.get("question_similarity", 0.0) or 0.0)
            selected_similarities.append(similarity)
            max_similarity = max(max_similarity, similarity)
            signature_match = bool(item.get("query_signature_match"))
            high_similarity = similarity >= high_similarity_threshold
            if signature_match:
                selected_signature_matches += 1
                row_has_signature_match = True
            if high_similarity:
                selected_high_similarity += 1
                row_has_high_similarity = True
        if row_has_signature_match:
            by_graph[graph]["rows_with_signature_match"] += 1
            by_category[category]["rows_with_signature_match"] += 1
        if row_has_high_similarity:
            by_graph[graph]["rows_with_high_similarity"] += 1
            by_category[category]["rows_with_high_similarity"] += 1
        if (row_has_signature_match or row_has_high_similarity) and len(risk_examples) < max_examples:
            risk_examples.append(
                {
                    "id": current_id,
                    "graph_profile": graph,
                    "category": category,
                    "mode": mode,
                    "selected_count": len(selected),
                    "max_question_similarity": max_similarity,
                    "has_query_signature_match": row_has_signature_match,
                    "has_high_question_similarity": row_has_high_similarity,
                    "selected_ids": [str(item.get("id", "")) for item in selected],
                }
            )

    return {
        "train_examples": len(train_rows),
        "test_examples": len(test_rows),
        "prediction_rows": len(prediction_rows),
        "selection_rows": len(selection_rows),
        "high_similarity_threshold": high_similarity_threshold,
        "train_test_overlap": {
            "exact_question_count": len(exact_question_overlap),
            "exact_question_rate": _rate(len(exact_question_overlap), len(test_rows)),
            "query_signature_count": len(signature_overlap),
            "query_signature_rate": _rate(len(signature_overlap), len(test_rows)),
        },
        "selected_examples": {
            "total_selected": selected_total,
            "mean_selected_per_row": selected_total / len(selection_rows) if selection_rows else 0.0,
            "query_signature_match_count": selected_signature_matches,
            "query_signature_match_rate": _rate(selected_signature_matches, selected_total),
            "high_question_similarity_count": selected_high_similarity,
            "high_question_similarity_rate": _rate(selected_high_similarity, selected_total),
            "mean_question_similarity": (
                sum(selected_similarities) / len(selected_similarities)
                if selected_similarities
                else 0.0
            ),
            "max_question_similarity": max(selected_similarities) if selected_similarities else 0.0,
            "selected_count_histogram": dict(sorted(selected_count_hist.items())),
            "mode_counts": dict(sorted(mode_counts.items())),
        },
        "by_graph": _summarize_groups(by_graph),
        "by_category": _summarize_groups(by_category),
        "risk_examples": risk_examples,
    }


def audit_fewshot_leakage_from_paths(
    *,
    benchmark_dir: str | Path,
    split: str = "test",
    predictions_path: str | Path | None = None,
    selection_path: str | Path | None = None,
    high_similarity_threshold: float = 0.90,
    reconstruct_mode: str = "",
    few_shot_k: int = 5,
    few_shot_seed: int = 13,
    few_shot_max_question_similarity: float = 0.90,
    few_shot_exclude_signature_match: bool = False,
) -> dict[str, Any]:
    benchmark = Path(benchmark_dir)
    train_rows = read_jsonl(benchmark / "train.jsonl")
    test_rows = read_jsonl(benchmark / f"{split}.jsonl")
    prediction_rows = read_jsonl(predictions_path) if predictions_path else []
    selection_rows = read_jsonl(selection_path) if selection_path else []
    if reconstruct_mode and not selection_rows:
        selection_rows = [
            selection_metadata(
                current=row,
                selected=choose_few_shots(
                    train_rows,
                    current=row,
                    k=few_shot_k,
                    mode=reconstruct_mode,
                    seed=few_shot_seed,
                    max_question_similarity=few_shot_max_question_similarity,
                    exclude_signature_match=few_shot_exclude_signature_match,
                ),
            )
            for row in test_rows
        ]
    return audit_fewshot_leakage(
        train_rows=train_rows,
        test_rows=test_rows,
        prediction_rows=prediction_rows,
        selection_rows=selection_rows,
        high_similarity_threshold=high_similarity_threshold,
    )


def render_fewshot_leakage_markdown(report: dict[str, Any]) -> str:
    overlap = report["train_test_overlap"]
    selected = report["selected_examples"]
    lines = [
        "# Few-Shot Leakage Audit",
        "",
        f"- Train examples: `{report['train_examples']}`",
        f"- Test examples: `{report['test_examples']}`",
        f"- Selection rows: `{report['selection_rows']}`",
        f"- Exact train/test question overlap: `{overlap['exact_question_count']}` "
        f"({overlap['exact_question_rate']:.3f})",
        f"- Train/test query-signature overlap: `{overlap['query_signature_count']}` "
        f"({overlap['query_signature_rate']:.3f})",
        f"- Selected demonstrations with query-signature matches: "
        f"`{selected['query_signature_match_count']}` "
        f"({selected['query_signature_match_rate']:.3f})",
        f"- Selected demonstrations above question-similarity threshold: "
        f"`{selected['high_question_similarity_count']}` "
        f"({selected['high_question_similarity_rate']:.3f})",
        f"- Mean / max selected question similarity: "
        f"`{selected['mean_question_similarity']:.3f}` / "
        f"`{selected['max_question_similarity']:.3f}`",
        "",
        "## Risk Examples",
        "",
    ]
    if not report["risk_examples"]:
        lines.append("No selected demonstration exceeded the configured risk checks.")
    else:
        for item in report["risk_examples"]:
            lines.append(
                "- `{id}` {graph}/{category} mode={mode} selected={selected} "
                "max_sim={sim:.3f} signature_match={signature}".format(
                    id=item["id"],
                    graph=item["graph_profile"],
                    category=item["category"],
                    mode=item["mode"],
                    selected=",".join(item["selected_ids"]),
                    sim=float(item["max_question_similarity"]),
                    signature=str(item["has_query_signature_match"]).lower(),
                )
            )
    lines.append("")
    return "\n".join(lines)


def render_fewshot_leakage_latex(report: dict[str, Any]) -> str:
    overlap = report["train_test_overlap"]
    selected = report["selected_examples"]
    return "\n".join(
        [
            r"\begin{table}[H]",
            r"\centering",
            r"\small",
            r"\begin{tabular}{lr}",
            r"\toprule",
            r"Few-shot audit metric & Value \\",
            r"\midrule",
            f"Train / test examples & {report['train_examples']} / {report['test_examples']} \\\\",
            f"Selection rows & {report['selection_rows']} \\\\",
            f"Exact question overlap & {overlap['exact_question_count']} ({overlap['exact_question_rate']:.3f}) \\\\",
            f"Query-signature overlap & {overlap['query_signature_count']} ({overlap['query_signature_rate']:.3f}) \\\\",
            f"Selected signature matches & {selected['query_signature_match_count']} ({selected['query_signature_match_rate']:.3f}) \\\\",
            f"Selected high-similarity demos & {selected['high_question_similarity_count']} ({selected['high_question_similarity_rate']:.3f}) \\\\",
            f"Mean / max selected similarity & {selected['mean_question_similarity']:.3f} / {selected['max_question_similarity']:.3f} \\\\",
            r"\bottomrule",
            r"\end{tabular}",
            (
                r"\caption{Few-shot leakage audit for downstream demonstration-bank "
                r"evaluation. Query-signature and near-question overlap are reported "
                r"separately from execution metrics so large few-shot gains can be "
                r"interpreted against template-overlap risk.}"
            ),
            r"\label{tab:fewshot_leakage_audit}",
            r"\end{table}",
            "",
        ]
    )


def build_fewshot_leakage_control_report(
    reports_by_mode: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    rows = []
    for mode, report in reports_by_mode.items():
        selected = report["selected_examples"]
        rows.append(
            {
                "mode": mode,
                "selection_rows": int(report["selection_rows"]),
                "total_selected": int(selected["total_selected"]),
                "signature_match_rate": float(selected["query_signature_match_rate"]),
                "high_similarity_rate": float(selected["high_question_similarity_rate"]),
                "mean_similarity": float(selected["mean_question_similarity"]),
                "max_similarity": float(selected["max_question_similarity"]),
            }
        )
    train_test = next(iter(reports_by_mode.values()), {}).get("train_test_overlap", {})
    return {
        "modes": rows,
        "train_test_overlap": train_test,
        "high_similarity_threshold": next(
            iter(reports_by_mode.values()), {}
        ).get("high_similarity_threshold", 0.90),
    }


def render_fewshot_leakage_control_markdown(report: dict[str, Any]) -> str:
    overlap = report.get("train_test_overlap", {})
    lines = [
        "# Few-Shot Leakage Control Audit",
        "",
        f"- Exact train/test question overlap: `{overlap.get('exact_question_count', 0)}` "
        f"({float(overlap.get('exact_question_rate', 0.0)):.3f})",
        f"- Train/test query-signature overlap: `{overlap.get('query_signature_count', 0)}` "
        f"({float(overlap.get('query_signature_rate', 0.0)):.3f})",
        "",
        "| Mode | Rows | Selected demos | Signature match rate | High-sim rate | Mean sim | Max sim |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report["modes"]:
        lines.append(
            "| {mode} | {rows} | {selected} | {sig:.3f} | {high:.3f} | {mean:.3f} | {max:.3f} |".format(
                mode=row["mode"],
                rows=row["selection_rows"],
                selected=row["total_selected"],
                sig=row["signature_match_rate"],
                high=row["high_similarity_rate"],
                mean=row["mean_similarity"],
                max=row["max_similarity"],
            )
        )
    lines.append("")
    return "\n".join(lines)


def render_fewshot_leakage_control_latex(report: dict[str, Any]) -> str:
    rows = [
        r"\begin{table}[H]",
        r"\centering",
        r"\small",
        r"\resizebox{\columnwidth}{!}{%",
        r"\begin{tabular}{lrrrrr}",
        r"\toprule",
        r"Selection mode & Rows & Demos & Sig. match & High sim. & Mean sim. \\",
        r"\midrule",
    ]
    for row in report["modes"]:
        rows.append(
            "{mode} & {rows} & {selected} & {sig:.3f} & {high:.3f} & {mean:.3f} \\\\".format(
                mode=_escape_latex(str(row["mode"])),
                rows=int(row["selection_rows"]),
                selected=int(row["total_selected"]),
                sig=float(row["signature_match_rate"]),
                high=float(row["high_similarity_rate"]),
                mean=float(row["mean_similarity"]),
            )
        )
    overlap = report.get("train_test_overlap", {})
    rows.extend(
        [
            r"\bottomrule",
            r"\end{tabular}",
            r"}",
            (
                r"\caption{Few-shot leakage controls for downstream demonstration-bank "
                r"evaluation. The held-out split has "
                f"{int(overlap.get('exact_question_count', 0))} exact train/test question overlaps "
                r"and "
                f"{int(overlap.get('query_signature_count', 0))} train/test query-signature overlaps; "
                r"selection-mode rates show how often retrieved demonstrations share "
                r"the test query signature or exceed the 0.90 normalized-question "
                r"similarity threshold.}"
            ),
            r"\label{tab:fewshot_leakage_controls}",
            r"\end{table}",
            "",
        ]
    )
    return "\n".join(rows)


def _signature(row: dict[str, Any]) -> str:
    return canonical_query_signature(str(row.get("cypher") or row.get("gold_cypher") or ""))


def _normalized_question(row: dict[str, Any]) -> str:
    return " ".join(tokenize(str(row.get("question", ""))))


def _rate(count: int, denominator: int) -> float:
    return count / denominator if denominator else 0.0


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


def _summarize_groups(groups: dict[str, Counter[str]]) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for key, counts in sorted(groups.items()):
        rows = int(counts.get("rows", 0))
        summary[key] = {
            "rows": rows,
            "rows_with_signature_match": int(counts.get("rows_with_signature_match", 0)),
            "rows_with_signature_match_rate": _rate(
                int(counts.get("rows_with_signature_match", 0)),
                rows,
            ),
            "rows_with_high_similarity": int(counts.get("rows_with_high_similarity", 0)),
            "rows_with_high_similarity_rate": _rate(
                int(counts.get("rows_with_high_similarity", 0)),
                rows,
            ),
        }
    return summary
