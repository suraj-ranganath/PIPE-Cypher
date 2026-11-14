#!/usr/bin/env python3
"""Collect every number the NAACL 2027 paper needs from the v3 build into one JSON.

Reads completed artifacts only: build run records, template proposals, run
summaries, spend ledgers, benchmark exports, export-level audits, downstream
evaluation JSONL, the gpt-6-luna checklist audit, and generator-swap replays.
It never calls a model, a graph, or any network service.

Every section tolerates missing inputs and records ``{"missing": [paths]}``
instead of failing, so the script can be re-run while results arrive. Records
files that are still being appended to are read up to the last parsable line
(skipped lines are counted under ``bad_lines``). Downstream runs that do not
cover their expected item set, or whose prediction-failure rate exceeds 1%,
are reported but excluded from medians, intervals, and rank analyses.

Sections: build (A), export (B), downstream (C), stability (D),
rank_agreement (E), audit (F), genswap (G), gen9b_vs_full (H), hosted_spend.

Example (pilot):
  python scripts/collect_naacl_v3_results.py --main-prefix naacl_v3_pilot1 \\
      --main-export naacl_v3_pilot1 --all-eval-prefix naacl_v3_pilot1_harness \\
      --heldout-eval-prefix naacl_v3_pilot1_harness \\
      --audit-file artifacts/naacl_v3/audit/pilot1_gpt6luna_test.jsonl \\
      --genswap-replay 'qwen9b=artifacts/naacl_v3/genswap/pilot1_*.jsonl' \\
      --output /tmp/v3_pilot_results.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import re
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.diversity_metrics import (
    benchmark_diversity_report,
    canonical_query_signature,
    distinct_n,
    expected_distinct_ratio,
    self_bleu,
)
from pipecypher.downstream_model_transfer import MAX_PREDICTION_FAILURE_RATE
from pipecypher.eval_statistics import (
    EvaluationRun,
    analyze_models,
    analyze_rank_agreement,
    analyze_self_preference,
    kendall_tau_b,
    spearman_rho,
    to_jsonable,
)

CATEGORIES = (
    "simple_retrieval", "complex_retrieval", "simple_aggregation", "complex_aggregation",
    "boolean_existence", "negation_difference", "path_temporal", "ranking_topk",
)
MODELS = (
    "glm53_flash", "qwen35_9b", "llama31_8b", "gemma3_4b", "gemma3_12b", "gemma4_26b_a4b",
    "phi4", "mistral_small32_24b", "gpt_oss_20b", "qwen3_coder_30b_a3b", "gpt6_luna",
)
TIERS = ("easy", "medium", "hard")
SELF_BLEU_SAMPLE = 200  # same deterministic sample as diversity_v2.json / Table tab:diversity
EX_METRICS = ("execution_accuracy", "projected_execution_accuracy")
FUNNEL_BUCKETS = (
    "slot bindings unavailable/exhausted",
    "schema/syntax/validation",
    "execution error",
    "empty result",
    "truncated unordered LIMIT",
    "truncated default LIMIT",
    "LIMIT tie",
    "literal mismatch",
    "category contract",
    "structural defect",
    "tier quota",
    "signature quota/duplicate/entity cap",
    "LLM judge error (fail-closed)",
    "LLM panel reject",
    "other",
)
# v1 baseline, transcribed from paper_naacl2027_industry/main.tex Table tab:diversity
# (exact text values from artifacts/naacl_results/diversity_v1.json where the table rounds).
V1_DIVERSITY = {
    "source": "paper_naacl2027_industry/main.tex Table tab:diversity (+ artifacts/naacl_results/diversity_v1.json)",
    "total": 3000,
    "per_category": {"finbench": 250, "snb": 125},
    "unique_signatures": 123,
    "template_families": 36,
    "question_templates": 123,
    "signatures_per_cell": {"min": 1, "median": 1},
    "top10_signature_share": 0.673,
    "distinct_2": 0.08546162009197028,
    "ead_distinct_2": 0.26608284270434984,
    "self_bleu_2_sampled": 0.8129828626589073,
    "tier_share_pct": {"easy": 52, "medium": 48, "hard": 0},
    "test_sharing_train_signature": {"shared": 289, "test": 296},
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], int]:
    """Rows plus the number of unparsable lines (a file may still be written to)."""

    rows: list[dict[str, Any]] = []
    bad = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows, bad


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def share(part: float, whole: float) -> float | None:
    return part / whole if whole else None


def rate(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [row.get(key) for row in rows if row.get(key) is not None]
    if not values:
        return None
    return sum(float(v) for v in values) / len(values)


def kappa(pairs: list[tuple[bool, bool]]) -> float | None:
    if not pairs:
        return None
    n = len(pairs)
    agree = sum(a == b for a, b in pairs) / n
    pa = sum(a for a, _ in pairs) / n
    pb = sum(b for _, b in pairs) / n
    expected = pa * pb + (1 - pa) * (1 - pb)
    return None if expected >= 1 else (agree - expected) / (1 - expected)


def agreement(pairs: list[tuple[bool, bool]]) -> dict[str, Any]:
    """Raw agreement, Cohen's kappa, and PABAK (kappa collapses when nearly everything passes)."""

    n = len(pairs)
    raw = share(sum(a == b for a, b in pairs), n)
    return {
        "n": n,
        "raw_agreement": raw,
        "cohen_kappa": kappa(pairs),
        "pabak": 2 * raw - 1 if raw is not None else None,
        "both_pass": sum(a and b for a, b in pairs),
        "both_fail": sum((not a) and (not b) for a, b in pairs),
        "first_only_pass": sum(a and not b for a, b in pairs),
        "second_only_pass": sum(b and not a for a, b in pairs),
    }


def parse_ts(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(str(value)).timestamp()
    except ValueError:
        return None


def iso(ts: float | None) -> str | None:
    return dt.datetime.fromtimestamp(ts, tz=dt.UTC).isoformat() if ts is not None else None


def ranked(counter: Counter, top: int | None = None) -> dict[str, int]:
    return {str(k): v for k, v in counter.most_common(top)}


def median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def seed_of_run(run_name: str) -> int | None:
    match = re.search(r"_s(\d+)_", str(run_name or ""))
    return int(match.group(1)) if match else None


def guarded(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run one analysis; a failure is reported in place, never hidden or fatal."""

    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return {"error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# A. Build runs
# ---------------------------------------------------------------------------


@dataclass
class Cell:
    name: str
    path: Path
    stamp: str
    cfg: str
    seed: int
    category: str
    records: list[dict[str, Any]] = field(default_factory=list)
    templates: list[dict[str, Any]] = field(default_factory=list)
    bad_lines: int = 0
    summary: dict[str, Any] | None = None
    launch_target: int | None = None
    exit_code: int | None = None

    @property
    def graph(self) -> str:
        graphs = Counter(str(r.get("graph_profile")) for r in self.records if r.get("graph_profile"))
        if graphs:
            return graphs.most_common(1)[0][0]
        if self.summary and self.summary.get("graph_profile"):
            return str(self.summary["graph_profile"])
        return graph_from_cfg(self.cfg)

    @property
    def summary_target(self) -> int | None:
        by_cat = ((self.summary or {}).get("attempt_summary") or {}).get("by_category") or {}
        value = (by_cat.get(self.category) or {}).get("target")
        return int(value) if value is not None else None

    @property
    def target(self) -> int | None:
        """summary.txt when the cell finished, else the launch command's --target-per-category."""

        return self.summary_target if self.summary_target is not None else self.launch_target


def graph_from_cfg(cfg: str) -> str:
    """Fallback only (cells without records): finbench_v3 -> finbench, t2c_fincen_v3 -> t2c_fincen."""

    parts = cfg.split("_")
    return "_".join(parts[:2]) if parts[0] == "t2c" and len(parts) > 1 else parts[0]


def parse_summary(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    out: dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if not sep:
            continue
        if key == "attempt_summary":
            try:
                out[key] = json.loads(value)
            except json.JSONDecodeError:
                out[key] = None
        else:
            out[key] = value
    return out


def launch_info(logs_root: Path, prefix: str) -> dict[str, Any]:
    """Per-run targets from logs/<prefix>/launch_commands.txt plus the launch manifest lines."""

    targets: dict[str, int] = {}
    commands = logs_root / prefix / "launch_commands.txt"
    if commands.exists():
        for line in commands.read_text(encoding="utf-8").splitlines():
            name = re.search(r"--run-name\s+(\S+)", line)
            target = re.search(r"--target-per-category\s+(\d+)", line)
            if name and target:
                targets[name.group(1)] = int(target.group(1))
    manifest = {}
    manifest_path = logs_root / prefix / "launch_manifest.txt"
    if manifest_path.exists():
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key in ("prefix", "started", "finished", "code_tree_sha256", "git_head"):
                manifest[key] = value.split(" ")[0] if key == "prefix" else value
    return {"targets": targets, "manifest": manifest}


def cell_exit_code(logs_root: Path, prefix: str, cell: Cell) -> int | None:
    log = logs_root / prefix / f"{cell.cfg}_s{cell.seed}_{cell.category}.log"
    if not log.exists():
        return None
    with log.open("rb") as handle:
        handle.seek(0, 2)
        handle.seek(max(0, handle.tell() - 400))
        tail = handle.read().decode("utf-8", errors="replace")
    codes = re.findall(r"EXIT=(\d+)", tail)
    return int(codes[-1]) if codes else None


def discover_cells(runs_root: Path, prefix: str, logs_root: Path | None = None) -> tuple[list[Cell], list[str]]:
    """One Cell per (cfg, seed, category); older reruns of a cell are reported as superseded."""

    pattern = re.compile(
        rf"^(?P<stamp>\d{{8}}_\d{{6}})_{re.escape(prefix)}_(?P<cfg>.+)_s(?P<seed>\d+)_(?P<cat>{'|'.join(CATEGORIES)})$"
    )
    latest: dict[tuple[str, int, str], Cell] = {}
    superseded: list[str] = []
    for path in sorted(runs_root.glob(f"*_{prefix}_*")):
        match = pattern.match(path.name)
        if not match or not path.is_dir():
            continue
        cell = Cell(path.name, path, match["stamp"], match["cfg"], int(match["seed"]), match["cat"])
        key = (cell.cfg, cell.seed, cell.category)
        if key in latest:
            older, newer = sorted([latest[key], cell], key=lambda c: c.stamp)
            superseded.append(older.name)
            cell = newer
        latest[key] = cell
    cells = sorted(latest.values(), key=lambda c: (c.cfg, c.seed, CATEGORIES.index(c.category)))
    targets = launch_info(logs_root, prefix)["targets"] if logs_root is not None else {}
    for cell in cells:
        cell.launch_target = targets.get(f"{prefix}_{cell.cfg}_s{cell.seed}_{cell.category}")
        if logs_root is not None:
            cell.exit_code = cell_exit_code(logs_root, prefix, cell)
        if (cell.path / "records.jsonl").exists():
            cell.records, cell.bad_lines = read_jsonl(cell.path / "records.jsonl")
        if (cell.path / "records.templates.jsonl").exists():
            cell.templates, bad = read_jsonl(cell.path / "records.templates.jsonl")
            cell.bad_lines += bad
        cell.summary = parse_summary(cell.path / "summary.txt")
    return cells, superseded


def funnel_bucket(
    reason: str,
    *,
    error: str = "",
    validation_ok: bool = True,
    execution_success: bool = True,
    llm_judged: bool = False,
) -> str:
    """First blocking reason of a rejected candidate, in gate order."""

    if reason.startswith("slot bindings") or error.startswith("slot bindings"):
        return "slot bindings unavailable/exhausted"
    if reason == "validation failed" or error == "validation failed" or not validation_ok:
        return "schema/syntax/validation"
    if not execution_success:
        return "execution error"
    if reason.startswith("execution returned no rows"):
        return "empty result"
    if reason.startswith("reference truncated by unordered LIMIT"):
        return "truncated unordered LIMIT"
    if reason.startswith("reference truncated"):
        return "truncated default LIMIT"
    if "tie at the ORDER BY/LIMIT" in reason or "hides a tie" in reason or "verify ORDER BY/LIMIT" in reason:
        return "LIMIT tie"
    if reason.startswith("literal mismatch"):
        return "literal mismatch"
    if reason.startswith("category contract"):
        return "category contract"
    if reason.startswith("structural defect"):
        return "structural defect"
    if reason.startswith("tier quota"):
        return "tier quota"
    if reason.startswith(("signature quota", "duplicate")) or "diversity cap" in reason:
        return "signature quota/duplicate/entity cap"
    if "llm judge error" in reason:
        return "LLM judge error (fail-closed)"
    if llm_judged or reason.startswith("[") or "=no" in reason:
        return "LLM panel reject"
    return "other"


def record_bucket(record: dict[str, Any]) -> str | None:
    if record.get("accepted"):
        return None
    judge = record.get("judge") or {}
    execution = record.get("execution") or {}
    validation = record.get("validation") or {}
    return funnel_bucket(
        str(judge.get("failure_reason") or ""),
        error=str(execution.get("error") or ""),
        validation_ok=all(validation.get(k, True) for k in ("read_only", "syntax_valid", "schema_valid")),
        execution_success=bool(execution.get("success")),
        llm_judged=bool((judge.get("raw") or {}).get("judge_mode")),
    )


def panel_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Member pass rates and pairwise agreement on candidates the LLM panel actually judged.

    Candidates rejected after a panel pass (duplicate/quota checks) lose their
    member verdicts in the record and are not counted here.
    """

    panels = []
    for record in records:
        raw = (record.get("judge") or {}).get("raw") or {}
        members = raw.get("panel") or []
        if raw.get("judge_mode") == "panel" and len(members) >= 2:
            panels.append({str(m.get("label")): bool(m.get("passed")) for m in members})
    if not panels:
        return {"n": 0}
    labels = list(dict.fromkeys(label for panel in panels for label in panel))
    out: dict[str, Any] = {
        "n": len(panels),
        "members": labels,
        "member_pass_rate": {
            label: share(sum(p[label] for p in panels if label in p), sum(label in p for p in panels))
            for label in labels
        },
        "unanimous_pass_rate": share(sum(all(p.values()) for p in panels), len(panels)),
    }
    if len(labels) >= 2:
        a, b = labels[:2]
        out["pair"] = [a, b]
        out.update(agreement([(p[a], p[b]) for p in panels if a in p and b in p]))
    return out


def normalize_template_reason(reason: str) -> str:
    """Strip item-specific detail so rejection reasons aggregate."""

    reason = reason.strip()
    for prefix in ("template Cypher does not use slot parameter(s)", "template Cypher uses unknown parameter(s)"):
        if reason.startswith(prefix):
            return prefix
    if reason.startswith("template Cypher fails governance:"):
        first = reason.split(":", 1)[1].split(";")[0].strip()
        first = re.sub(r"\(.*", "", first)
        first = re.sub(r"\s:\S+.*", "", first)
        return "template Cypher fails governance: " + first.strip()
    return re.sub(r"\d{3,}", "<num>", reason)[:120]


def template_stats(templates: list[dict[str, Any]]) -> dict[str, Any]:
    status = Counter(str(t.get("status")) for t in templates)
    by_origin: dict[str, Counter] = defaultdict(Counter)
    reasons: Counter = Counter()
    for t in templates:
        by_origin[str(t.get("template_origin"))][str(t.get("status"))] += 1
        if t.get("status") != "accepted":
            reasons[normalize_template_reason(str(t.get("reason") or ""))] += 1
    return {
        "proposed": len(templates),
        "accepted": status.get("accepted", 0),
        "rejected": status.get("rejected", 0),
        "contract_pass_rate": share(status.get("accepted", 0), len(templates)),
        "by_origin": {k: dict(v) for k, v in sorted(by_origin.items())},
        "top_rejection_reasons": ranked(reasons, 15),
    }


def build_metrics(records: list[dict[str, Any]], templates: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(records)
    accepted = [r for r in records if r.get("accepted")]
    buckets = Counter(b for b in map(record_bucket, records) if b)
    rejected = n - len(accepted)
    funnel = {
        name: {"count": buckets[name], "share_of_rejected": share(buckets[name], rejected),
               "share_of_candidates": share(buckets[name], n)}
        for name in FUNNEL_BUCKETS if buckets[name]
    }
    raw_reasons = Counter(
        re.sub(r"\(.*", "", str((r.get("judge") or {}).get("failure_reason") or ""))[:80].strip()
        for r in records if not r.get("accepted")
    )
    empty = sum(1 for r in records if str((r.get("judge") or {}).get("failure_reason") or "").startswith("execution returned no rows"))

    def meta_counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
        return ranked(Counter(str((r.get("generation_metadata") or {}).get(key)) for r in rows))

    return {
        "candidates": n,
        "accepted": len(accepted),
        "acceptance_rate": share(len(accepted), n),
        "funnel": funnel,
        "top_raw_rejection_reasons": ranked(raw_reasons, 12),
        "empty_result_share_of_candidates": share(empty, n),
        "panel": panel_stats(records),
        "templates": template_stats(templates),
        "reference_source": {"all": meta_counts(records, "reference_source"), "accepted": meta_counts(accepted, "reference_source")},
        "template_cypher_agreement": {
            "all": meta_counts(records, "template_cypher_agreement"),
            "accepted": meta_counts(accepted, "template_cypher_agreement"),
        },
        "realization_style": {
            "all": meta_counts(records, "question_realization"),
            "accepted": meta_counts(accepted, "question_realization"),
        },
        "accepted_template_origin": meta_counts(accepted, "template_origin"),
        # Calibrated tier (v3 difficulty model); configs without the model leave it unset.
        "accepted_tiers": {
            t: sum(1 for r in accepted if (r.get("generation_metadata") or {}).get("difficulty_tier") == t)
            for t in TIERS
        } | {"missing": sum(1 for r in accepted if not (r.get("generation_metadata") or {}).get("difficulty_tier"))},
        "accepted_structural_heuristic_difficulty": ranked(Counter(
            str(((r.get("validation") or {}).get("structural_features") or {}).get("difficulty")) for r in accepted
        )),
    }


def accepted_diversity(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Export-style diversity computed directly on accepted run records."""

    accepted = [r for r in records if r.get("accepted")]
    if not accepted:
        return {"n": 0}
    questions = [str(r.get("question") or "") for r in accepted]
    signatures = [
        (r.get("generation_metadata") or {}).get("query_signature")
        or canonical_query_signature(str((r.get("validation") or {}).get("normalized_cypher") or r.get("cypher") or ""))
        for r in accepted
    ]
    counts = Counter(signatures)
    return {
        "n": len(accepted),
        "unique_signatures": len(counts),
        "top10_signature_share": share(sum(c for _, c in counts.most_common(10)), len(accepted)),
        "distinct_2": distinct_n(questions, 2),
        "ead_distinct_2": expected_distinct_ratio(questions, 2),
        "self_bleu_2_sampled": self_bleu(questions, max_examples=SELF_BLEU_SAMPLE, max_order=2),
    }


def cell_rows(cells: list[Cell]) -> list[dict[str, Any]]:
    rows = []
    for cell in cells:
        by_cat = ((cell.summary or {}).get("attempt_summary") or {}).get("by_category") or {}
        cat_summary = by_cat.get(cell.category) or {}
        accepted = sum(1 for r in cell.records if r.get("accepted"))
        rows.append({
            "run": cell.name,
            "graph": cell.graph,
            "cfg": cell.cfg,
            "seed": cell.seed,
            "category": cell.category,
            "complete": cell.summary is not None,
            "exit_code": cell.exit_code,
            "candidates": len(cell.records),
            "accepted": accepted,
            "target": cell.target,
            "target_source": "summary" if cell.summary_target is not None else ("launch_commands" if cell.launch_target is not None else None),
            "at_target": (accepted >= cell.target) if cell.target is not None else None,
            "candidate_attempts": cat_summary.get("candidate_attempts"),
            "tier_quota": cat_summary.get("tier_quota"),
            "tier_accepted": cat_summary.get("tier_accepted"),
            "tier_quota_unmet": cat_summary.get("tier_quota_unmet"),
            "tier_spillover": cat_summary.get("tier_spillover"),
            "templates_retired_by_gates": cat_summary.get("templates_retired_by_gates"),
            "no_reusable_template_break": cat_summary.get("no_reusable_template_break"),
            "induced_templates": cat_summary.get("induced_templates"),
            "bad_lines": cell.bad_lines,
        })
    return rows


# --- spend ledgers ----------------------------------------------------------


def ledger_rows(ledger_dir: Path, prefix: str, explicit: str | None) -> tuple[list[dict[str, Any]], list[str], str | None]:
    candidates = [Path(explicit)] if explicit else [
        ledger_dir / f"{prefix}_spend.jsonl", ledger_dir / f"{prefix}_generation_spend.jsonl"
    ]
    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        return [], [str(p) for p in candidates], None
    label_re = re.compile(rf"^{re.escape(prefix)}_(?P<cfg>.+)_s(?P<seed>\d+):(?P<cat>[a-z_]+):(?P<stage>[A-Za-z0-9_]+)$")
    rows, _ = read_jsonl(path)
    out = []
    for row in rows:
        match = label_re.match(str(row.get("label") or ""))
        if match:
            out.append({**row, "_cell": (match["cfg"], int(match["seed"]), match["cat"]), "_stage": match["stage"]})
    return out, [], str(path)


def spend_summary(rows: list[dict[str, Any]], *, accepted: int | None = None, exported: int | None = None) -> dict[str, Any]:
    def totals(group: list[dict[str, Any]]) -> dict[str, Any]:
        prompt = sum(int(r.get("prompt_tokens") or 0) for r in group)
        cached = sum(int(r.get("cached_tokens") or 0) for r in group)
        costs = [r.get("cost_usd") for r in group]
        return {
            "calls": len(group),
            "cost_usd": sum(float(c) for c in costs if c is not None) if any(c is not None for c in costs) else None,
            "prompt_tokens": prompt,
            "cached_tokens": cached,
            "completion_tokens": sum(int(r.get("completion_tokens") or 0) for r in group),
            "reasoning_tokens": sum(int(r.get("reasoning_tokens") or 0) for r in group),
            "cache_hit_share": share(cached, prompt),
            "median_latency_s": median([float(r["latency_s"]) for r in group if r.get("latency_s") is not None]),
        }

    out = totals(rows)
    by_stage: dict[str, list] = defaultdict(list)
    by_model: dict[str, list] = defaultdict(list)
    for row in rows:
        by_stage[str(row.get("_stage", row.get("label")))].append(row)
        by_model[f"{row.get('model')}@{row.get('served_by')}"].append(row)
    out["by_stage"] = {k: totals(v) for k, v in sorted(by_stage.items())}
    out["by_model_provider"] = {k: totals(v) for k, v in sorted(by_model.items())}
    stamps = [float(r["ts"]) for r in rows if r.get("ts") is not None]
    out["first_call"], out["last_call"] = (iso(min(stamps)), iso(max(stamps))) if stamps else (None, None)
    out["call_span_minutes"] = (max(stamps) - min(stamps)) / 60 if stamps else None
    usd = out["cost_usd"]
    out["accepted"] = accepted
    out["exported"] = exported
    out["usd_per_1000_accepted"] = 1000 * usd / accepted if usd is not None and accepted else None
    out["usd_per_1000_exported"] = 1000 * usd / exported if usd is not None and exported else None
    return out


def wall_clock(records: list[dict[str, Any]]) -> dict[str, Any]:
    stamps = [t for t in (parse_ts(r.get("created_at")) for r in records) if t is not None]
    if not stamps:
        return {"first_record": None, "last_record": None, "minutes": None}
    return {"first_record": iso(min(stamps)), "last_record": iso(max(stamps)), "minutes": (max(stamps) - min(stamps)) / 60}


def export_counts(bench_root: Path, names: list[str]) -> tuple[int | None, Counter]:
    total, by_graph, found = 0, Counter(), False
    for name in names:
        path = bench_root / name / "all.jsonl"
        if path.exists():
            found = True
            rows, _ = read_jsonl(path)
            total += len(rows)
            by_graph.update(str(r.get("graph_profile")) for r in rows)
    return (total if found else None), by_graph


def build_section(args: argparse.Namespace, prefix: str, export_names: list[str], ledger: str | None) -> dict[str, Any]:
    runs_root = Path(args.runs_root)
    cells, superseded = discover_cells(runs_root, prefix, Path(args.logs_root))
    if not cells:
        return {"prefix": prefix, "missing": [str(runs_root / f"*_{prefix}_*/records.jsonl")]}
    records = [r for c in cells for r in c.records]
    templates = [t for c in cells for t in c.templates]
    spend_rows, spend_missing, spend_path = ledger_rows(Path(args.ledger_dir), prefix, ledger)
    exported, exported_by_graph = export_counts(Path(args.benchmarks_root), export_names)
    cell_graph = {(c.cfg, c.seed, c.category): c.graph for c in cells}
    graphs = sorted({c.graph for c in cells})
    out: dict[str, Any] = {
        "prefix": prefix,
        "launch_manifest": launch_info(Path(args.logs_root), prefix)["manifest"],
        "run_dirs": len(cells),
        "complete_cells": sum(1 for c in cells if c.summary is not None),
        "failed_cells": [c.name for c in cells if c.exit_code not in (None, 0)],
        "superseded_runs": superseded,
        "bad_lines": sum(c.bad_lines for c in cells),
        "overall": build_metrics(records, templates),
        "by_graph": {},
        "cells": cell_rows(cells),
        "wall_clock": wall_clock(records),
        "spend": (
            {"missing": spend_missing} if spend_missing else
            {"ledger": spend_path, **spend_summary(spend_rows, accepted=sum(1 for r in records if r.get("accepted")), exported=exported)}
        ),
    }
    known = [row for row in out["cells"] if row["target"] is not None]
    out["cells_at_target"] = {
        "known_target": len(known),
        "at_target": sum(1 for r in known if r["at_target"]),
        "complete_below_target": [r["run"] for r in known if r["complete"] and not r["at_target"]],
        "target_sum": sum(r["target"] for r in known),
        "accepted_sum": sum(r["accepted"] for r in out["cells"]),
    }
    for graph in graphs:
        g_cells = [c for c in cells if c.graph == graph]
        g_records = [r for c in g_cells for r in c.records]
        entry = build_metrics(g_records, [t for c in g_cells for t in c.templates])
        entry["wall_clock"] = wall_clock(g_records)
        if not spend_missing:
            g_spend = [r for r in spend_rows if cell_graph.get(r["_cell"], graph_from_cfg(r["_cell"][0])) == graph]
            entry["spend"] = spend_summary(
                g_spend,
                accepted=entry["accepted"],
                exported=exported_by_graph.get(graph) if exported is not None else None,
            )
        out["by_graph"][graph] = entry
    return out


# ---------------------------------------------------------------------------
# B. Exports
# ---------------------------------------------------------------------------


def export_section(bench_root: Path, name: str, audit_root: Path | None) -> dict[str, Any]:
    root = bench_root / name
    all_path = root / "all.jsonl"
    if not all_path.exists():
        return {"missing": [str(all_path)]}
    rows, bad = read_jsonl(all_path)
    if not rows:
        return {"missing": [str(all_path)], "note": "empty export"}
    splits = {}
    for split in ("train", "dev", "test"):
        path = root / f"{split}.jsonl"
        splits[split] = read_jsonl(path)[0] if path.exists() else None

    def sig(row: dict[str, Any]) -> str:
        return row.get("query_signature") or canonical_query_signature(str(row.get("normalized_cypher") or row.get("cypher") or ""))

    signatures = Counter(sig(r) for r in rows)
    per_cell: dict[tuple[str, str], set] = defaultdict(set)
    for row in rows:
        per_cell[(str(row.get("graph_profile")), str(row.get("category")))].add(sig(row))
    cell_sizes = [len(v) for v in per_cell.values()]
    tiers = Counter(str(r.get("difficulty")) for r in rows)
    report = benchmark_diversity_report(
        rows, self_bleu_sample_size=SELF_BLEU_SAMPLE, include_by_graph=False, include_by_category=False
    )
    text = report["question_text"]
    by_graph_text = {}
    for graph in sorted({str(r.get("graph_profile")) for r in rows}):
        questions = [str(r.get("question") or "") for r in rows if str(r.get("graph_profile")) == graph]
        by_graph_text[graph] = {
            "n": len(questions),
            "distinct_2": distinct_n(questions, 2),
            "ead_distinct_2": expected_distinct_ratio(questions, 2),
            "self_bleu_2_sampled": self_bleu(questions, max_examples=SELF_BLEU_SAMPLE, max_order=2),
        }
    out: dict[str, Any] = {
        "path": str(root),
        "bad_lines": bad,
        "total": len(rows),
        "by_graph": ranked(Counter(str(r.get("graph_profile")) for r in rows)),
        "by_category": ranked(Counter(str(r.get("category")) for r in rows)),
        "by_graph_category": ranked(Counter(f"{r.get('graph_profile')}::{r.get('category')}" for r in rows)),
        "by_tier": {t: tiers.get(t, 0) for t in TIERS} | {k: v for k, v in tiers.items() if k not in TIERS},
        "tier_share": {t: share(tiers.get(t, 0), len(rows)) for t in TIERS},
        "by_graph_tier": ranked(Counter(f"{r.get('graph_profile')}::{r.get('difficulty')}" for r in rows)),
        "by_seed": ranked(Counter(str(seed_of_run((r.get("source") or {}).get("run"))) for r in rows)),
        "unique_signatures": len(signatures),
        "signatures_per_cell": {"min": min(cell_sizes), "median": median(cell_sizes), "max": max(cell_sizes), "cells": len(cell_sizes)},
        "top10_signature_share": share(sum(c for _, c in signatures.most_common(10)), len(rows)),
        "template_families": report["template_families"]["unique_family_count"],
        "unique_template_strings": len({r.get("template") for r in rows if r.get("template")}),
        "distinct_1": text["distinct_1"],
        "distinct_2": text["distinct_2"],
        "ead_distinct_2": text["ead_distinct_2"],
        "self_bleu_2_sampled": text["self_bleu_2_sampled"],
        "self_bleu_sample_size": SELF_BLEU_SAMPLE,
        "pairwise_jaccard_sampled": text["pairwise_jaccard_sampled"],
        "unique_question_ratio": text["unique_question_ratio"],
        "text_by_graph": by_graph_text,
        "splits": {k: (len(v) if v is not None else None) for k, v in splits.items()},
    }
    if splits["train"] is not None and splits["test"] is not None:
        train_sigs = {sig(r) for r in splits["train"]}
        out["test_sharing_train_signature"] = {
            "shared": sum(1 for r in splits["test"] if sig(r) in train_sigs),
            "test": len(splits["test"]),
        }
    manifest = load_json(root / "manifest.json")
    if isinstance(manifest, dict):
        out["manifest"] = {k: manifest.get(k) for k in (
            "created_at", "sha256", "split_strategy", "split_seed", "split_counts", "total_examples",
            "max_per_signature", "max_per_cell", "signature_cap_dropped", "cell_cap_dropped",
        )}
        out["manifest"]["records_paths"] = len(manifest.get("records_paths") or [])
    if audit_root is not None:
        out["audits"] = export_audits(audit_root / name)
    return out


def export_audits(root: Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    missing = []
    ties = load_json(root / "limit_ties" / "summary.json")
    if ties is None:
        missing.append(str(root / "limit_ties" / "summary.json"))
    else:
        out["limit_ties"] = {"n": ties.get("n"), "by_status": ties.get("by_status"), "by_category": ties.get("by_category")}
    literal = load_json(root / "literal" / "summary.json")
    if literal is None:
        missing.append(str(root / "literal" / "summary.json"))
    else:
        out["literal"] = {k: literal.get(k) for k in ("n", "flagged", "flagged_share", "items_by_problem_kind")}
    redaction = load_json(root / "redaction.json")
    if redaction is None:
        missing.append(str(root / "redaction.json"))
    else:
        out["redaction"] = {k: redaction.get(k) for k in (
            "examples", "examples_with_residuals", "sensitive_values", "residual_values",
            "residual_rate_per_value", "residuals_by_field", "config",
        )}
    if missing:
        out["missing"] = missing
    return out


# ---------------------------------------------------------------------------
# C-E. Downstream evaluation
# ---------------------------------------------------------------------------


@dataclass
class EvalRun:
    label: str
    path: str
    rows: list[dict[str, Any]]
    expected: int | None

    @property
    def failure_rate(self) -> float:
        return share(sum(1 for r in self.rows if r.get("prediction_failed")), len(self.rows)) or 0.0

    @property
    def complete(self) -> bool:
        return self.expected is None or len({str(r.get("id")) for r in self.rows}) == self.expected

    @property
    def valid(self) -> bool:
        return self.failure_rate <= MAX_PREDICTION_FAILURE_RATE

    @property
    def usable(self) -> bool:
        return bool(self.rows) and self.complete and self.valid

    def as_stats_run(self, rows: list[dict[str, Any]] | None = None) -> EvaluationRun:
        return EvaluationRun(label=self.label, rows=list(rows if rows is not None else self.rows), path=self.path)


def load_eval(label: str, candidates: list[Path], ids: set[str] | None, graph: str | None = None) -> EvalRun | None:
    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        return None
    rows, _ = read_jsonl(path)
    if graph:
        rows = [r for r in rows if r.get("graph_profile") == graph]
    if ids is not None:
        rows = [r for r in rows if str(r.get("id")) in ids]
    return EvalRun(label, str(path), rows, len(ids) if ids is not None else None)


def tier_of(row: dict[str, Any], index: dict[str, dict[str, Any]]) -> str:
    bench = index.get(str(row.get("id"))) or {}
    return str(bench.get("difficulty") or row.get("difficulty") or "unknown")


def overall(run: EvalRun, index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows = run.rows
    n = len(rows)

    def projected_by(key_fn: Callable[[dict[str, Any]], str]) -> dict[str, Any]:
        groups: dict[str, list] = defaultdict(list)
        for row in rows:
            groups[key_fn(row)].append(row)
        return {k: {"n": len(v), "projected": rate(v, "projected_execution_accuracy"), "strict": rate(v, "execution_accuracy")}
                for k, v in sorted(groups.items())}

    by_tier = projected_by(lambda r: tier_of(r, index))
    tier_points = [by_tier.get(t, {}).get("projected") for t in TIERS]
    out = {
        "path": run.path,
        "n": n,
        "n_expected": run.expected,
        "complete": run.complete,
        "valid": run.valid,
        "strict": rate(rows, "execution_accuracy"),
        "projected": rate(rows, "projected_execution_accuracy"),
        "answer_f1": rate(rows, "answer_f1"),
        "projected_f1": rate(rows, "projected_answer_f1"),
        "exec_success": rate(rows, "execution_success"),
        "parse_valid": rate(rows, "parse_valid"),
        "schema_valid": rate(rows, "schema_valid"),
        "governance_valid": rate(rows, "governance_valid"),
        "prediction_failure_rate": run.failure_rate,
        "wrong_direction_rate": share(sum(1 for r in rows if "wrong_direction" in (r.get("governance_error_codes") or [])), n),
        "by_tier": by_tier,
        "by_category": projected_by(lambda r: str(r.get("category"))),
        "by_graph": projected_by(lambda r: str(r.get("graph_profile"))),
    }
    if all(p is not None for p in tier_points):
        out["tier_strictly_decreasing"] = tier_points[0] > tier_points[1] > tier_points[2]
        out["tier_non_increasing"] = tier_points[0] >= tier_points[1] >= tier_points[2]
    return out


def condition_summary(runs: list[EvalRun], index: dict[str, dict[str, Any]], args: argparse.Namespace, missing: list[str]) -> dict[str, Any]:
    per_model = {run.label: overall(run, index) for run in runs}
    usable = [run for run in runs if run.usable]
    medians = {}
    for key in ("strict", "projected", "exec_success", "parse_valid", "schema_valid", "prediction_failure_rate", "wrong_direction_rate"):
        values = [per_model[r.label][key] for r in usable if per_model[r.label][key] is not None]
        medians[key] = median(values)
    for tier in TIERS:
        values = [per_model[r.label]["by_tier"].get(tier, {}).get("projected") for r in usable]
        medians[f"projected_{tier}"] = median([v for v in values if v is not None])
    scored = [per_model[r.label] for r in usable if "tier_strictly_decreasing" in per_model[r.label]]
    out: dict[str, Any] = {
        "models_found": len(runs),
        "models_usable": [r.label for r in usable],
        "models_unusable": {r.label: {"n": len(r.rows), "n_expected": r.expected, "failure_rate": r.failure_rate}
                            for r in runs if not r.usable},
        "per_model": per_model,
        "medians_usable": medians,
        "tier_monotonicity": {
            "models_scored": len(scored),
            "strictly_decreasing_easy_medium_hard": sum(1 for m in scored if m["tier_strictly_decreasing"]),
            "non_increasing": sum(1 for m in scored if m["tier_non_increasing"]),
        },
    }
    if missing:
        out["missing"] = missing
    if usable and not args.skip_bootstrap:
        out["clustered"] = guarded(
            analyze_models,
            [r.as_stats_run() for r in usable],
            metrics=EX_METRICS,
            benchmark_index=index or None,
            exclude_invalid=True,
            require_same_ids=False,
            iterations=args.bootstrap_iterations,
        )
    return out


def eval_dir(args: argparse.Namespace, name: str) -> Path:
    return Path(args.evaluations_root) / name


def downstream_section(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, EvalRun]]:
    bench = Path(args.benchmarks_root) / args.main_export
    all_path, test_path = bench / "all.jsonl", bench / "test.jsonl"
    if not all_path.exists():
        return {"missing": [str(all_path)]}, {}
    index = {str(r.get("id")): r for r in read_jsonl(all_path)[0]}
    all_ids = set(index)
    test_ids = {str(r.get("id")) for r in read_jsonl(test_path)[0]} if test_path.exists() else None
    out: dict[str, Any] = {"benchmark": str(bench), "n_all": len(all_ids), "n_test": len(test_ids) if test_ids is not None else None}
    if test_ids is None:
        out["missing_test_split"] = str(test_path)

    conditions: dict[str, tuple[Callable[[str], list[Path]], set[str] | None]] = {
        "zero_all": (lambda s: [eval_dir(args, f"{args.all_eval_prefix}_downstream_{s}") / "zero_shot_evaluation.jsonl"], all_ids),
    }
    if test_ids is not None:
        conditions.update({
            "zero_heldout": (lambda s: [
                eval_dir(args, f"{args.all_eval_prefix}_downstream_{s}") / "zero_shot_evaluation.jsonl",
                eval_dir(args, f"{args.heldout_eval_prefix}_downstream_{s}") / "zero_shot_evaluation.jsonl",
            ], test_ids),
            "governed_heldout": (lambda s: [
                eval_dir(args, f"{args.heldout_eval_prefix}_promptfmt_{s}_zero_pipe_governed") / "zero_shot_evaluation.jsonl"
            ], test_ids),
            "fewshot_heldout": (lambda s: [
                eval_dir(args, f"{args.heldout_eval_prefix}_control_{s}_ordered_logged") / "few_shot_evaluation.jsonl"
            ], test_ids),
        })
    zero_all_runs: dict[str, EvalRun] = {}
    for condition, (paths_for, ids) in conditions.items():
        runs, missing, off_split = [], [], []
        for slug in args.models:
            candidates = paths_for(slug)
            run = load_eval(slug, candidates, ids)
            if run is None:
                missing.append(str(candidates[0]))
            elif run.rows:
                runs.append(run)
            else:
                off_split.append(run.path)
        if condition == "zero_all":
            zero_all_runs = {r.label: r for r in runs}
        out[condition] = condition_summary(runs, index, args, missing)
        if off_split:
            out[condition]["no_rows_for_expected_ids"] = off_split

    local_runs, off_split = [], []
    for path in sorted(Path(args.evaluations_root).glob(f"{args.local_eval_glob}/zero_shot_evaluation.jsonl")):
        label = path.parent.name.removeprefix(args.local_eval_glob.split("*")[0])
        run = load_eval(label, [path], test_ids)
        if run is not None and run.rows:
            local_runs.append(run)
        elif run is not None:
            off_split.append(run.path)
    out["local_finetunes_heldout"] = (
        condition_summary(local_runs, index, args, []) if local_runs
        else {"missing": [str(Path(args.evaluations_root) / args.local_eval_glob / "zero_shot_evaluation.jsonl")]}
    )
    if off_split:
        out["local_finetunes_heldout"]["no_rows_for_expected_ids"] = off_split
    return out, zero_all_runs


def stability_section(args: argparse.Namespace, zero_all: dict[str, EvalRun]) -> dict[str, Any]:
    all_path = Path(args.benchmarks_root) / args.main_export / "all.jsonl"
    if not all_path.exists():
        return {"missing": [str(all_path)]}
    seed_of = {str(r.get("id")): seed_of_run((r.get("source") or {}).get("run")) for r in read_jsonl(all_path)[0]}
    seeds = sorted({s for s in seed_of.values() if s is not None})
    usable = [run for run in zero_all.values() if run.usable]
    out: dict[str, Any] = {"seeds_in_export": seeds, "items_per_seed": dict(Counter(str(s) for s in seed_of.values()))}
    if not usable:
        out["missing"] = ["no complete zero-shot run on split all (" + f"{args.all_eval_prefix}_downstream_<slug>)"]
        return out
    per_model: dict[str, dict[str, Any]] = {}
    for run in usable:
        entry = {}
        for seed in seeds:
            rows = [r for r in run.rows if seed_of.get(str(r.get("id"))) == seed]
            entry[f"s{seed}"] = {"n": len(rows), "projected": rate(rows, "projected_execution_accuracy"), "strict": rate(rows, "execution_accuracy")}
        per_model[run.label] = entry
    out["per_model"] = per_model
    if len(seeds) < 2:
        out["missing"] = [f"only seed(s) {seeds} in {all_path}; stability needs two seeds"]
        return out
    s1, s2 = seeds[:2]
    out["seed_pair"] = [s1, s2]
    for metric, key in (("projected_execution_accuracy", "projected"), ("execution_accuracy", "strict")):
        x = [per_model[m][f"s{s1}"][key] for m in per_model]
        y = [per_model[m][f"s{s2}"][key] for m in per_model]
        if len(x) >= 3 and None not in x and None not in y:
            out[f"{key}_kendall_tau_b"] = kendall_tau_b(x, y)
            out[f"{key}_spearman_rho"] = spearman_rho(x, y)
            out[f"{key}_median_abs_diff"] = median([abs(a - b) for a, b in zip(x, y)])
    if len(usable) >= 3 and not args.skip_bootstrap:
        def subset(seed: int) -> list[EvaluationRun]:
            return [r.as_stats_run([row for row in r.rows if seed_of.get(str(row.get("id"))) == seed]) for r in usable]

        out["rank_agreement_bootstrap"] = guarded(
            analyze_rank_agreement,
            subset(s1), subset(s2), name_a=f"seed{s1}", name_b=f"seed{s2}", metrics=EX_METRICS,
            iterations=args.bootstrap_iterations,
        )
    return out


def rank_agreement_section(args: argparse.Namespace) -> dict[str, Any]:
    anchor_path = Path(args.anchor_index)
    anchor_index = {str(r.get("id")): r for r in read_jsonl(anchor_path)[0]} if anchor_path.exists() else None
    out: dict[str, Any] = {}
    for graph in args.pub_graphs:
        export = Path(args.benchmarks_root) / f"{args.pub_export_stem}_{graph}" / "all.jsonl"
        missing = [str(p) for p in (export, anchor_path) if not p.exists()]
        if missing:
            out[graph] = {"missing": missing}
            continue
        pipe_index = {str(r.get("id")): r for r in read_jsonl(export)[0]}
        anchor_ids = {i for i, r in anchor_index.items() if r.get("graph_profile") == f"t2c_{graph}"}
        side_a, side_b, missing = {}, {}, []
        for slug in args.models:
            pa = eval_dir(args, f"{args.pubeval_prefix}_{graph}_downstream_{slug}") / "zero_shot_evaluation.jsonl"
            pb = eval_dir(args, f"{args.anchor_prefix}_downstream_{slug}") / "zero_shot_evaluation.jsonl"
            ra = load_eval(slug, [pa], set(pipe_index))
            rb = load_eval(slug, [pb], anchor_ids, graph=f"t2c_{graph}")
            if ra is None:
                missing.append(str(pa))
            if rb is None:
                missing.append(str(pb))
            if ra is not None and ra.rows:
                side_a[slug] = ra
            if rb is not None and rb.rows:
                side_b[slug] = rb
        both = [s for s in args.models if s in side_a and s in side_b and side_a[s].usable and side_b[s].usable]
        entry: dict[str, Any] = {
            "pipe": {s: {k: v for k, v in overall(r, pipe_index).items() if k not in ("by_category", "by_graph")} for s, r in side_a.items()},
            "anchor": {s: {k: v for k, v in overall(r, anchor_index).items() if k not in ("by_category", "by_graph", "by_tier")} for s, r in side_b.items()},
            "models_in_both_usable": both,
        }
        if missing:
            entry["missing"] = missing
        if len(both) >= args.min_rank_models:
            entry["analysis"] = guarded(
                analyze_rank_agreement,
                [side_a[s].as_stats_run() for s in both], [side_b[s].as_stats_run() for s in both],
                name_a=f"PIPE-{graph}", name_b=f"T2C24-{graph}", metrics=EX_METRICS[::-1],
                benchmark_index_a=pipe_index, benchmark_index_b=anchor_index,
                iterations=args.bootstrap_iterations,
            )
        else:
            entry["analysis"] = {"skipped": f"{len(both)} usable models on both sides (< {args.min_rank_models})"}
        out[graph] = entry
    return out


# ---------------------------------------------------------------------------
# F. gpt-6-luna checklist audit
# ---------------------------------------------------------------------------


def audit_section(args: argparse.Namespace) -> dict[str, Any]:
    path = Path(args.audit_file)
    if not path.exists():
        return {"missing": [str(path)]}
    rows, bad = read_jsonl(path)

    def is_error(r: dict[str, Any]) -> bool:
        return bool((r.get("auditor_raw") or {}).get("judge_error")) or "llm judge error" in str(r.get("auditor_failure_reason") or "")

    errors = [r for r in rows if is_error(r)]
    scored = [r for r in rows if not is_error(r) and r.get("auditor_passed") is not None]
    accepted = [r for r in scored if r.get("accepted")]

    def flag_rate(group: list[dict[str, Any]]) -> dict[str, Any]:
        flagged = sum(1 for r in group if not r.get("auditor_passed"))
        return {"n": len(group), "flagged": flagged, "flag_rate": share(flagged, len(group))}

    def by(key: str) -> dict[str, Any]:
        groups: dict[str, list] = defaultdict(list)
        for r in accepted:
            groups[str(r.get(key))].append(r)
        return {k: flag_rate(v) for k, v in sorted(groups.items())}

    failing_items: Counter = Counter()
    reasons: Counter = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    for r in scored:
        if r.get("auditor_passed"):
            continue
        items = (r.get("auditor_raw") or {}).get("failing") or re.findall(r"(\w+)=no", str(r.get("auditor_failure_reason") or ""))
        failing_items.update(str(i) for i in items)
        first = str(r.get("auditor_failure_reason") or "").split(":", 1)[0][:60]
        reasons[first] += 1
        if len(examples[first]) < 3:
            examples[first].append(str(r.get("auditor_failure_reason") or "")[:200])
    members = sorted({label for r in scored for label in (r.get("panel_members") or {})})
    out: dict[str, Any] = {
        "path": str(path),
        "bad_lines": bad,
        "rows": len(rows),
        "auditor_errors": len(errors),
        "scored": len(scored),
        "accepted_flag": flag_rate(accepted),
        "accepted_flag_by_graph": by("graph_profile"),
        "accepted_flag_by_category": by("category"),
        "accepted_flag_by_tier": by("difficulty_tier"),
        "vs_panel_decision": agreement([(bool(r.get("panel_passed")), bool(r.get("auditor_passed"))) for r in scored]),
        "vs_panel_members": {
            m: agreement([(bool(r["panel_members"][m]), bool(r.get("auditor_passed"))) for r in scored if m in (r.get("panel_members") or {})])
            for m in members
        },
        "panel_accept_auditor_reject": sum(1 for r in scored if r.get("panel_passed") and not r.get("auditor_passed")),
        "panel_reject_auditor_accept": sum(1 for r in scored if not r.get("panel_passed") and r.get("auditor_passed")),
        "top_failing_checklist_items": ranked(failing_items),
        "top_failure_reasons": ranked(reasons, 10),
        "failure_reason_examples": dict(examples),
    }
    export_path = Path(args.benchmarks_root) / args.main_export / "all.jsonl"
    if export_path.exists():
        keys = {f"{r.get('graph_profile')}|{r.get('category')}|{r.get('question')}|{r.get('cypher')}" for r in read_jsonl(export_path)[0]}
        exported = [r for r in scored if r.get("key") in keys]
        out["exported_flag"] = {**flag_rate(exported), "export_items": len(keys)}
    return out


# ---------------------------------------------------------------------------
# G. Generator swap
# ---------------------------------------------------------------------------


def replay_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def reached_judge(r: dict[str, Any]) -> bool:
        raw = r.get("judge_raw") or {}
        return bool(r.get("validation_ok") and r.get("execution_success") and (r.get("judge_passed") or raw.get("judge_mode")))

    gate = [r for r in rows if reached_judge(r)]
    judged_pass = [r for r in rows if r.get("judge_passed")]
    same = [r.get("same_answer_as_original") for r in rows if r.get("same_answer_as_original") is not None]
    buckets = Counter(
        funnel_bucket(
            str(r.get("failure_reason") or ""),
            validation_ok=bool(r.get("validation_ok")),
            execution_success=bool(r.get("execution_success")),
            llm_judged=bool((r.get("judge_raw") or {}).get("judge_mode")),
        )
        for r in rows if not r.get("judge_passed")
    )
    return {
        "sampled": len(rows),
        "gate_pass": len(gate),
        "gate_pass_rate": share(len(gate), len(rows)),
        "judge_pass": len(judged_pass),
        "judge_pass_rate": share(len(judged_pass), len(rows)),
        "judge_pass_given_gate": share(len(judged_pass), len(gate)),
        "both_pass": sum(1 for r in judged_pass if reached_judge(r)),
        "same_answer_known": len(same),
        "same_answer_as_original": sum(same),
        "same_answer_rate_known": share(sum(same), len(same)),
        "same_answer_rate_sampled": share(sum(same), len(rows)),
        "failure_funnel": ranked(buckets),
        "with_id": sum(1 for r in rows if r.get("id")),
    }


def genswap_section(args: argparse.Namespace) -> dict[str, Any]:
    out: dict[str, Any] = {"replays": {}, "rescoring": {}, "self_preference": {}}
    for spec in args.genswap_replay:
        name, pattern = spec.split("=", 1)
        files = sorted(glob.glob(pattern))
        if not files:
            out["replays"][name] = {"missing": [pattern]}
            continue
        rows: list[dict[str, Any]] = []
        bad = 0
        for f in files:
            got, b = read_jsonl(Path(f))
            rows.extend(got)
            bad += b
        entry = {"files": len(files), "bad_lines": bad, "replay_generators": ranked(Counter(str(r.get("replay_generator")) for r in rows)),
                 **replay_stats(rows)}
        for key in ("graph_profile", "category", "difficulty_tier"):
            groups: dict[str, list] = defaultdict(list)
            for r in rows:
                groups[str(r.get(key))].append(r)
            entry[f"by_{key}"] = {k: {kk: replay_stats(v)[kk] for kk in ("sampled", "gate_pass_rate", "judge_pass_rate", "same_answer_rate_known")}
                                  for k, v in sorted(groups.items())}
        out["replays"][name] = entry

    runs_by_set: dict[str, dict[str, EvalRun]] = {}
    for set_name in args.genswap_sets:
        bench_all = Path(args.genswap_bench_root) / set_name / "all.jsonl"
        index = {str(r.get("id")): r for r in read_jsonl(bench_all)[0]} if bench_all.exists() else {}
        runs, missing = {}, []
        for slug in args.models:
            base = eval_dir(args, f"{args.genswap_eval_prefix}_{set_name}_{slug}")
            candidates = [base / "evaluation.jsonl", base / "zero_shot_evaluation.jsonl"]
            run = load_eval(slug, candidates, set(index) if index else None)
            if run is None:
                missing.append(str(candidates[0]))
            elif run.rows:
                runs[slug] = run
            else:
                missing.append(f"{run.path} (no rows for the set's item ids)")
        entry = {"benchmark": str(bench_all) if index else None,
                 "per_model": {s: {k: v for k, v in overall(r, index).items() if k not in ("by_category", "by_graph")} for s, r in runs.items()}}
        if missing:
            entry["missing"] = missing
        if not index:
            entry.setdefault("missing", []).append(str(bench_all))
        out["rescoring"][set_name] = entry
        runs_by_set[set_name] = {s: r for s, r in runs.items() if r.usable}

    def bench_index(set_name: str) -> dict[str, dict[str, Any]] | None:
        path = Path(args.genswap_bench_root) / set_name / "all.jsonl"
        return {str(r.get("id")): r for r in read_jsonl(path)[0]} if path.exists() else None

    pairs = [("original", other, "glm53_flash") for other in args.genswap_sets if other != "original"]
    pairs += [(own, "original", self_model) for own, self_model in (("gpt6luna", "gpt6_luna"), ("qwen9b", "qwen35_9b")) if own in args.genswap_sets]
    for own, other, self_model in pairs:
        key = f"{self_model}:{own}_vs_{other}"
        a, b = runs_by_set.get(own, {}), runs_by_set.get(other, {})
        labels = [s for s in args.models if s in a and s in b]
        if self_model not in labels or len(labels) < 4:
            out["self_preference"][key] = {"skipped": f"usable models on both sets: {labels}; need {self_model} and >= 4"}
            continue
        out["self_preference"][key] = guarded(
            analyze_self_preference,
            [a[s].as_stats_run() for s in labels], [b[s].as_stats_run() for s in labels],
            self_model=self_model, name_own=own, name_other=other, metric="projected_execution_accuracy",
            benchmark_index_own=bench_index(own), benchmark_index_other=bench_index(other),
            iterations=args.bootstrap_iterations,
        )
    return out


# ---------------------------------------------------------------------------
# H. Small generator (gen9b) vs the main build at equal per-category target
# ---------------------------------------------------------------------------


def truncate_at_target(records: list[dict[str, Any]], target: int) -> tuple[list[dict[str, Any]], float | None]:
    """Records up to (and including) the target-th acceptance, plus that record's timestamp."""

    accepted = 0
    for i, record in enumerate(records):
        accepted += bool(record.get("accepted"))
        if accepted >= target:
            return records[: i + 1], parse_ts(record.get("created_at"))
    return records, None


def gen9b_vs_full_section(args: argparse.Namespace) -> dict[str, Any]:
    runs_root = Path(args.runs_root)
    small, _ = discover_cells(runs_root, args.gen9b_prefix, Path(args.logs_root))
    full, _ = discover_cells(runs_root, args.main_prefix, Path(args.logs_root))
    missing = []
    if not small:
        missing.append(str(runs_root / f"*_{args.gen9b_prefix}_*"))
    if not full:
        missing.append(str(runs_root / f"*_{args.main_prefix}_*"))
    if missing:
        return {"missing": missing}
    pairs = {(c.graph, c.category) for c in small}
    full_s1 = [c for c in full if c.seed == 1 and (c.graph, c.category) in pairs]
    target = args.gen9b_compare_target
    small_ledger, small_missing, _ = ledger_rows(Path(args.ledger_dir), args.gen9b_prefix, args.gen9b_ledger)
    full_ledger, full_missing, _ = ledger_rows(Path(args.ledger_dir), args.main_prefix, args.main_ledger)

    truncated_records, truncated_spend, unrestricted_spend = [], [], []
    cutoffs = {}
    for cell in full_s1:
        kept, cutoff = truncate_at_target(cell.records, target)
        truncated_records.extend(kept)
        key = (cell.cfg, cell.seed, cell.category)
        cutoffs[cell.name] = {"kept": len(kept), "of": len(cell.records), "reached_target": cutoff is not None}
        cell_rows_ = [r for r in full_ledger if r["_cell"] == key]
        unrestricted_spend.extend(cell_rows_)
        truncated_spend.extend(r for r in cell_rows_ if cutoff is None or float(r.get("ts") or 0) <= cutoff + 1.0)

    def arm(records: list[dict[str, Any]], templates: list[dict[str, Any]], spend: list[dict[str, Any]], spend_missing: list[str]) -> dict[str, Any]:
        metrics = build_metrics(records, templates)
        metrics["diversity_of_accepted"] = accepted_diversity(records)
        metrics["spend"] = {"missing": spend_missing} if spend_missing else spend_summary(spend, accepted=metrics["accepted"])
        return metrics

    small_records = [r for c in small for r in c.records]
    small_keys = {(c.cfg, c.seed, c.category) for c in small}
    full_templates = [t for c in full_s1 for t in c.templates]
    return {
        "compare_target_per_category": target,
        "cells_compared": sorted(f"{g}:{c}" for g, c in pairs),
        "full_seed1_cells_matched": len(full_s1),
        "gen9b_cells_complete": sum(1 for c in small if c.summary is not None),
        "full_seed1_cells_complete": sum(1 for c in full_s1 if c.summary is not None),
        "gen9b": arm(small_records, [t for c in small for t in c.templates],
                     [r for r in small_ledger if r["_cell"] in small_keys], small_missing),
        "full_seed1_truncated_at_target": arm(truncated_records, full_templates, truncated_spend, full_missing),
        "full_seed1_unrestricted": arm([r for c in full_s1 for r in c.records], full_templates, unrestricted_spend, full_missing),
        "truncation": cutoffs,
        "notes": [
            "Truncated arm keeps each full seed-1 cell's records up to its target-th acceptance; spend is cut at that record's timestamp.",
            "Template proposals of the main build are not time-stamped, so both full arms report every template of the matched cells.",
            "Tier quotas scale with each run's own target, so the truncated full arm ran under larger quotas than gen9b.",
        ],
    }


# ---------------------------------------------------------------------------
# Hosted model token use
# ---------------------------------------------------------------------------


def hosted_spend_section(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"missing": [str(path)]}
    rows, bad = read_jsonl(path)
    by_label: dict[str, list] = defaultdict(list)
    for row in rows:
        by_label[str(row.get("label"))].append(row)
    drop = ("by_stage", "accepted", "exported", "usd_per_1000_accepted", "usd_per_1000_exported")
    summary = {k: v for k, v in spend_summary(rows).items() if k not in drop}
    summary["by_label"] = {k: {kk: v for kk, v in spend_summary(g).items() if kk not in (*drop, "by_model_provider")}
                           for k, g in sorted(by_label.items())}
    summary["bad_lines"] = bad
    summary["note"] = "cost_usd is not recorded for the hosted OpenAI endpoint; report tokens."
    return summary


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def git_head() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--output", default="artifacts/naacl_results/v3_results.json")
    ap.add_argument("--runs-root", default="artifacts/runs")
    ap.add_argument("--benchmarks-root", default="artifacts/benchmarks")
    ap.add_argument("--evaluations-root", default="artifacts/evaluations")
    ap.add_argument("--ledger-dir", default="artifacts/naacl_v3/ledgers")
    ap.add_argument("--logs-root", default="logs", help="launch_commands.txt (targets of running cells) and per-cell EXIT codes")
    # Build prefixes and their exports.
    ap.add_argument("--main-prefix", default="naacl_v3_full")
    ap.add_argument("--gen9b-prefix", default="naacl_v3_gen9b")
    ap.add_argument("--pub-prefix", default="naacl_v3_pub")
    ap.add_argument("--main-export", default="naacl_v3_full")
    ap.add_argument("--gen9b-export", default="naacl_v3_gen9b")
    ap.add_argument("--pub-export-stem", default="naacl_v3_pub", help="Public-graph exports are <stem>_<graph>")
    ap.add_argument("--pub-graphs", default="recommendations,northwind,fincen")
    ap.add_argument("--v2-export", default="naacl_v2_heldout")
    ap.add_argument("--main-ledger", default=None, help="Default: <ledger-dir>/<prefix>_spend.jsonl, then _generation_spend.jsonl")
    ap.add_argument("--gen9b-ledger", default=None)
    ap.add_argument("--pub-ledger", default=None)
    ap.add_argument("--hosted-ledger", default="artifacts/naacl_v3/ledgers/openai_gpt6luna_spend.jsonl")
    # Audits.
    ap.add_argument("--audit-file", default="artifacts/naacl_v3/audit/full_gpt6luna_checklist.jsonl")
    ap.add_argument("--audit-snapshot-root", default="experiments/snapshots/20261113_naacl_v3")
    # Downstream.
    ap.add_argument("--models", default=",".join(MODELS))
    ap.add_argument("--all-eval-prefix", default="naacl_v3_all")
    ap.add_argument("--heldout-eval-prefix", default="naacl_v3_heldout")
    ap.add_argument("--local-eval-glob", default="naacl_v3_local_*")
    ap.add_argument("--pubeval-prefix", default="naacl_v3_pubeval")
    ap.add_argument("--anchor-prefix", default="naacl_anchor")
    ap.add_argument("--anchor-index", default="artifacts/external_benchmarks/t2c2024_d9f1554_recommended_audited/test.jsonl")
    ap.add_argument("--min-rank-models", type=int, default=4)
    # Generator swap.
    ap.add_argument("--genswap-dir", default="artifacts/naacl_v3/genswap")
    ap.add_argument("--genswap-replay", action="append", default=None,
                    help="NAME=GLOB of replay JSONL (repeatable). Default: glm, gpt6luna, qwen9b -> <genswap-dir>/<name>_*.jsonl")
    ap.add_argument("--genswap-sets", default="original,gpt6luna,qwen9b")
    ap.add_argument("--genswap-eval-prefix", default="naacl_v3_genswap")
    ap.add_argument("--genswap-bench-root", default="artifacts/benchmarks/naacl_v3_genswap")
    # gen9b comparison and statistics.
    ap.add_argument("--gen9b-compare-target", type=int, default=25)
    ap.add_argument("--bootstrap-iterations", type=int, default=2000)
    ap.add_argument("--skip-bootstrap", action="store_true", help="Point estimates only (fast)")
    args = ap.parse_args(argv)
    args.models = [m for m in args.models.split(",") if m]
    args.pub_graphs = [g for g in args.pub_graphs.split(",") if g]
    args.genswap_sets = [s for s in args.genswap_sets.split(",") if s]
    if not args.genswap_replay:
        args.genswap_replay = [f"{name}={Path(args.genswap_dir) / f'{name}_*.jsonl'}" for name in ("glm", "gpt6luna", "qwen9b")]
    return args


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    bench_root = Path(args.benchmarks_root)
    audit_root = Path(args.audit_snapshot_root)
    pub_exports = [f"{args.pub_export_stem}_{g}" for g in args.pub_graphs]
    res: dict[str, Any] = {
        "meta": {
            "generated_at": dt.datetime.now(dt.UTC).isoformat(),
            "git_head": git_head(),
            "args": {k: v for k, v in vars(args).items()},
            "funnel_buckets": list(FUNNEL_BUCKETS),
            "max_prediction_failure_rate": MAX_PREDICTION_FAILURE_RATE,
            "self_bleu_sample_size": SELF_BLEU_SAMPLE,
        }
    }
    sections: list[tuple[str, Callable[[], Any]]] = [
        ("build", lambda: {
            "full": build_section(args, args.main_prefix, [args.main_export], args.main_ledger),
            "gen9b": build_section(args, args.gen9b_prefix, [args.gen9b_export], args.gen9b_ledger),
            "pub": build_section(args, args.pub_prefix, pub_exports, args.pub_ledger),
        }),
        ("export", lambda: {
            **{name: export_section(bench_root, name, audit_root) for name in [args.main_export, args.gen9b_export, *pub_exports]},
            "v2_baseline": export_section(bench_root, args.v2_export, None),
            "v1_baseline": V1_DIVERSITY,
        }),
    ]
    for name, fn in sections:
        res[name] = guarded(fn)
        print(f"[{name}] done", file=sys.stderr)
    downstream = guarded(downstream_section, args)
    if isinstance(downstream, tuple):
        res["downstream"], zero_all = downstream
    else:
        res["downstream"], zero_all = downstream, {}
    print("[downstream] done", file=sys.stderr)
    for name, fn in (
        ("stability", lambda: stability_section(args, zero_all)),
        ("rank_agreement", lambda: rank_agreement_section(args)),
        ("audit", lambda: audit_section(args)),
        ("genswap", lambda: genswap_section(args)),
        ("gen9b_vs_full", lambda: gen9b_vs_full_section(args)),
        ("hosted_spend", lambda: hosted_spend_section(Path(args.hosted_ledger))),
    ):
        res[name] = guarded(fn)
        print(f"[{name}] done", file=sys.stderr)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(to_jsonable(res), indent=2, default=str) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
