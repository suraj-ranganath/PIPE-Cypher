"""Independent (cross-family) re-judging and judge-agreement analysis.

This module supports experiment E2.1: every benchmark item (accepted rows of an
exported benchmark, plus optionally the judge-decided rejected candidates from
generation ``records.jsonl`` files) is re-judged by one or more non-Qwen local
judges through the *unchanged* :class:`pipecypher.judge.LLMJudge` path, so the
system prompt, user prompt template (``JUDGE_PROMPT``), schema slice
(``schema_slice_for_cypher``), execution sample (first five rows), validation
summary, temperature, token budget, and categorical-value guard are identical to
the original judge contract.

Context reconstruction (what the original judge saw):

* ``source_record`` -- the exported row's ``source.records_path`` is available
  locally, so the original ``ValidationResult`` (including warning issues) and
  ``ExecutionResult`` rows are restored byte-for-byte from the generation record.
* ``export_reconstructed`` -- only the export row is available. The execution
  sample is rebuilt from ``result_rows_sample`` (the exporter keeps
  ``execution.rows[:5]``, exactly the rows the judge prompt shows), structural
  features and gate flags come from the export, and warning-level validation
  issues are recomputed with the current deterministic validator. Error-level
  issues that the current validator would add are dropped (the original row
  passed validation) and logged in ``context_notes``.
* ``+reexecuted`` -- with ``--neo4j-config graph=yaml`` the reference Cypher is
  re-executed read-only (``limit_rows=25`` as in the pipeline) and the fresh rows
  replace the stored sample.

Every output row and CSV that carries questions, Cypher literals, or result rows
is PRIVATE/internal: it contains graph values and must not be shared outside the
project without redaction.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import random
import re
import subprocess
import time
from collections import Counter, defaultdict, deque
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .benchmark_export import benchmark_id
from .calibration import wilson_interval
from .io import append_jsonl, read_jsonl
from .judge import DeterministicJudge, LLMJudge
from .llm import assert_model_served, extract_json_text, resolve_api_key
from .models import ExecutionResult, SchemaSummary, ValidationIssue, ValidationResult
from .prompts import JUDGE_PROMPT, SYSTEM_JSON_ENGINEER
from .question_constraints import apply_question_constraints
from .validator import validate_cypher

PRIVATE_NOTICE = (
    "PRIVATE/internal: contains benchmark questions, Cypher literals, and graph result "
    "values. Do not share outside the project without redaction."
)

# Judge settings used by the original pipeline (`LLMJudge` defaults in run_pipeline.py).
ORIGINAL_JUDGE_TEMPERATURE = 0.0
ORIGINAL_JUDGE_MAX_TOKENS = 512
# The pipeline executes candidates with `client.run(..., limit_rows=25)`.
PIPELINE_EXECUTION_ROW_LIMIT = 25
# `LLMJudge` shows `execution.rows[:5]` to the judge.
JUDGE_VISIBLE_ROWS = 5

POST_JUDGE_REJECTIONS = (
    "duplicate accepted question",
    "entity diversity cap exceeded",
)

# Hosted (provider="openai") judges may only see public LDBC study graphs.
PUBLIC_HOSTED_GRAPHS = frozenset({"finbench", "snb"})

HOSTED_API_HOST_SUFFIXES = (
    "openai.com",
    "anthropic.com",
    "googleapis.com",
    "openrouter.ai",
    "together.xyz",
    "together.ai",
    "groq.com",
    "fireworks.ai",
    "mistral.ai",
    "cohere.ai",
    "cohere.com",
    "deepinfra.com",
    "perplexity.ai",
    "azure.com",
    "amazonaws.com",
)


# ---------------------------------------------------------------------------
# Small shared helpers (also used by benchmark_validation_packet)
# ---------------------------------------------------------------------------


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def judge_contract_sha256() -> str:
    """Fingerprint of the judge user-prompt template (matches paper_appendix hashes)."""

    return sha256_text(JUDGE_PROMPT)


def judge_prompt_sha256(system: str, user: str) -> str:
    return sha256_text(json.dumps({"system": system, "user": user}, ensure_ascii=False, sort_keys=True))


def git_revision(repo_root: str | Path | None = None) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root) if repo_root else None,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_yes_no(value: Any) -> bool | None:
    text = str(value if value is not None else "").strip().lower()
    if text in {"yes", "y", "true", "t", "1", "pass", "correct", "accept", "accepted"}:
        return True
    if text in {"no", "n", "false", "f", "0", "fail", "incorrect", "reject", "rejected"}:
        return False
    return None


def format_bool(value: bool | None) -> str:
    if value is None:
        return ""
    return "yes" if value else "no"


def benchmark_rows_path(path: str | Path, split: str = "all") -> Path:
    candidate = Path(path)
    if candidate.is_dir():
        return candidate / f"{split}.jsonl"
    return candidate


def load_benchmark_rows(path: str | Path, split: str = "all") -> list[dict[str, Any]]:
    rows_path = benchmark_rows_path(path, split)
    if not rows_path.exists():
        raise FileNotFoundError(f"benchmark rows not found: {rows_path}")
    rows = read_jsonl(rows_path)
    split_map = benchmark_split_map(path)
    for row in rows:
        if split_map and "split" not in row:
            row["_split"] = split_map.get(str(row.get("id")), "")
        elif "split" in row:
            row["_split"] = row["split"]
        elif split != "all":
            row["_split"] = split
    return rows


def benchmark_split_map(path: str | Path) -> dict[str, str]:
    """Map example id to split when ``path`` is an export directory."""

    directory = Path(path)
    if not directory.is_dir():
        return {}
    mapping: dict[str, str] = {}
    for split in ("train", "dev", "test"):
        split_path = directory / f"{split}.jsonl"
        if not split_path.exists():
            continue
        for row in read_jsonl(split_path):
            mapping[str(row.get("id"))] = split
    return mapping


def write_private_csv(
    path: str | Path,
    rows: list[dict[str, Any]],
    fieldnames: list[str],
    *,
    notice: str = PRIVATE_NOTICE,
) -> None:
    """Write a CSV whose first line is a ``#`` comment marking it PRIVATE/internal."""

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        f.write(f"# {notice}\n")
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_cell(row.get(key, "")) for key in fieldnames})


def write_plain_csv(path: str | Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_cell(row.get(key, "")) for key in fieldnames})


def read_csv_rows(path: str | Path) -> list[dict[str, str]]:
    """Read a CSV, skipping leading ``#`` comment lines (privacy headers)."""

    text = Path(path).read_text(encoding="utf-8-sig")
    lines = text.splitlines(keepends=True)
    start = 0
    while start < len(lines) and lines[start].lstrip().startswith("#"):
        start += 1
    reader = csv.DictReader(io.StringIO("".join(lines[start:])))
    return [dict(row) for row in reader]


def _csv_cell(value: Any) -> Any:
    if isinstance(value, bool):
        return format_bool(value)
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return value


def rows_preview(rows: list[dict[str, Any]], *, k: int = 3, max_chars: int = 1500) -> str:
    text = json.dumps(list(rows or [])[:k], ensure_ascii=False, default=str)
    if len(text) > max_chars:
        text = text[: max_chars - 3] + "..."
    return text


def tex_escape(value: Any) -> str:
    text = str(value)
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
    return "".join(replacements.get(ch, ch) for ch in text)


# ---------------------------------------------------------------------------
# Agreement statistics
# ---------------------------------------------------------------------------


def cohen_kappa(labels_a: list[Any], labels_b: list[Any]) -> float | None:
    """Cohen's kappa for two raters over the same items (any hashable labels).

    Returns ``None`` when chance agreement is 1 (both raters use one identical
    constant label), where kappa is undefined.
    """

    if len(labels_a) != len(labels_b):
        raise ValueError("label lists must have equal length")
    total = len(labels_a)
    if total == 0:
        return None
    observed = sum(1 for a, b in zip(labels_a, labels_b) if a == b) / total
    counts_a = Counter(labels_a)
    counts_b = Counter(labels_b)
    expected = sum((counts_a[label] / total) * (counts_b[label] / total) for label in set(counts_a) | set(counts_b))
    if expected >= 1.0 - 1e-12:
        return None
    return (observed - expected) / (1.0 - expected)


def fleiss_kappa(category_counts: list[dict[Any, int]]) -> float | None:
    """Fleiss' kappa from per-item category counts.

    ``category_counts[i][c]`` is the number of raters assigning item ``i`` to
    category ``c``. Every item must have the same number of ratings (>= 2).
    Returns ``None`` when undefined (no items or perfect chance agreement).
    """

    items = [counts for counts in category_counts if sum(counts.values()) > 0]
    if not items:
        return None
    raters = sum(items[0].values())
    if raters < 2:
        return None
    if any(sum(counts.values()) != raters for counts in items):
        raise ValueError("Fleiss' kappa requires the same number of ratings per item")
    n_items = len(items)
    categories = sorted({cat for counts in items for cat in counts}, key=str)
    p_bar = sum(
        (sum(count * count for count in counts.values()) - raters) / (raters * (raters - 1))
        for counts in items
    ) / n_items
    p_e = sum(
        (sum(counts.get(cat, 0) for counts in items) / (n_items * raters)) ** 2 for cat in categories
    )
    if p_e >= 1.0 - 1e-12:
        return None
    return (p_bar - p_e) / (1.0 - p_e)


def fleiss_kappa_from_ratings(ratings: list[list[Any]]) -> float | None:
    return fleiss_kappa([dict(Counter(item)) for item in ratings])


def gwet_ac1(labels_a: list[Any], labels_b: list[Any]) -> float | None:
    """Gwet's AC1 for two raters; robust to the kappa prevalence paradox."""

    if len(labels_a) != len(labels_b):
        raise ValueError("label lists must have equal length")
    total = len(labels_a)
    if total == 0:
        return None
    categories = sorted(set(labels_a) | set(labels_b), key=str)
    observed = sum(1 for a, b in zip(labels_a, labels_b) if a == b) / total
    if len(categories) < 2:
        return 1.0 if observed == 1.0 else None
    q = len(categories)
    pi = {cat: (labels_a.count(cat) + labels_b.count(cat)) / (2 * total) for cat in categories}
    expected = sum(value * (1 - value) for value in pi.values()) / (q - 1)
    if expected >= 1.0 - 1e-12:
        return None
    return (observed - expected) / (1.0 - expected)


def binary_confusion(pairs: list[tuple[bool, bool]]) -> dict[str, Any]:
    """Confusion counts with ``pairs = [(reference, other), ...]``."""

    both_pass = sum(1 for a, b in pairs if a and b)
    both_fail = sum(1 for a, b in pairs if not a and not b)
    ref_pass_other_fail = sum(1 for a, b in pairs if a and not b)
    ref_fail_other_pass = sum(1 for a, b in pairs if not a and b)
    total = len(pairs)
    ref_pass = both_pass + ref_pass_other_fail
    ref_fail = both_fail + ref_fail_other_pass
    labels_a = [a for a, _ in pairs]
    labels_b = [b for _, b in pairs]
    flag_ci = wilson_interval(ref_pass_other_fail, ref_pass)
    rescue_ci = wilson_interval(ref_fail_other_pass, ref_fail)
    return {
        "n": total,
        "both_pass": both_pass,
        "both_fail": both_fail,
        "reference_pass_other_fail": ref_pass_other_fail,
        "reference_fail_other_pass": ref_fail_other_pass,
        "agreement": (both_pass + both_fail) / total if total else None,
        "cohen_kappa": cohen_kappa(labels_a, labels_b),
        "gwet_ac1": gwet_ac1(labels_a, labels_b),
        "flag_rate_among_reference_pass": ref_pass_other_fail / ref_pass if ref_pass else None,
        "flag_rate_ci95": list(flag_ci) if ref_pass else None,
        "rescue_rate_among_reference_fail": ref_fail_other_pass / ref_fail if ref_fail else None,
        "rescue_rate_ci95": list(rescue_ci) if ref_fail else None,
    }


def rate_with_ci(successes: int, total: int) -> dict[str, Any]:
    low, high = wilson_interval(successes, total)
    return {
        "count": successes,
        "n": total,
        "rate": successes / total if total else None,
        "ci95": [low, high] if total else None,
    }


# ---------------------------------------------------------------------------
# Re-judge items and context reconstruction
# ---------------------------------------------------------------------------


@dataclass
class RejudgeItem:
    item_id: str
    item_source: str
    graph_profile: str
    category: str
    difficulty: str
    primary_strategy: str
    question: str
    cypher: str
    validation: ValidationResult
    execution: ExecutionResult
    result_row_count_observed: int
    context_source: str
    original: dict[str, Any]
    provenance: dict[str, Any] = field(default_factory=dict)
    context_notes: list[str] = field(default_factory=list)


@dataclass
class SkippedItem:
    item_key: str
    item_source: str
    reason: str


def validation_from_dict(data: dict[str, Any]) -> ValidationResult:
    return ValidationResult(
        read_only=bool(data.get("read_only")),
        syntax_valid=bool(data.get("syntax_valid")),
        schema_valid=bool(data.get("schema_valid")),
        normalized_cypher=str(data.get("normalized_cypher") or ""),
        issues=[
            ValidationIssue(
                str(issue.get("level", "")),
                str(issue.get("code", "")),
                str(issue.get("message", "")),
            )
            for issue in data.get("issues") or []
        ],
        structural_features=dict(data.get("structural_features") or {}),
    )


def execution_from_dict(data: dict[str, Any]) -> ExecutionResult:
    return ExecutionResult(
        success=bool(data.get("success")),
        rows=list(data.get("rows") or []),
        error=data.get("error"),
        latency_ms=data.get("latency_ms"),
    )


def record_original_judgement(record: dict[str, Any]) -> dict[str, Any]:
    """Describe what the original judge decided for a generation record."""

    judge = record.get("judge") or {}
    raw = judge.get("raw") or {}
    reason = str(judge.get("failure_reason") or "")
    if "fallback_after_error" in raw:
        source = "deterministic_fallback_after_llm_error"
        llm_decision = None
        decision: bool | None = bool(judge.get("passed"))
    elif "pass" in raw:
        source = "llm_judge"
        if raw.get("override"):
            source += f"+{raw.get('override')}"
        llm_decision = bool(raw.get("pass"))
        decision = bool(judge.get("passed"))
    elif reason in POST_JUDGE_REJECTIONS:
        source = "post_judge_rejection"
        llm_decision = None
        decision = None
    else:
        source = "not_judged"
        llm_decision = None
        decision = None
    return {
        "decision": decision,
        "llm_decision": llm_decision,
        "decision_source": source,
        "ambiguity_score": judge.get("ambiguity_score"),
        "semantic_alignment_score": judge.get("semantic_alignment_score"),
        "schema_use_score": judge.get("schema_use_score"),
        "difficulty": judge.get("difficulty"),
        "failure_reason": reason,
        "fallback_error": raw.get("fallback_after_error"),
        "source_model": record.get("model"),
    }


def _validation_ok(validation: dict[str, Any]) -> bool:
    return (
        bool(validation.get("read_only"))
        and bool(validation.get("syntax_valid"))
        and bool(validation.get("schema_valid"))
        and not any(issue.get("level") == "error" for issue in validation.get("issues") or [])
    )


def record_rejudge_eligibility(record: dict[str, Any]) -> tuple[bool, str]:
    """Return whether the judge was the deciding gate for this record.

    Only records whose deterministic gates passed (valid, executed, non-empty)
    and whose judge output is preserved are re-judged; others are skipped with
    an explicit reason so the omission is auditable.
    """

    original = record_original_judgement(record)
    if original["decision_source"] == "post_judge_rejection":
        return False, f"post-judge rejection ({original['failure_reason']}); original judge output not preserved"
    if original["decision_source"] == "not_judged":
        return False, f"judge not decisive ({original['failure_reason'] or 'no judge output'})"
    validation = record.get("validation") or {}
    if not _validation_ok(validation):
        return False, "deterministic validation failed (judge not decisive)"
    execution = record.get("execution") or {}
    if not execution.get("success"):
        return False, "execution failed (judge not decisive)"
    if not execution.get("rows"):
        return False, "execution returned no rows (judge not decisive)"
    return True, ""


class SourceRecordIndex:
    """Lazy index of generation records keyed by benchmark id."""

    def __init__(self, search_roots: Iterable[str | Path] = ()) -> None:
        self.search_roots = [Path(root) for root in search_roots]
        self._cache: dict[str, dict[str, dict[str, Any]] | None] = {}

    def resolve(self, raw_path: str | None) -> Path | None:
        if not raw_path:
            return None
        candidate = Path(raw_path)
        if candidate.is_dir():
            candidate = candidate / "records.jsonl"
        options = [candidate] if candidate.is_absolute() else [candidate]
        if not candidate.is_absolute():
            options.extend(root / candidate for root in self.search_roots)
        for option in options:
            if option.exists():
                return option
        return None

    def lookup(self, raw_path: str | None, example_id: str) -> tuple[dict[str, Any] | None, str]:
        resolved = self.resolve(raw_path)
        if resolved is None:
            return None, f"source records not found: {raw_path}"
        key = str(resolved.resolve())
        if key not in self._cache:
            index: dict[str, dict[str, Any]] = {}
            for record in read_jsonl(resolved):
                if not record.get("accepted"):
                    continue
                index.setdefault(benchmark_id(record), record)
            self._cache[key] = index
        index = self._cache[key] or {}
        record = index.get(example_id)
        if record is None:
            return None, f"example id not found in {resolved}"
        return record, str(resolved)


def export_reconstructed_context(
    row: dict[str, Any],
    schema: SchemaSummary,
) -> tuple[ValidationResult, ExecutionResult, list[str]]:
    """Rebuild judge context from an exported benchmark row alone."""

    notes: list[str] = []
    gates = row.get("gates") or {}
    cypher = str(row.get("normalized_cypher") or row.get("cypher") or "")
    question = str(row.get("question") or "")
    recomputed = apply_question_constraints(validate_cypher(cypher, schema, normalize=True), question)
    issues = [issue for issue in recomputed.issues if issue.level != "error"]
    dropped = [issue.code for issue in recomputed.issues if issue.level == "error"]
    if dropped:
        notes.append("dropped_current_validator_errors=" + ",".join(sorted(set(dropped))))
    if recomputed.normalized_cypher != cypher:
        notes.append("current_normalizer_changes_cypher")
    validation = ValidationResult(
        read_only=bool(gates.get("read_only", recomputed.read_only)),
        syntax_valid=bool(gates.get("syntax_valid", recomputed.syntax_valid)),
        schema_valid=bool(gates.get("schema_valid", recomputed.schema_valid)),
        normalized_cypher=cypher,
        issues=issues,
        structural_features=dict(row.get("structural_features") or recomputed.structural_features),
    )
    rows = list(row.get("result_rows_sample") or [])
    if len(rows) < min(JUDGE_VISIBLE_ROWS, int(row.get("result_row_count_observed") or 0)):
        notes.append("result_rows_sample_shorter_than_judge_view")
    execution = ExecutionResult(success=bool(gates.get("execution_success", True)), rows=rows)
    notes.append("validation_issues_recomputed_with_current_validator")
    return validation, execution, notes


def _features(validation: ValidationResult) -> dict[str, Any]:
    return validation.structural_features or {}


def items_from_benchmark(
    rows: list[dict[str, Any]],
    schemas: dict[str, SchemaSummary],
    *,
    context_mode: str = "auto",
    source_index: SourceRecordIndex | None = None,
) -> tuple[list[RejudgeItem], list[SkippedItem]]:
    if context_mode not in {"auto", "record", "export"}:
        raise ValueError("context_mode must be auto, record, or export")
    items: list[RejudgeItem] = []
    skipped: list[SkippedItem] = []
    source_index = source_index or SourceRecordIndex()
    for row in rows:
        example_id = str(row.get("id") or benchmark_id(row))
        graph = str(row.get("graph_profile") or "")
        if graph not in schemas:
            raise ValueError(f"missing --schema mapping for graph_profile={graph}")
        source = row.get("source") or {}
        gates = row.get("gates") or {}
        scores = row.get("judge_scores") or {}
        original = {
            "decision": bool(gates.get("judge_pass")),
            "llm_decision": None,
            "decision_source": "export_gates",
            "ambiguity_score": scores.get("ambiguity"),
            "semantic_alignment_score": scores.get("semantic_alignment"),
            "schema_use_score": scores.get("schema_use"),
            "difficulty": scores.get("difficulty"),
            "failure_reason": "",
            "fallback_error": None,
            "source_model": source.get("model"),
        }
        notes: list[str] = []
        record = None
        if context_mode in {"auto", "record"}:
            record, detail = source_index.lookup(source.get("records_path"), example_id)
            if record is None:
                if context_mode == "record":
                    skipped.append(SkippedItem(example_id, "benchmark", f"source record unavailable: {detail}"))
                    continue
                notes.append(f"source_record_unavailable: {detail}")
        if record is not None:
            validation = validation_from_dict(record.get("validation") or {})
            execution = execution_from_dict(record.get("execution") or {})
            context_source = "source_record"
            export_cypher = str(row.get("normalized_cypher") or row.get("cypher") or "")
            if validation.normalized_cypher and validation.normalized_cypher != export_cypher:
                notes.append("source_record_cypher_differs_from_export")
            record_original = record_original_judgement(record)
            original.update(
                {
                    key: record_original[key]
                    for key in ("llm_decision", "decision_source", "failure_reason", "fallback_error")
                }
            )
            if record_original["decision"] is not None:
                original["decision"] = record_original["decision"]
        else:
            validation, execution, export_notes = export_reconstructed_context(row, schemas[graph])
            notes.extend(export_notes)
            context_source = "export_reconstructed"
        features = _features(validation)
        items.append(
            RejudgeItem(
                item_id=example_id,
                item_source="benchmark",
                graph_profile=graph,
                category=str(row.get("category") or ""),
                difficulty=str(row.get("difficulty") or features.get("difficulty") or "unknown"),
                primary_strategy=str(features.get("primary_strategy") or ""),
                question=str(row.get("question") or ""),
                cypher=validation.normalized_cypher or str(row.get("normalized_cypher") or row.get("cypher") or ""),
                validation=validation,
                execution=execution,
                result_row_count_observed=int(row.get("result_row_count_observed") or len(execution.rows)),
                context_source=context_source,
                original=original,
                provenance={
                    "split": row.get("_split", ""),
                    "source_run": source.get("run"),
                    "records_path": source.get("records_path"),
                },
                context_notes=notes,
            )
        )
    return items, skipped


def load_records_files(paths: Iterable[str | Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            path = path / "records.jsonl"
        if not path.exists():
            raise FileNotFoundError(f"records file not found: {path}")
        for record in read_jsonl(path):
            record = dict(record)
            record["_source_run"] = path.parent.name
            record["_source_records_path"] = str(path)
            rows.append(record)
    return rows


def items_from_records(
    records: list[dict[str, Any]],
    schemas: dict[str, SchemaSummary],
    *,
    scope: str = "rejected",
) -> tuple[list[RejudgeItem], list[SkippedItem]]:
    if scope not in {"rejected", "all"}:
        raise ValueError("records scope must be 'rejected' or 'all'")
    items: list[RejudgeItem] = []
    skipped: list[SkippedItem] = []
    seen: set[str] = set()
    for record in records:
        accepted = bool(record.get("accepted"))
        if scope == "rejected" and accepted:
            continue
        item_id = benchmark_id(record)
        source_label = "records_accepted" if accepted else "records_rejected"
        if item_id in seen:
            skipped.append(SkippedItem(item_id, source_label, "duplicate candidate (same graph/category/question/cypher)"))
            continue
        eligible, reason = record_rejudge_eligibility(record)
        if not eligible:
            skipped.append(SkippedItem(item_id, source_label, reason))
            continue
        graph = str(record.get("graph_profile") or "")
        if graph not in schemas:
            raise ValueError(f"missing --schema mapping for graph_profile={graph}")
        seen.add(item_id)
        validation = validation_from_dict(record.get("validation") or {})
        execution = execution_from_dict(record.get("execution") or {})
        features = _features(validation)
        items.append(
            RejudgeItem(
                item_id=item_id,
                item_source=source_label,
                graph_profile=graph,
                category=str(record.get("category") or ""),
                difficulty=str(features.get("difficulty") or "unknown"),
                primary_strategy=str(features.get("primary_strategy") or ""),
                question=str(record.get("question") or ""),
                cypher=validation.normalized_cypher or str(record.get("cypher") or ""),
                validation=validation,
                execution=execution,
                result_row_count_observed=len(execution.rows),
                context_source="source_record",
                original=record_original_judgement(record),
                provenance={
                    "split": "",
                    "source_run": record.get("_source_run"),
                    "records_path": record.get("_source_records_path"),
                },
            )
        )
    return items, skipped


def merge_items(*groups: list[RejudgeItem]) -> tuple[list[RejudgeItem], list[SkippedItem]]:
    merged: list[RejudgeItem] = []
    skipped: list[SkippedItem] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            if item.item_id in seen:
                skipped.append(SkippedItem(item.item_id, item.item_source, "already included from an earlier source"))
                continue
            seen.add(item.item_id)
            merged.append(item)
    return merged, skipped


def select_items(items: list[RejudgeItem], *, limit: int = 0, seed: int | None = None) -> list[RejudgeItem]:
    selected = list(items)
    if limit and limit < len(selected):
        if seed is not None:
            rng = random.Random(seed)
            selected = sorted(selected, key=lambda item: item.item_id)
            rng.shuffle(selected)
        selected = selected[:limit]
    return selected


def reexecute_items(items: list[RejudgeItem], clients: dict[str, Any]) -> None:
    """Replace stored execution evidence with a fresh read-only execution."""

    for item in items:
        client = clients.get(item.graph_profile)
        if client is None:
            continue
        if not item.validation.read_only:
            item.context_notes.append("reexecution_skipped_not_read_only")
            continue
        fresh = client.run(item.cypher, read_only=True, limit_rows=PIPELINE_EXECUTION_ROW_LIMIT)
        stored = [json.dumps(row, sort_keys=True, default=str) for row in item.execution.rows[:JUDGE_VISIBLE_ROWS]]
        fresh_rows = {json.dumps(row, sort_keys=True, default=str) for row in fresh.rows}
        item.context_notes.append(
            "reexecution_stored_sample_subset_of_fresh_rows="
            + str(all(row in fresh_rows for row in stored)).lower()
        )
        item.context_notes.append(f"reexecution_row_count={len(fresh.rows)}")
        if not fresh.success:
            item.context_notes.append(f"reexecution_error={fresh.error}")
        item.execution = fresh
        item.result_row_count_observed = len(fresh.rows)
        item.context_source += "+reexecuted"


# ---------------------------------------------------------------------------
# Recording LLM wrapper and the re-judge runner
# ---------------------------------------------------------------------------


class RejudgeAborted(RuntimeError):
    def __init__(self, message: str, summary: dict[str, Any]) -> None:
        super().__init__(message)
        self.summary = summary


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
        return True
    if isinstance(exc, requests.exceptions.HTTPError):
        status = getattr(getattr(exc, "response", None), "status_code", None)
        return status is None or status >= 500 or status == 429
    return False


class RecordingJudgeLLM:
    """Wrap an OpenAI-compatible client to capture the judge call verbatim.

    ``LLMJudge`` swallows client errors and falls back to the deterministic
    judge. For re-judging, that fallback must be counted as a failed call, so
    this wrapper records the exact system/user prompt, raw response text,
    latency, retries, and the error kind. ``OpenAICompatibleLLM`` already
    retries transport errors, 429, and 5xx internally; ``request_retries`` adds
    optional wrapper-level retries on top (default 0), so an item counts as a
    failed call only after every retry is exhausted.
    """

    def __init__(
        self,
        inner: Any,
        *,
        request_retries: int = 0,
        retry_backoff_sec: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.inner = inner
        self.model = getattr(inner, "model", "unknown")
        self.request_retries = max(0, int(request_retries))
        self.retry_backoff_sec = retry_backoff_sec
        self.sleep = sleep
        self.system: str | None = None
        self.user: str | None = None
        self.call_kwargs: dict[str, Any] = {}
        self.text: str | None = None
        self.response_raw: dict[str, Any] | None = None
        self.error: str | None = None
        self.error_kind: str | None = None
        self.attempts = 0
        self.latency_ms: float | None = None
        self.calls = 0

    def chat(self, **kwargs: Any) -> Any:  # pragma: no cover - judge only uses chat_json
        return self.inner.chat(**kwargs)

    def chat_json(self, **kwargs: Any) -> Any:
        self.calls += 1
        self.system = kwargs.get("system")
        self.user = kwargs.get("user")
        self.call_kwargs = {
            key: value for key, value in kwargs.items() if key not in {"system", "user"}
        }
        started = time.perf_counter()
        response = None
        for attempt in range(self.request_retries + 1):
            self.attempts = attempt + 1
            try:
                response = self.inner.chat(**kwargs)
                break
            except Exception as exc:
                if attempt < self.request_retries and _is_retryable(exc):
                    self.sleep(self.retry_backoff_sec * (attempt + 1))
                    continue
                self.latency_ms = (time.perf_counter() - started) * 1000
                self.error_kind = "request_error"
                self.error = f"{type(exc).__name__}: {exc}"
                raise
        self.latency_ms = (time.perf_counter() - started) * 1000
        self.text = getattr(response, "text", None)
        self.response_raw = getattr(response, "raw", None)
        try:
            return json.loads(extract_json_text(self.text or ""))
        except Exception as exc:
            self.error_kind = "parse_error"
            self.error = f"{type(exc).__name__}: {exc}"
            raise


def judge_item(
    item: RejudgeItem,
    *,
    llm: Any,
    schema: SchemaSummary,
    judge_label: str,
    judge_model: str,
    judge_role: str,
    temperature: float = ORIGINAL_JUDGE_TEMPERATURE,
    max_tokens: int = ORIGINAL_JUDGE_MAX_TOKENS,
    request_retries: int = 0,
    retry_backoff_sec: float = 2.0,
    save_prompts: bool = True,
    system_message_mode: str = "separate",
    call_settings: dict[str, Any] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Judge one item through the unchanged ``LLMJudge`` path and log everything.

    ``call_settings`` (provider, send_temperature, reasoning_effort, ...) is
    copied into the row so every decision carries its transport settings.
    Secrets must never be placed in ``call_settings``.
    """

    recorder = RecordingJudgeLLM(
        llm,
        request_retries=request_retries,
        retry_backoff_sec=retry_backoff_sec,
        sleep=sleep,
    )
    judge = LLMJudge(recorder, DeterministicJudge(), temperature=temperature, max_tokens=max_tokens)
    started = time.perf_counter()
    result = None
    error: str | None = None
    error_kind: str | None = None
    try:
        result = judge.judge(
            question=item.question,
            cypher=item.cypher,
            schema=schema,
            validation=item.validation,
            execution=item.execution,
        )
    except Exception as exc:  # prompt construction happens outside LLMJudge's try block
        error = f"{type(exc).__name__}: {exc}"
        error_kind = "prompt_build_error"
    wall_ms = (time.perf_counter() - started) * 1000
    if result is not None:
        if recorder.error_kind:
            error = recorder.error
            error_kind = recorder.error_kind
        elif "fallback_after_error" in (result.raw or {}):
            error = str(result.raw.get("fallback_after_error"))
            error_kind = "judge_output_error"
        elif recorder.calls == 0:
            error = "judge did not call the LLM"
            error_kind = "no_llm_call"

    decided = error is None and result is not None
    raw_json = dict(result.raw) if (decided and result is not None) else None
    llm_decision = None
    guard_applied = False
    missing_keys: list[str] = []
    if raw_json is not None:
        llm_decision = bool(raw_json.get("pass", False))
        guard_applied = raw_json.get("override") == "categorical_result_value_guard"
        missing_keys = [
            key
            for key in (
                "pass",
                "ambiguity_score",
                "semantic_alignment_score",
                "schema_use_score",
                "difficulty",
                "failure_reason",
            )
            if key not in raw_json
        ]
    usage = (recorder.response_raw or {}).get("usage") if isinstance(recorder.response_raw, dict) else None
    row: dict[str, Any] = {
        "item_id": item.item_id,
        "item_source": item.item_source,
        "split": item.provenance.get("split", ""),
        "graph_profile": item.graph_profile,
        "category": item.category,
        "difficulty": item.difficulty,
        "primary_strategy": item.primary_strategy,
        "question": item.question,
        "cypher": item.cypher,
        "result_row_count_observed": item.result_row_count_observed,
        "execution_rows_shown": item.execution.rows[:JUDGE_VISIBLE_ROWS],
        "context_source": item.context_source,
        "context_notes": item.context_notes,
        "provenance": item.provenance,
        "original_judge": item.original,
        "judge_label": judge_label,
        "judge_model": judge_model,
        "judge_role": judge_role,
        "provider": (call_settings or {}).get("provider", "vllm"),
        "call_settings": dict(call_settings or {}),
        "system_message_mode": system_message_mode,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "decision": bool(result.passed) if decided and result is not None else None,
        "llm_decision": llm_decision,
        "categorical_guard_applied": guard_applied,
        "scores": (
            {
                "ambiguity_score": result.ambiguity_score,
                "semantic_alignment_score": result.semantic_alignment_score,
                "schema_use_score": result.schema_use_score,
                "difficulty": result.difficulty,
                "failure_reason": result.failure_reason,
            }
            if decided and result is not None
            else None
        ),
        "judge_output_missing_keys": missing_keys,
        "judge_raw_json": raw_json,
        "raw_response_text": recorder.text,
        "prompt_sha256": (
            judge_prompt_sha256(recorder.system or "", recorder.user or "") if recorder.user is not None else None
        ),
        "user_prompt_sha256": sha256_text(recorder.user) if recorder.user is not None else None,
        "judge_contract_sha256": judge_contract_sha256(),
        "request_attempts": recorder.attempts,
        "latency_ms": recorder.latency_ms,
        "wall_ms": wall_ms,
        "usage": usage,
        "error": error,
        "error_kind": error_kind,
        "created_at": utc_now(),
    }
    if save_prompts:
        row["judge_prompt_system"] = recorder.system
        row["judge_prompt_user"] = recorder.user
    return row


def _ordered_results(
    items: list[RejudgeItem],
    fn: Callable[[RejudgeItem], dict[str, Any]],
    concurrency: int,
) -> Iterator[tuple[RejudgeItem, dict[str, Any]]]:
    if concurrency <= 1:
        for item in items:
            yield item, fn(item)
        return
    executor = ThreadPoolExecutor(max_workers=concurrency)
    pending: deque[tuple[RejudgeItem, Future]] = deque()
    iterator = iter(items)
    try:
        for _ in range(concurrency * 2):
            nxt = next(iterator, None)
            if nxt is None:
                break
            pending.append((nxt, executor.submit(fn, nxt)))
        while pending:
            item, future = pending.popleft()
            result = future.result()
            nxt = next(iterator, None)
            if nxt is not None:
                pending.append((nxt, executor.submit(fn, nxt)))
            yield item, result
    finally:
        for _, future in pending:
            future.cancel()
        executor.shutdown(wait=True)


def run_rejudge(
    items: list[RejudgeItem],
    *,
    llm: Any,
    schemas: dict[str, SchemaSummary],
    output_path: str | Path,
    judge_label: str,
    judge_model: str,
    judge_role: str,
    temperature: float = ORIGINAL_JUDGE_TEMPERATURE,
    max_tokens: int = ORIGINAL_JUDGE_MAX_TOKENS,
    concurrency: int = 1,
    max_consecutive_errors: int = 5,
    max_error_rate: float = 0.01,
    request_retries: int = 0,
    retry_backoff_sec: float = 2.0,
    resume: bool = False,
    save_prompts: bool = True,
    system_message_mode: str = "separate",
    call_settings: dict[str, Any] | None = None,
    run_metadata: dict[str, Any] | None = None,
    skipped: list[SkippedItem] | None = None,
    progress: Callable[[str], None] | None = print,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Re-judge ``items`` and append one JSONL row per item to ``output_path``.

    Raises :class:`RejudgeAborted` after ``max_consecutive_errors`` failed calls
    in a row. Returns a summary whose ``status`` is ``complete`` or
    ``error_rate_exceeded`` (failed calls / targeted items > ``max_error_rate``).
    """

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    done: set[str] = set()
    if resume and out.exists():
        for row in read_jsonl(out):
            if row.get("error") is None and row.get("decision") is not None:
                done.add(str(row.get("item_id")))
    elif out.exists():
        raise FileExistsError(f"{out} exists; pass resume=True or choose a new output path")
    targets = [item for item in items if item.item_id not in done]
    started_at = utc_now()

    def _judge(item: RejudgeItem) -> dict[str, Any]:
        return judge_item(
            item,
            llm=llm,
            schema=schemas[item.graph_profile],
            judge_label=judge_label,
            judge_model=judge_model,
            judge_role=judge_role,
            temperature=temperature,
            max_tokens=max_tokens,
            request_retries=request_retries,
            retry_backoff_sec=retry_backoff_sec,
            save_prompts=save_prompts,
            system_message_mode=system_message_mode,
            call_settings=call_settings,
            sleep=sleep,
        )

    consecutive = 0
    failures = 0
    error_kinds: Counter[str] = Counter()
    decisions: Counter[str] = Counter()
    processed = 0
    summary: dict[str, Any] = {}

    def _summary(status: str) -> dict[str, Any]:
        targeted = len(targets)
        return {
            "status": status,
            "judge_label": judge_label,
            "judge_model": judge_model,
            "judge_role": judge_role,
            "provider": (call_settings or {}).get("provider", "vllm"),
            "call_settings": dict(call_settings or {}),
            "output": str(out),
            "items_total": len(items),
            "items_already_done": len(done),
            "items_targeted": targeted,
            "items_processed": processed,
            "failed_calls": failures,
            "failed_call_rate": failures / targeted if targeted else 0.0,
            "max_error_rate": max_error_rate,
            "error_kinds": dict(error_kinds),
            "decisions": dict(decisions),
            "skipped_items": len(skipped or []),
            "skipped_reasons": dict(Counter(item.reason.split(":")[0] for item in (skipped or []))),
            "started_at": started_at,
            "finished_at": utc_now(),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "concurrency": concurrency,
            "request_retries": request_retries,
            "judge_contract_sha256": judge_contract_sha256(),
            "system_prompt_sha256": sha256_text(SYSTEM_JSON_ENGINEER),
            **(run_metadata or {}),
        }

    for item, row in _ordered_results(targets, _judge, concurrency):
        append_jsonl(out, row)
        processed += 1
        if row["error"] is not None:
            failures += 1
            consecutive += 1
            error_kinds[str(row["error_kind"])] += 1
        else:
            consecutive = 0
            decisions["pass" if row["decision"] else "fail"] += 1
        if progress:
            status = f"error:{row['error_kind']}" if row["error"] else ("pass" if row["decision"] else "fail")
            progress(f"{processed}/{len(targets)} {item.item_id} {item.graph_profile} {status}")
        if consecutive >= max_consecutive_errors:
            summary = _summary("aborted_consecutive_failures")
            summary["last_error"] = row["error"]
            raise RejudgeAborted(
                f"aborting after {consecutive} consecutive failed judge calls "
                f"(last error: {row['error']}); partial output at {out} is not a judge result",
                summary,
            )
    status = "complete"
    if targets and failures / len(targets) > max_error_rate:
        status = "error_rate_exceeded"
    summary = _summary(status)
    return summary


def summary_path_for(output_path: str | Path) -> Path:
    out = Path(output_path)
    return out.with_name(out.stem + ".summary.json")


def write_skipped_log(path: str | Path, skipped: list[SkippedItem]) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for item in skipped:
            f.write(
                json.dumps(
                    {"item_key": item.item_key, "item_source": item.item_source, "reason": item.reason},
                    ensure_ascii=False,
                )
                + "\n"
            )


def assert_hosted_graphs_public(graphs: Iterable[str]) -> None:
    """Hosted judges may only receive public LDBC study graphs (never tenant data)."""

    disallowed = sorted({str(graph) for graph in graphs} - PUBLIC_HOSTED_GRAPHS)
    if disallowed:
        raise ValueError(
            f"hosted provider refused for graph_profile(s) {disallowed}; hosted judges are limited to "
            f"public LDBC graphs {sorted(PUBLIC_HOSTED_GRAPHS)}"
        )


def assert_local_endpoint(base_url: str) -> None:
    """Refuse well-known hosted API hosts; judges must serve local weights."""

    host = (urlparse(base_url).hostname or "").lower()
    if not host:
        raise ValueError(f"cannot parse host from base URL {base_url!r}")
    for suffix in HOSTED_API_HOST_SUFFIXES:
        if host == suffix or host.endswith("." + suffix):
            raise ValueError(
                f"{base_url} looks like a hosted API ({host}); PIPE-Cypher judges must be "
                "local weights behind a project-controlled OpenAI-compatible endpoint"
            )


def preflight_judge_endpoint(
    base_url: str,
    model: str,
    *,
    provider: str = "vllm",
    timeout_sec: int = 30,
) -> list[str]:
    """Abort before any judge call unless ``model`` is served at ``base_url``.

    ``provider="vllm"`` additionally refuses well-known hosted API hosts, so a
    local-weights judge cannot silently be pointed at a vendor endpoint.
    """

    if provider == "vllm":
        assert_local_endpoint(base_url)
    elif provider in ("openai", "openrouter"):
        if resolve_api_key(provider) == "EMPTY":
            raise RuntimeError(
                f"provider={provider} needs its API key (OPENAI_API_KEY / OPENROUTER_API_KEY) in the environment"
            )
    else:
        raise ValueError(f"unknown provider {provider!r}")
    return assert_model_served(base_url, model, timeout_sec=timeout_sec, provider=provider)


def default_judge_label(model: str) -> str:
    label = model.rstrip("/").split("/")[-1]
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", label) or "judge"


def default_judge_role(model: str) -> str:
    return "same_family_control" if "qwen" in model.lower() else "independent"


# ---------------------------------------------------------------------------
# Agreement analysis over re-judge outputs
# ---------------------------------------------------------------------------


@dataclass
class JudgeRun:
    label: str
    model: str
    role: str
    provider: str
    path: str
    rows_by_id: dict[str, dict[str, Any]]
    duplicate_rows: int
    sha256: str


def load_rejudge_file(path: str | Path, *, label: str | None = None) -> JudgeRun:
    rows = read_jsonl(path)
    if not rows:
        raise ValueError(f"rejudge file is empty: {path}")
    labels = {str(row.get("judge_label")) for row in rows}
    if label is None:
        if len(labels) != 1:
            raise ValueError(f"{path} mixes judge labels {sorted(labels)}; pass label=path to disambiguate")
        label = labels.pop()
    models = Counter(str(row.get("judge_model")) for row in rows)
    roles = Counter(str(row.get("judge_role") or "independent") for row in rows)
    providers = Counter(str(row.get("provider") or "vllm") for row in rows)
    by_id: dict[str, dict[str, Any]] = {}
    duplicates = 0
    for row in rows:
        item_id = str(row.get("item_id"))
        if item_id in by_id:
            duplicates += 1
            previous = by_id[item_id]
            # Prefer the latest decided row (resume appends retries).
            if row.get("decision") is None and previous.get("decision") is not None:
                continue
        by_id[item_id] = row
    return JudgeRun(
        label=label,
        model=models.most_common(1)[0][0],
        role=roles.most_common(1)[0][0],
        provider=providers.most_common(1)[0][0],
        path=str(path),
        rows_by_id=by_id,
        duplicate_rows=duplicates,
        sha256=sha256_file(path),
    )


def original_decisions_from_sources(
    benchmark_paths: Iterable[str | Path] = (),
    records_paths: Iterable[str | Path] = (),
    *,
    split: str = "all",
) -> dict[str, dict[str, Any]]:
    """Original judge decisions keyed by item id from exports and/or records."""

    decisions: dict[str, dict[str, Any]] = {}
    for path in benchmark_paths:
        for row in load_benchmark_rows(path, split):
            gates = row.get("gates") or {}
            decisions[str(row.get("id"))] = {
                "decision": bool(gates.get("judge_pass")),
                "decision_source": "export_gates",
            }
    for record in load_records_files(records_paths):
        original = record_original_judgement(record)
        if original["decision"] is None:
            continue
        decisions.setdefault(
            benchmark_id(record),
            {"decision": original["decision"], "decision_source": original["decision_source"]},
        )
    return decisions


def analyze_judge_agreement(
    runs: list[JudgeRun],
    *,
    original_override: dict[str, dict[str, Any]] | None = None,
    original_label: str = "original_judge",
) -> dict[str, Any]:
    if not runs:
        raise ValueError("at least one rejudge run is required")
    labels = [run.label for run in runs]
    if len(set(labels)) != len(labels) or original_label in labels:
        raise ValueError(f"judge labels must be unique and differ from {original_label!r}: {labels}")

    # Item universe and metadata come from the union of re-judge rows.
    meta: dict[str, dict[str, Any]] = {}
    for run in runs:
        for item_id, row in run.rows_by_id.items():
            meta.setdefault(item_id, row)

    original: dict[str, bool] = {}
    original_sources: Counter[str] = Counter()
    original_source_by_id: dict[str, str] = {}
    for item_id, row in meta.items():
        info = (original_override or {}).get(item_id) or row.get("original_judge") or {}
        decision = info.get("decision")
        if decision is None:
            continue
        original[item_id] = bool(decision)
        source = str(info.get("decision_source") or "unknown")
        original_sources[source] += 1
        original_source_by_id[item_id] = source

    decisions: dict[str, dict[str, bool]] = {original_label: original}
    for run in runs:
        decisions[run.label] = {
            item_id: bool(row["decision"])
            for item_id, row in run.rows_by_id.items()
            if row.get("decision") is not None and row.get("error") is None
        }
    roles = {original_label: "original", **{run.label: run.role for run in runs}}
    models = {
        original_label: Counter(
            str((row.get("original_judge") or {}).get("source_model")) for row in meta.values()
        ).most_common(1)[0][0],
        **{run.label: run.model for run in runs},
    }
    independent = [run.label for run in runs if run.role == "independent"]
    all_labels = [original_label, *labels]

    judges_summary = []
    for label in all_labels:
        decided = decisions[label]
        passes = sum(1 for value in decided.values() if value)
        entry: dict[str, Any] = {
            "label": label,
            "model": models[label],
            "role": roles[label],
            "provider": "vllm" if label == original_label else next(r.provider for r in runs if r.label == label),
            "items": len(meta),
            "decided": len(decided),
            "pass_rate": rate_with_ci(passes, len(decided)),
        }
        if label != original_label:
            run = next(r for r in runs if r.label == label)
            errors = Counter(
                str(row.get("error_kind")) for row in run.rows_by_id.values() if row.get("error") is not None
            )
            entry.update(
                {
                    "provider": run.provider,
                    "path": run.path,
                    "sha256": run.sha256,
                    "errors": sum(errors.values()),
                    "error_kinds": dict(errors),
                    "missing_items": len(meta) - len(run.rows_by_id),
                    "duplicate_rows": run.duplicate_rows,
                    "categorical_guard_applied": sum(
                        1 for row in run.rows_by_id.values() if row.get("categorical_guard_applied")
                    ),
                    "context_sources": dict(
                        Counter(str(row.get("context_source")) for row in run.rows_by_id.values())
                    ),
                    "prompt_contracts": sorted(
                        {str(row.get("judge_contract_sha256")) for row in run.rows_by_id.values()}
                    ),
                }
            )
        judges_summary.append(entry)

    item_sources = {item_id: str(row.get("item_source") or "unknown") for item_id, row in meta.items()}

    def _pairs(a: str, b: str, ids: Iterable[str] | None = None) -> list[tuple[bool, bool]]:
        pool = set(decisions[a]) & set(decisions[b])
        if ids is not None:
            pool &= set(ids)
        return [(decisions[a][i], decisions[b][i]) for i in sorted(pool)]

    vs_original: dict[str, Any] = {}
    for label in labels:
        entry = binary_confusion(_pairs(original_label, label))
        entry["by_item_source"] = {
            source: binary_confusion(
                _pairs(original_label, label, [i for i, s in item_sources.items() if s == source])
            )
            for source in sorted(set(item_sources.values()))
        }
        entry["by_original_decision_source"] = {
            source: binary_confusion(
                _pairs(original_label, label, [i for i, s in original_source_by_id.items() if s == source])
            )
            for source in sorted(set(original_source_by_id.values()))
        }
        vs_original[label] = entry

    pairwise = []
    for a, b in combinations(all_labels, 2):
        pairs = _pairs(a, b)
        conf = binary_confusion(pairs)
        pairwise.append(
            {
                "judge_a": a,
                "judge_b": b,
                "n": conf["n"],
                "agreement": conf["agreement"],
                "cohen_kappa": conf["cohen_kappa"],
                "gwet_ac1": conf["gwet_ac1"],
            }
        )

    def _fleiss(group: list[str]) -> dict[str, Any]:
        if len(group) < 2:
            return {"judges": group, "n_items": 0, "kappa": None}
        common = set.intersection(*(set(decisions[label]) for label in group))
        ratings = [[decisions[label][i] for label in group] for i in sorted(common)]
        return {"judges": group, "n_items": len(ratings), "kappa": fleiss_kappa_from_ratings(ratings)}

    fleiss = {
        "all_judges": _fleiss(all_labels),
        "independent_judges": _fleiss(independent),
        "original_plus_independent": _fleiss([original_label, *independent]),
    }

    def _slice(key_fn: Callable[[dict[str, Any]], str]) -> dict[str, Any]:
        groups: dict[str, list[str]] = defaultdict(list)
        for item_id, row in meta.items():
            groups[key_fn(row)].append(item_id)
        out: dict[str, Any] = {}
        for key in sorted(groups):
            ids = groups[key]
            out[key] = {}
            for label in all_labels:
                decided = [decisions[label][i] for i in ids if i in decisions[label]]
                out[key][label] = rate_with_ci(sum(1 for value in decided if value), len(decided))
        return out

    slices = {
        "by_graph": _slice(lambda row: str(row.get("graph_profile"))),
        "by_category": _slice(lambda row: str(row.get("category"))),
        "by_graph_category": _slice(lambda row: f"{row.get('graph_profile')}::{row.get('category')}"),
        "by_difficulty": _slice(lambda row: str(row.get("difficulty"))),
        "by_item_source": _slice(lambda row: str(row.get("item_source"))),
    }

    flagged_counts: dict[str, int] = {}
    rescued_counts: dict[str, int] = {}
    for item_id in meta:
        fails = sum(1 for label in independent if decisions[label].get(item_id) is False)
        passes = sum(1 for label in independent if decisions[label].get(item_id) is True)
        if original.get(item_id) is True and fails:
            flagged_counts[item_id] = fails
        if original.get(item_id) is False and passes:
            rescued_counts[item_id] = passes
    original_pass_ids = [i for i, value in original.items() if value]
    all_independent_decided = [
        i for i in original_pass_ids if all(i in decisions[label] for label in independent)
    ]
    flags = {
        "independent_judges": independent,
        "original_pass_items": len(original_pass_ids),
        "flagged_by_any_independent": len(flagged_counts),
        "flagged_by_any_independent_rate": rate_with_ci(len(flagged_counts), len(original_pass_ids)),
        "flagged_by_at_least_2_independent": sum(1 for v in flagged_counts.values() if v >= 2),
        "flagged_by_all_independent": sum(
            1 for i in all_independent_decided if flagged_counts.get(i, 0) == len(independent) and independent
        ),
        "original_pass_items_decided_by_all_independent": len(all_independent_decided),
        "original_fail_items": len(original) - len(original_pass_ids),
        "rescued_by_any_independent": len(rescued_counts),
        "flagged_ids": sorted(flagged_counts),
        "rescued_ids": sorted(rescued_counts),
    }

    return {
        "privacy": "Aggregate metrics only; item ids are hashes. Disagreement CSVs are PRIVATE/internal.",
        "generated_at": utc_now(),
        "original_label": original_label,
        "judges": judges_summary,
        "items": {
            "n_items": len(meta),
            "by_item_source": dict(Counter(item_sources.values())),
            "original_decision_sources": dict(original_sources),
            "original_decided": len(original),
        },
        "vs_original": vs_original,
        "pairwise": pairwise,
        "fleiss": fleiss,
        "slices": slices,
        "flags": flags,
        "notes": [
            "Cohen's kappa is undefined (null) when a judge is constant on the compared items; "
            "on accepted-only item sets the original judge passes everything, so report flag rates "
            "and Gwet's AC1 alongside kappa, and include judge-decided rejected candidates.",
            "Items whose call failed (request/parse/judge-output errors) are excluded per judge and "
            "counted under errors; they are never replaced by the deterministic fallback.",
        ],
    }


def judge_disagreement_rows(
    runs: list[JudgeRun],
    report: dict[str, Any],
    *,
    preview_rows: int = 3,
    original_override: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Rows where the judges (original + re-judges) are not unanimous."""

    original_label = report["original_label"]
    labels = [run.label for run in runs]
    independent = report["flags"]["independent_judges"]
    meta: dict[str, dict[str, Any]] = {}
    for run in runs:
        for item_id, row in run.rows_by_id.items():
            meta.setdefault(item_id, row)
    rows: list[dict[str, Any]] = []
    for item_id, base in meta.items():
        original_info = (original_override or {}).get(item_id) or base.get("original_judge") or {}
        original = original_info.get("decision")
        values: dict[str, bool | None] = {original_label: original}
        reasons: dict[str, str] = {original_label: str((base.get("original_judge") or {}).get("failure_reason") or "")}
        for run in runs:
            row = run.rows_by_id.get(item_id)
            decided = row is not None and row.get("error") is None and row.get("decision") is not None
            values[run.label] = bool(row["decision"]) if decided else None
            reasons[run.label] = str(((row or {}).get("scores") or {}).get("failure_reason") or "")
        observed = {value for value in values.values() if value is not None}
        if len(observed) < 2:
            continue
        independent_fail = sum(1 for label in independent if values.get(label) is False)
        independent_decided = sum(1 for label in independent if values.get(label) is not None)
        out: dict[str, Any] = {
            "item_id": item_id,
            "item_source": base.get("item_source", ""),
            "split": base.get("split", ""),
            "graph_profile": base.get("graph_profile", ""),
            "category": base.get("category", ""),
            "difficulty": base.get("difficulty", ""),
            "original_decision_source": original_info.get("decision_source", ""),
            "n_independent_fail": independent_fail,
            "n_independent_decided": independent_decided,
            "question": base.get("question", ""),
            "cypher": base.get("cypher", ""),
            "result_row_count_observed": base.get("result_row_count_observed", ""),
            "result_rows_preview": rows_preview(base.get("execution_rows_shown") or [], k=preview_rows),
            "adjudicated_reference_correct": "",
            "adjudicated_question_unambiguous": "",
            "adjudicated_error_type": "",
            "adjudicator": "",
            "adjudication_notes": "",
        }
        for label in [original_label, *labels]:
            out[f"{label}__decision"] = format_bool(values[label]) if values[label] is not None else "error/missing"
            out[f"{label}__failure_reason"] = reasons[label]
        rows.append(out)
    rows.sort(
        key=lambda row: (
            0 if row[f"{original_label}__decision"] == "yes" else 1,
            -int(row["n_independent_fail"]),
            str(row["graph_profile"]),
            str(row["category"]),
            str(row["item_id"]),
        )
    )
    fieldnames = [
        "item_id",
        "item_source",
        "split",
        "graph_profile",
        "category",
        "difficulty",
        "original_decision_source",
        "n_independent_fail",
        "n_independent_decided",
    ]
    for label in [original_label, *labels]:
        fieldnames.extend([f"{label}__decision", f"{label}__failure_reason"])
    fieldnames.extend(
        [
            "question",
            "cypher",
            "result_row_count_observed",
            "result_rows_preview",
            "adjudicated_reference_correct",
            "adjudicated_question_unambiguous",
            "adjudicated_error_type",
            "adjudicator",
            "adjudication_notes",
        ]
    )
    return rows, fieldnames


def _fmt_rate(entry: dict[str, Any] | None) -> str:
    if not entry or entry.get("rate") is None:
        return "--"
    low, high = entry["ci95"]
    return f"{100 * entry['rate']:.1f}% [{100 * low:.1f}, {100 * high:.1f}]"


def _fmt_num(value: Any, digits: int = 3) -> str:
    if value is None:
        return "--"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def render_agreement_markdown(report: dict[str, Any]) -> str:
    original_label = report["original_label"]
    lines = [
        "# Independent Judge Agreement",
        "",
        f"Generated: {report['generated_at']}",
        "",
        f"Items: {report['items']['n_items']} "
        f"(by source: {json.dumps(report['items']['by_item_source'], sort_keys=True)}); "
        f"original decision sources: {json.dumps(report['items']['original_decision_sources'], sort_keys=True)}",
        "",
        "## Judges",
        "",
        "| Judge | Model | Provider | Role | Decided | Pass rate [95% CI] | Errors |",
        "| --- | --- | --- | --- | ---: | --- | ---: |",
    ]
    for judge in report["judges"]:
        lines.append(
            f"| {judge['label']} | {judge['model']} | {judge['provider']} | {judge['role']} | "
            f"{judge['decided']}/{judge['items']} | "
            f"{_fmt_rate(judge['pass_rate'])} | {judge.get('errors', 0)} |"
        )
    lines += [
        "",
        f"## Agreement with {original_label}",
        "",
        "| Judge | n | Agree | Cohen kappa | Gwet AC1 | Orig pass -> fail | Flag rate [95% CI] | Orig fail -> pass |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |",
    ]
    for label, entry in report["vs_original"].items():
        flag = (
            f"{100 * entry['flag_rate_among_reference_pass']:.1f}% "
            f"[{100 * entry['flag_rate_ci95'][0]:.1f}, {100 * entry['flag_rate_ci95'][1]:.1f}]"
            if entry["flag_rate_among_reference_pass"] is not None
            else "--"
        )
        lines.append(
            f"| {label} | {entry['n']} | {_fmt_num(entry['agreement'])} | {_fmt_num(entry['cohen_kappa'])} | "
            f"{_fmt_num(entry['gwet_ac1'])} | {entry['reference_pass_other_fail']} | {flag} | "
            f"{entry['reference_fail_other_pass']} |"
        )
    lines += ["", "### By item source", ""]
    for label, entry in report["vs_original"].items():
        for source, conf in entry["by_item_source"].items():
            lines.append(
                f"- {label} / {source}: n={conf['n']}, agree={_fmt_num(conf['agreement'])}, "
                f"kappa={_fmt_num(conf['cohen_kappa'])}, AC1={_fmt_num(conf['gwet_ac1'])}, "
                f"orig pass->fail={conf['reference_pass_other_fail']}, orig fail->pass={conf['reference_fail_other_pass']}"
            )
    lines += ["", "### By original decision source", ""]
    for label, entry in report["vs_original"].items():
        for source, conf in entry["by_original_decision_source"].items():
            lines.append(
                f"- {label} / {source}: n={conf['n']}, orig pass->fail={conf['reference_pass_other_fail']}, "
                f"orig fail->pass={conf['reference_fail_other_pass']}"
            )
    lines += ["", "## Pairwise agreement", "", "| Judge A | Judge B | n | Agree | Cohen kappa | Gwet AC1 |", "| --- | --- | ---: | ---: | ---: | ---: |"]
    for pair in report["pairwise"]:
        lines.append(
            f"| {pair['judge_a']} | {pair['judge_b']} | {pair['n']} | {_fmt_num(pair['agreement'])} | "
            f"{_fmt_num(pair['cohen_kappa'])} | {_fmt_num(pair['gwet_ac1'])} |"
        )
    lines += ["", "## Fleiss' kappa", ""]
    for name, entry in report["fleiss"].items():
        lines.append(f"- {name} ({', '.join(entry['judges'])}): n={entry['n_items']}, kappa={_fmt_num(entry['kappa'])}")
    flags = report["flags"]
    lines += [
        "",
        "## Flagged items",
        "",
        f"- Original-pass items: {flags['original_pass_items']}",
        f"- Flagged (fail) by any independent judge: {flags['flagged_by_any_independent']} "
        f"({_fmt_rate(flags['flagged_by_any_independent_rate'])})",
        f"- Flagged by at least 2 independent judges: {flags['flagged_by_at_least_2_independent']}",
        f"- Flagged by all independent judges: {flags['flagged_by_all_independent']} "
        f"(of {flags['original_pass_items_decided_by_all_independent']} decided by all)",
        f"- Original-fail items passed by any independent judge: {flags['rescued_by_any_independent']} "
        f"(of {flags['original_fail_items']})",
        "",
    ]
    for slice_name in ("by_graph", "by_category"):
        lines += [f"## Pass rate {slice_name.replace('_', ' ')}", ""]
        labels = [judge["label"] for judge in report["judges"]]
        lines.append("| Slice | " + " | ".join(labels) + " |")
        lines.append("| --- | " + " | ".join("---" for _ in labels) + " |")
        for key, per_judge in report["slices"][slice_name].items():
            lines.append(
                f"| {key} | "
                + " | ".join(
                    f"{per_judge[label]['count']}/{per_judge[label]['n']}" if per_judge[label]["n"] else "--"
                    for label in labels
                )
                + " |"
            )
        lines.append("")
    lines += ["## Notes", ""] + [f"- {note}" for note in report["notes"]] + [""]
    return "\n".join(lines)


def render_agreement_latex(report: dict[str, Any], *, label: str = "tab:independent_judge_agreement") -> str:
    original_label = report["original_label"]
    lines = [
        r"\begin{table}[t]",
        r"\centering",
        r"\small",
        r"\setlength{\tabcolsep}{4pt}",
        r"\begin{tabular}{lrrrrr}",
        r"\toprule",
        r"Judge & Decided & Pass rate [95\% CI] & Agree & $\kappa$ & AC1 \\",
        r"\midrule",
    ]
    for judge in report["judges"]:
        rate = judge["pass_rate"]
        rate_text = (
            f"{100 * rate['rate']:.1f} [{100 * rate['ci95'][0]:.1f}, {100 * rate['ci95'][1]:.1f}]"
            if rate["rate"] is not None
            else "--"
        )
        if judge["label"] == original_label:
            agree = kappa = ac1 = "--"
        else:
            entry = report["vs_original"][judge["label"]]
            agree = _fmt_num(entry["agreement"])
            kappa = _fmt_num(entry["cohen_kappa"])
            ac1 = _fmt_num(entry["gwet_ac1"])
        lines.append(
            f"{tex_escape(judge['label'])} & {judge['decided']} & {rate_text} & {agree} & {kappa} & {ac1} \\\\"
        )
    fleiss = report["fleiss"]["all_judges"]
    flags = report["flags"]
    lines += [
        r"\midrule",
        (
            rf"\multicolumn{{6}}{{l}}{{Fleiss' $\kappa$ (all judges, $n={fleiss['n_items']}$): {_fmt_num(fleiss['kappa'])}; "
            rf"original-pass items flagged by $\geq$1 independent judge: {flags['flagged_by_any_independent']}/{flags['original_pass_items']}}} \\"
        ),
        r"\bottomrule",
        r"\end{tabular}",
        (
            r"\caption{Cross-family re-judging with the unchanged judge prompt contract. Agreement, "
            r"Cohen's $\kappa$, and Gwet's AC1 are computed against the original judge on items both "
            r"judges decided; failed calls are excluded, not replaced.}"
        ),
        rf"\label{{{label}}}",
        r"\end{table}",
        "",
    ]
    return "\n".join(lines)


def render_agreement_slices_latex(
    report: dict[str, Any],
    *,
    slice_name: str = "by_category",
    label: str = "tab:independent_judge_agreement_slices",
) -> str:
    judges = [judge["label"] for judge in report["judges"]]
    lines = [
        r"\begin{table}[t]",
        r"\centering",
        r"\small",
        r"\begin{tabular}{l" + "r" * len(judges) + "}",
        r"\toprule",
        "Slice & " + " & ".join(tex_escape(j) for j in judges) + r" \\",
        r"\midrule",
    ]
    for key, per_judge in report["slices"][slice_name].items():
        cells = []
        for judge in judges:
            entry = per_judge[judge]
            cells.append(f"{100 * entry['rate']:.1f}" if entry["rate"] is not None else "--")
        lines.append(f"{tex_escape(key)} & " + " & ".join(cells) + r" \\")
    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        rf"\caption{{Judge pass rate (\%) {tex_escape(slice_name.replace('_', ' '))}.}}",
        rf"\label{{{label}}}",
        r"\end{table}",
        "",
    ]
    return "\n".join(lines)

