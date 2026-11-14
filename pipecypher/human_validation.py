"""Human validation for the NAACL v3 benchmark (plan section 3, item 8).

Three parts:

* **Sampler.** Draws a stratified sample (default 200 items) over
  ``graph x category x difficulty tier x focus``. "Focus" items are those no
  downstream model solves or on which judges disagree; they and the hard tier
  are oversampled. Every item carries the inclusion weight ``N_h / n_h`` of
  its stratum, so population rates can be re-weighted.
* **Page data.** Two annotators label 130 items each, 60 of them shared (for
  inter-annotator agreement), in independently randomized orders. ``items.json``
  holds only what annotators need: id, graph, question, reference Cypher, the
  first result rows, and a schema slice. Verdicts, solve counts, category,
  and tier stay in the private key file, so annotators label blind.
* **Readback.** Converts label rows (an ``ArtifactData`` dump of the page's
  ``labels`` collection, or the page's JSON download) into ``labels.jsonl``.
  It then computes inter-annotator agreement, weighted error and ambiguity
  rates with stratified bootstrap CIs, and judge-human agreement.

Item files and label files contain questions, Cypher literals, and result
rows: they are PRIVATE/internal.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .calibration import wilson_interval
from .judge_agreement import PIPELINE_EXECUTION_ROW_LIMIT, cohen_kappa, gwet_ac1
from .judge import CHECKLIST_CRITERIA, CHECKLIST_NA_FAILS
from .models import SchemaSummary

TIERS = ("easy", "medium", "hard")
REFERENCE_LABELS = ("correct", "minor", "wrong")
CLARITY_LABELS = ("clear", "ambiguous")
FOCUS = "focus"
REGULAR = "regular"
DEFAULT_TIER_FIELDS = ("difficulty_tier", "tier", "difficulty")
PRIVATE_NOTICE = (
    "PRIVATE/internal: contains benchmark questions, Cypher literals, and graph result values."
)

# Convention topics annotators can name when a question is ambiguous. They
# mirror the v2 judge-disagreement taxonomy (counting unit, boundaries, hop
# ranges, ties, ...). Keep the values stable: readback groups by them.
UNCLEAR_CONVENTIONS = (
    ("count_unit", "What is counted (distinct entities, rows, or relationships)"),
    ("comparison_boundary", "Strict or inclusive comparison (after / before / at least)"),
    ("time_window", "Time window or date boundary"),
    ("hop_range", "Hop count or path length (exactly k or up to k)"),
    ("direction_role", "Relationship direction or role (sender vs receiver)"),
    ("ranking_ties", "Ranking, top-k size, or tie handling"),
    ("self_loops_duplicates", "Self-loops, the start entity itself, or duplicates"),
    ("answer_columns", "Which attributes to return"),
    ("entity_reference", "Which entity or value the question refers to"),
    ("other", "Something else (explain in the note)"),
)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows = []
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def load_export(export_dir: str | Path, split: str = "all") -> list[dict[str, Any]]:
    """Rows of an exported benchmark; adds ``_split`` from the split files when present."""

    base = Path(export_dir)
    rows = read_jsonl(base / f"{split}.jsonl")
    split_of: dict[str, str] = {}
    for name in ("train", "dev", "test"):
        path = base / f"{name}.jsonl"
        if path.exists():
            for row in read_jsonl(path):
                split_of[str(row.get("id"))] = name
    for row in rows:
        row.setdefault("_split", split_of.get(str(row.get("id")), split if split != "all" else ""))
    return rows


def tier_of(row: dict[str, Any], tier_field: str | None = None) -> str:
    fields = (tier_field,) if tier_field else DEFAULT_TIER_FIELDS
    for name in fields:
        value = row.get(name)
        if value in (None, "") and name == "difficulty":
            value = (row.get("structural_features") or {}).get("difficulty")
        if value not in (None, ""):
            value = str(value).lower()
            return value if value in TIERS else "unknown"
    return "unknown"


def load_solve_counts(paths: Iterable[str | Path]) -> tuple[dict[str, int], dict[str, int]]:
    """Per-item solve counts from downstream evaluation files (one model each).

    Uses ``projected_execution_accuracy`` when present (the paper's headline
    metric), else ``execution_accuracy``. Returns ``(solved, evaluated)``.
    """

    solved: Counter[str] = Counter()
    evaluated: Counter[str] = Counter()
    for path in paths:
        seen: set[str] = set()
        for row in read_jsonl(path):
            item_id = str(row.get("id") or row.get("item_id") or "")
            if not item_id or item_id in seen:
                continue
            seen.add(item_id)
            value = row.get("projected_execution_accuracy")
            if value is None:
                value = row.get("execution_accuracy")
            evaluated[item_id] += 1
            if bool(value):
                solved[item_id] += 1
    return dict(solved), dict(evaluated)


_DECISION_KEYS = ("decision", "judge_pass", "passed", "pass", "verdict", "accepted")


def _decision(row: dict[str, Any]) -> bool | None:
    for key in _DECISION_KEYS:
        if key not in row:
            continue
        value = row[key]
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"pass", "passed", "accept", "accepted", "yes", "true", "correct"}:
                return True
            if lowered in {"fail", "failed", "reject", "rejected", "no", "false", "wrong"}:
                return False
    return None


def load_verdicts(specs: dict[str, str | Path]) -> dict[str, dict[str, bool]]:
    """``{item_id: {judge_name: passed}}`` from JSONL files of judge verdicts.

    Rows need an id (``item_id`` or ``id``) and a decision (``decision``,
    ``judge_pass``, ``passed``, ``pass``, ``verdict``, or ``accepted``). Rows
    with an error or no decision are skipped.
    """

    verdicts: dict[str, dict[str, bool]] = defaultdict(dict)
    for name, path in specs.items():
        for row in read_jsonl(path):
            if row.get("error"):
                continue
            item_id = str(row.get("item_id") or row.get("id") or "")
            decision = _decision(row)
            if item_id and decision is not None:
                verdicts[item_id][name] = decision
    return dict(verdicts)


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------


def _hash_key(seed: Any, key: str) -> str:
    return hashlib.sha256(f"{seed}:{key}".encode("utf-8")).hexdigest()


def focus_reasons(
    item_id: str,
    *,
    solved: dict[str, int] | None,
    evaluated: dict[str, int] | None,
    verdicts: dict[str, dict[str, bool]] | None,
) -> list[str]:
    reasons = []
    if evaluated and evaluated.get(item_id, 0) > 0 and (solved or {}).get(item_id, 0) == 0:
        reasons.append("unsolved")
    item_verdicts = (verdicts or {}).get(item_id) or {}
    if len(set(item_verdicts.values())) > 1:
        reasons.append("judge_disagreement")
    return reasons


def stratum_key(row: dict[str, Any], tier: str, focus: bool) -> str:
    return "::".join(
        [
            str(row.get("graph_profile") or "unknown"),
            str(row.get("category") or "unknown"),
            tier,
            FOCUS if focus else REGULAR,
        ]
    )


def allocate(
    sizes: dict[str, int],
    boosts: dict[str, float],
    n: int,
    *,
    min_per_stratum: int = 1,
    seed: Any = 17,
) -> dict[str, int]:
    """Boosted proportional allocation with caps (``n_h <= N_h``) and a floor.

    Each stratum's share is proportional to ``N_h * boost_h``. Strata with
    ``N_h > 0`` get at least ``min(min_per_stratum, N_h)`` items. Shares are
    rounded by largest remainder (ties broken by a seeded hash), and any
    excess over a cap is redistributed, so the total equals
    ``min(n, sum(N_h))``.
    """

    keys = [key for key, size in sizes.items() if size > 0]
    total_population = sum(sizes[key] for key in keys)
    target = min(n, total_population)
    alloc = {key: 0 for key in sizes}
    if target <= 0:
        return alloc
    floor = {key: min(min_per_stratum, sizes[key]) for key in keys}
    if sum(floor.values()) >= target:
        # Too many strata for the floor: give one item to the largest boosted strata.
        order = sorted(keys, key=lambda key: (-sizes[key] * boosts.get(key, 1.0), _hash_key(seed, key)))
        for key in order[:target]:
            alloc[key] = 1
        return alloc
    for key in keys:
        alloc[key] = floor[key]
    remaining = target - sum(alloc.values())
    open_keys = [key for key in keys if alloc[key] < sizes[key]]
    while remaining > 0 and open_keys:
        weight = {key: sizes[key] * boosts.get(key, 1.0) for key in open_keys}
        weight_total = sum(weight.values())
        quotas = {key: remaining * weight[key] / weight_total for key in open_keys}
        added = 0
        for key in open_keys:
            take = min(math.floor(quotas[key]), sizes[key] - alloc[key])
            alloc[key] += take
            added += take
        remaining -= added
        if remaining > 0:
            order = sorted(
                (key for key in open_keys if alloc[key] < sizes[key]),
                key=lambda key: (-(quotas[key] - math.floor(quotas[key])), _hash_key(seed, key)),
            )
            for key in order:
                if remaining == 0:
                    break
                alloc[key] += 1
                remaining -= 1
        open_keys = [key for key in keys if alloc[key] < sizes[key]]
    return alloc


@dataclass
class SampledItem:
    row: dict[str, Any]
    stratum: str
    tier: str
    focus_reasons: list[str]
    population: int
    sample_size: int
    solved: int | None = None
    evaluated: int | None = None
    verdicts: dict[str, bool] = field(default_factory=dict)

    @property
    def item_id(self) -> str:
        return str(self.row.get("id"))

    @property
    def weight(self) -> float:
        return self.population / self.sample_size if self.sample_size else 0.0


MIXED = "mixed"


def collapse_strata(
    strata: dict[str, list[Any]],
    max_strata: int,
    *,
    hard_boost: float = 2.0,
    focus_boost: float = 2.0,
) -> dict[str, list[Any]]:
    """Merge focus/regular siblings within a cell, smallest first, until ``len <= max_strata``."""

    strata = {key: list(members) for key, members in strata.items() if members}

    def boosted(key: str) -> float:
        _, _, tier, focus = key.split("::")
        return len(strata[key]) * (hard_boost if tier == "hard" else 1.0) * (focus_boost if focus == FOCUS else 1.0)

    while len(strata) > max_strata:
        cells: dict[str, list[str]] = defaultdict(list)
        for key in strata:
            cells[key.rsplit("::", 1)[0]].append(key)
        candidates = [key for keys in cells.values() if len(keys) > 1 for key in keys]
        if not candidates:
            break
        smallest = min(candidates, key=lambda key: (boosted(key), key))
        cell = smallest.rsplit("::", 1)[0]
        members = [m for key in cells[cell] for m in strata.pop(key)]
        strata[f"{cell}::{MIXED}"] = members
    return strata


def sample_items(
    rows: list[dict[str, Any]],
    *,
    n: int = 200,
    seed: int = 17,
    hard_boost: float = 2.0,
    focus_boost: float = 2.0,
    min_per_stratum: int = 1,
    tier_field: str | None = None,
    solved: dict[str, int] | None = None,
    evaluated: dict[str, int] | None = None,
    verdicts: dict[str, dict[str, bool]] | None = None,
    max_strata: int | None = None,
) -> list[SampledItem]:
    """Seeded stratified sample over graph x category x tier x focus.

    ``max_strata`` (optional) collapses strata when there are more than the
    sample can cover: the smallest boosted stratum that has a sibling in the
    same graph x category x tier cell is merged into that sibling (key suffix
    ``mixed``, no focus boost) until at most ``max_strata`` remain. Every cell
    keeps a stratum, so with ``min_per_stratum >= 1`` every cell is sampled and
    inclusion weights stay exact (simple random sampling within each stratum).
    """

    strata: dict[str, list[tuple[dict[str, Any], str, list[str]]]] = defaultdict(list)
    for row in rows:
        item_id = str(row.get("id"))
        tier = tier_of(row, tier_field)
        reasons = focus_reasons(item_id, solved=solved, evaluated=evaluated, verdicts=verdicts)
        strata[stratum_key(row, tier, bool(reasons))].append((row, tier, reasons))
    if max_strata is not None:
        strata = collapse_strata(strata, max_strata, hard_boost=hard_boost, focus_boost=focus_boost)
    sizes = {key: len(members) for key, members in strata.items()}
    boosts = {}
    for key in strata:
        _, _, tier, focus = key.split("::")
        boost = 1.0
        if tier == "hard":
            boost *= hard_boost
        if focus == FOCUS:
            boost *= focus_boost
        boosts[key] = boost
    alloc = allocate(sizes, boosts, n, min_per_stratum=min_per_stratum, seed=seed)
    sampled: list[SampledItem] = []
    for key in sorted(strata):
        if not alloc.get(key):
            continue
        members = sorted(strata[key], key=lambda member: str(member[0].get("id")))
        rng = random.Random(f"{seed}:{key}")
        for row, tier, reasons in sorted(rng.sample(members, alloc[key]), key=lambda m: str(m[0].get("id"))):
            item_id = str(row.get("id"))
            sampled.append(
                SampledItem(
                    row=row,
                    stratum=key,
                    tier=tier,
                    focus_reasons=reasons,
                    population=sizes[key],
                    sample_size=alloc[key],
                    solved=(solved or {}).get(item_id) if evaluated and item_id in evaluated else None,
                    evaluated=(evaluated or {}).get(item_id),
                    verdicts=dict((verdicts or {}).get(item_id) or {}),
                )
            )
    return sampled


def assign_annotators(
    items: list[SampledItem],
    *,
    annotators: tuple[str, ...] = ("A", "B"),
    per_annotator: int = 130,
    shared: int = 60,
    seed: int = 17,
) -> dict[str, Any]:
    """Split items into a shared set (labeled by every annotator) and unique sets.

    The shared set is spread across strata: items are ordered by stratum and
    a seeded hash, and every k-th one is taken. Each annotator sees the shared
    items mixed among the first part of their queue, so agreement is measurable
    even if they do not finish. Orders are independent per annotator.
    """

    ids = [item.item_id for item in items]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate item ids in sample")
    count = len(annotators)
    unique_each = per_annotator - shared
    needed = shared + unique_each * count
    if unique_each < 0:
        raise ValueError("shared must not exceed per_annotator")
    if len(items) < needed:
        raise ValueError(f"need {needed} items for {count} annotators x {per_annotator} ({shared} shared), got {len(items)}")
    ordered = sorted(items, key=lambda item: (item.stratum, _hash_key(seed, item.item_id)))
    if shared:
        step = len(ordered) / shared
        shared_idx = {min(len(ordered) - 1, math.floor(i * step + step / 2)) for i in range(shared)}
        while len(shared_idx) < shared:  # only when step < 1 rounding collides
            shared_idx.add(next(i for i in range(len(ordered)) if i not in shared_idx))
    else:
        shared_idx = set()
    shared_ids = [ordered[i].item_id for i in sorted(shared_idx)]
    rest = [item for i, item in enumerate(ordered) if i not in shared_idx]
    random.Random(f"{seed}:unique").shuffle(rest)
    unique: dict[str, list[str]] = {}
    for index, annotator in enumerate(annotators):
        chunk = rest[index * unique_each : (index + 1) * unique_each]
        # Keep each annotator's unique set stratum-balanced: interleave by stratum.
        unique[annotator] = [item.item_id for item in sorted(chunk, key=lambda it: (it.stratum, it.item_id))]
    queues: dict[str, list[str]] = {}
    for annotator in annotators:
        rng = random.Random(f"{seed}:order:{annotator}")
        own = list(unique[annotator])
        rng.shuffle(own)
        head_unique = own[:shared]
        tail_unique = own[shared:]
        head = list(shared_ids) + head_unique
        rng.shuffle(head)
        queues[annotator] = head + tail_unique
    unassigned = [item_id for item_id in ids if item_id not in set(shared_ids).union(*map(set, unique.values()))]
    return {
        "annotators": list(annotators),
        "per_annotator": per_annotator,
        "shared": shared_ids,
        "unique": unique,
        "queues": queues,
        "unassigned": unassigned,
        "seed": seed,
    }


# ---------------------------------------------------------------------------
# Page data and key
# ---------------------------------------------------------------------------


def schema_slice_text(schema: SchemaSummary | None, labels: Iterable[str], rel_types: Iterable[str]) -> str:
    """Schema lines for the labels and relationship types an item uses."""

    if schema is None:
        return ""
    labels = set(labels)
    rel_types = set(rel_types)
    rels = [
        rel
        for rel in schema.relationships
        if rel.type in rel_types and (not labels or rel.start_label in labels or rel.end_label in labels)
    ]
    node_props = [prop for prop in schema.node_properties if prop.label in labels]
    rel_props = [prop for prop in schema.relationship_properties if prop.type in rel_types]
    sliced = SchemaSummary(
        node_properties=node_props,
        relationship_properties=rel_props,
        relationships=rels,
        categorical_properties={
            key: values
            for key, values in schema.categorical_properties.items()
            if key.split(".", 1)[0] in labels or key.split(".", 1)[0] in rel_types
        },
        graph_name=schema.graph_name,
        symmetric_relationships=[rel for rel in schema.symmetric_relationships if rel in rel_types],
    )
    text = sliced.to_prompt(max_items=200)
    # The slice has only the item's labels; say so instead of listing every label.
    return text.replace("Node labels: ", "Labels used: ", 1)


_JS_SAFE_INT = 2**53 - 1


def _jsonable(value: Any) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, (str, float)):
        return value
    if isinstance(value, int):
        # JavaScript numbers lose precision above 2^53; show such ids as text.
        return value if abs(value) <= _JS_SAFE_INT else str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return str(value)


def page_item(row: dict[str, Any], schema: SchemaSummary | None, *, preview_rows: int = 5) -> dict[str, Any]:
    """The only fields annotators see. No category, tier, verdicts, or model results."""

    features = row.get("structural_features") or {}
    rows = list(row.get("result_rows_sample") or [])[:preview_rows]
    columns: list[str] = []
    for result in rows:
        for key in result:
            if key not in columns:
                columns.append(key)
    if not columns:
        columns = list((row.get("answer_contract") or {}).get("result_columns") or [])
    observed = int(row.get("result_row_count_observed") or len(row.get("result_rows_sample") or []))
    return {
        "id": str(row.get("id")),
        "graph": str(row.get("graph_profile") or ""),
        "question": str(row.get("question") or ""),
        "cypher": str(row.get("normalized_cypher") or row.get("cypher") or ""),
        "columns": columns,
        "rows": [[_jsonable(result.get(column)) for column in columns] for result in rows],
        "row_count": observed,
        "row_count_capped": observed >= PIPELINE_EXECUTION_ROW_LIMIT,
        "schema": schema_slice_text(
            schema,
            features.get("labels") or [],
            features.get("relationship_types") or [],
        ),
    }


def load_conventions(path: str | Path | None = None) -> list[dict[str, str]]:
    """Convention sheet entries ``[{"name", "rule"}]`` for the instructions panel.

    Reads a JSON file when given; otherwise tries ``pipecypher.conventions``
    (any of ``CONVENTIONS``, ``CONVENTION_SHEET``, ``conventions()``), which
    another workstream writes. Returns [] when neither is available.
    """

    raw: Any = None
    if path:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    else:
        try:
            from . import conventions as module  # type: ignore[attr-defined]
        except Exception:
            return []
        for name in ("CONVENTIONS", "CONVENTION_SHEET", "CONVENTION_RULES"):
            if hasattr(module, name):
                raw = getattr(module, name)
                break
        if raw is None and callable(getattr(module, "conventions", None)):
            raw = module.conventions()
    return normalize_conventions(raw)


_CONVENTION_LINE = re.compile(r"^(C\d+)\s+([^.]{1,40})\.\s+(.*)$")


def normalize_conventions(raw: Any) -> list[dict[str, str]]:
    if raw is None:
        return []
    if isinstance(raw, str):
        entries = []
        for line in (line.strip().lstrip("-*• ").strip() for line in raw.splitlines()):
            if not line:
                continue
            match = _CONVENTION_LINE.match(line)
            if match:
                entries.append({"name": f"{match.group(1)} {match.group(2)}", "rule": match.group(3)})
            elif entries and entries[-1]["name"] and not line.endswith(":"):
                entries[-1]["rule"] += " " + line  # wrapped continuation line
            else:
                entries.append({"name": "", "rule": line})
        return entries
    if isinstance(raw, dict):
        return [{"name": str(k), "rule": str(v)} for k, v in raw.items()]
    entries = []
    for item in raw:
        if isinstance(item, str):
            entries.append({"name": "", "rule": item})
        elif isinstance(item, dict):
            name = item.get("name") or item.get("id") or item.get("key") or item.get("topic") or ""
            rule = item.get("rule") or item.get("text") or item.get("description") or item.get("convention") or ""
            if rule:
                entries.append({"name": str(name), "rule": str(rule)})
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            entries.append({"name": str(item[0]), "rule": str(item[1])})
        else:
            for attr_name, attr_rule in (("name", "rule"), ("key", "text"), ("id", "description")):
                if hasattr(item, attr_rule):
                    entries.append({"name": str(getattr(item, attr_name, "")), "rule": str(getattr(item, attr_rule))})
                    break
    return entries


def unclear_convention_options(conventions: list[dict[str, str]]) -> list[dict[str, str]]:
    """Choices for "which convention is unclear": the sheet's rules, else generic topics."""

    named = [entry for entry in conventions if entry.get("name")]
    if not named:
        return [{"value": value, "label": label} for value, label in UNCLEAR_CONVENTIONS]
    options = [{"value": entry["name"].split()[0], "label": entry["name"]} for entry in named]
    options.append({"value": "not_covered", "label": "Not covered by any convention"})
    return options


def build_page_data(
    items: list[SampledItem],
    assignment: dict[str, Any],
    *,
    schemas: dict[str, SchemaSummary],
    set_id: str,
    conventions: list[dict[str, str]] | None = None,
    preview_rows: int = 5,
) -> dict[str, Any]:
    by_id = {item.item_id: item for item in items}
    queued = {item_id for queue in assignment["queues"].values() for item_id in queue}
    return {
        "set_id": set_id,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "row_limit": PIPELINE_EXECUTION_ROW_LIMIT,
        "conventions": conventions or [],
        "unclear_conventions": unclear_convention_options(conventions or []),
        "annotators": {name: list(queue) for name, queue in assignment["queues"].items()},
        "items": {
            item_id: page_item(by_id[item_id].row, schemas.get(str(by_id[item_id].row.get("graph_profile"))), preview_rows=preview_rows)
            for item_id in sorted(queued)
        },
    }


def build_key(items: list[SampledItem], assignment: dict[str, Any], *, set_id: str) -> list[dict[str, Any]]:
    shared = set(assignment["shared"])
    owners = {item_id: name for name, ids in assignment["unique"].items() for item_id in ids}
    key_rows = []
    for item in items:
        features = item.row.get("structural_features") or {}
        key_rows.append(
            {
                "set_id": set_id,
                "item_id": item.item_id,
                "graph_profile": item.row.get("graph_profile"),
                "category": item.row.get("category"),
                "tier": item.tier,
                "split": item.row.get("_split", ""),
                "primary_strategy": features.get("primary_strategy", ""),
                "query_signature": item.row.get("query_signature", ""),
                "stratum": item.stratum,
                "stratum_population": item.population,
                "stratum_sample_size": item.sample_size,
                "weight": item.weight,
                "focus_reasons": item.focus_reasons,
                "solved": item.solved,
                "evaluated": item.evaluated,
                "verdicts": item.verdicts,
                "shared": item.item_id in shared,
                "annotators": list(assignment["annotators"]) if item.item_id in shared else ([owners[item.item_id]] if item.item_id in owners else []),
            }
        )
    return key_rows


def sample_summary(items: list[SampledItem], assignment: dict[str, Any], population: list[dict[str, Any]], *, tier_field: str | None = None) -> dict[str, Any]:
    def counts(key_fn, values):
        return dict(sorted(Counter(key_fn(value) for value in values).items()))

    return {
        "population": len(population),
        "sampled": len(items),
        "population_by_tier": counts(lambda row: tier_of(row, tier_field), population),
        "sample_by_tier": counts(lambda item: item.tier, items),
        "sample_by_graph": counts(lambda item: str(item.row.get("graph_profile")), items),
        "sample_by_category": counts(lambda item: str(item.row.get("category")), items),
        "sample_focus": counts(lambda item: "+".join(item.focus_reasons) or REGULAR, items),
        "strata_sampled": len({item.stratum for item in items}),
        "shared": len(assignment["shared"]),
        "queue_lengths": {name: len(queue) for name, queue in assignment["queues"].items()},
        "unassigned": len(assignment["unassigned"]),
        "weight_sum": round(sum(item.weight for item in items), 6),
    }


# ---------------------------------------------------------------------------
# Readback
# ---------------------------------------------------------------------------


def _label_body(entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    for key in ("data", "fields", "body", "value"):
        if isinstance(entry.get(key), dict) and "item_id" in entry[key]:
            return entry[key]
    return entry if "item_id" in entry else None


CHECKLIST_ANSWERS = ("yes", "no", "na")
# Criteria about the reference query; "unambiguous" is about the question.
CONTENT_CRITERIA = tuple(name for name in CHECKLIST_CRITERIA if name != "unambiguous")


def _criterion_fails(name: str, answer: str | None) -> bool:
    return answer == "no" or (answer == "na" and name in CHECKLIST_NA_FAILS)


def checklist_label_fields(checklist: Any) -> dict[str, Any] | None:
    """Map a judge-checklist label (the v3c form) onto the shared label fields.

    Uses the pipeline's verdict rule (``compute_checklist_verdict``): the item
    passes only when no criterion fails. ``reference`` is "wrong" when any
    criterion about the query fails, else "correct" (the checklist has no
    "minor" level); ``clarity`` is "ambiguous" unless "unambiguous" is yes.
    Returns None for an incomplete checklist.
    """

    if not isinstance(checklist, dict):
        return None
    answers = {name: str(checklist.get(name) or "").strip().lower() for name in CHECKLIST_CRITERIA}
    if any(answer not in CHECKLIST_ANSWERS for answer in answers.values()):
        return None
    failing = [name for name in CHECKLIST_CRITERIA if _criterion_fails(name, answers[name])]
    return {
        "checklist": answers,
        "failing": failing,
        "passed": not failing,
        "reference": "wrong" if any(name in failing for name in CONTENT_CRITERIA) else "correct",
        "clarity": "ambiguous" if "unambiguous" in failing else "clear",
    }


def parse_label_dump(payload: Any) -> list[dict[str, Any]]:
    """Normalize label rows from an ``ArtifactData`` dump or the page's download.

    Accepts a list of documents (bare bodies or ``{"id", "data"}`` wrappers), a
    dict with a ``documents`` / ``docs`` / ``labels`` / ``rows`` / ``items``
    list, or several such payloads in a list. Keeps the newest row per
    ``(set_id, annotator, item_id)``.
    """

    entries: list[Any] = []

    def collect(value: Any) -> None:
        if isinstance(value, list):
            for element in value:
                collect(element)
        elif isinstance(value, dict):
            body = _label_body(value)
            if body is not None:
                entries.append(body)
                return
            for key in ("documents", "docs", "labels", "rows", "items", "results"):
                if key in value:
                    collect(value[key])

    collect(payload)
    latest: dict[tuple[str, str, str], dict[str, Any]] = {}
    for body in entries:
        row = {
            "set_id": str(body.get("set_id") or ""),
            "item_id": str(body.get("item_id") or ""),
            "annotator": str(body.get("annotator") or ""),
            "clarity": body.get("clarity") if body.get("clarity") in CLARITY_LABELS else None,
            "unclear_convention": str(body.get("unclear_convention") or ""),
            "reference": body.get("reference") if body.get("reference") in REFERENCE_LABELS else None,
            "note": str(body.get("note") or ""),
            "skipped": bool(body.get("skipped")),
            "updated_at": str(body.get("updated_at") or ""),
            "seconds": body.get("seconds"),
        }
        if "checklist" in body:
            derived = checklist_label_fields(body.get("checklist"))
            row.update(derived or {"checklist": None, "failing": [], "passed": None, "reference": None, "clarity": None})
            row["clarified_question"] = str(body.get("clarified_question") or "")
        if not row["item_id"] or not row["annotator"]:
            continue
        key = (row["set_id"], row["annotator"], row["item_id"])
        if key not in latest or row["updated_at"] >= latest[key]["updated_at"]:
            latest[key] = row
    return sorted(latest.values(), key=lambda r: (r["set_id"], r["annotator"], r["item_id"]))


def completed(label: dict[str, Any]) -> bool:
    return not label.get("skipped") and label.get("reference") in REFERENCE_LABELS and label.get("clarity") in CLARITY_LABELS


def weighted_rate(
    values: dict[str, float],
    key_rows: dict[str, dict[str, Any]],
    *,
    n_boot: int = 2000,
    seed: int = 17,
) -> dict[str, Any]:
    """Ratio estimate ``sum(w y) / sum(w)`` with a stratified bootstrap CI.

    Weights are recomputed from the labeled items: ``N_h / m_h`` where ``m_h``
    is the number of labeled items in stratum ``h``. Strata with no labels
    drop out; ``population_coverage`` reports the share of the population
    their strata represent.
    """

    by_stratum: dict[str, list[float]] = defaultdict(list)
    population: dict[str, int] = {}
    for item_id, value in values.items():
        key = key_rows.get(item_id)
        if key is None:
            continue
        by_stratum[key["stratum"]].append(float(value))
        population[key["stratum"]] = int(key["stratum_population"])
    total_population = sum({row["stratum"]: int(row["stratum_population"]) for row in key_rows.values()}.values())
    n = sum(len(v) for v in by_stratum.values())
    if n == 0:
        return {"n": 0, "estimate": None, "ci95": None, "unweighted": None, "population_coverage": 0.0}

    def estimate(groups: dict[str, list[float]]) -> float:
        numerator = sum(population[h] * (sum(ys) / len(ys)) for h, ys in groups.items() if ys)
        denominator = sum(population[h] for h, ys in groups.items() if ys)
        return numerator / denominator

    point = estimate(by_stratum)
    # Item-level weighted bootstrap: resample labeled items across the whole sample,
    # each keeping its inverse inclusion weight N_h / m_h. (A within-stratum bootstrap
    # has no variance when most strata hold one labeled item.)
    weighted = [(population[h] / len(ys), y) for h, ys in by_stratum.items() for y in ys]
    rng = random.Random(seed)
    boots = []
    for _ in range(n_boot):
        draw = [weighted[rng.randrange(len(weighted))] for _ in weighted]
        total = sum(w for w, _ in draw)
        boots.append(sum(w * y for w, y in draw) / total)
    boots.sort()
    low = boots[int(0.025 * (n_boot - 1))]
    high = boots[int(math.ceil(0.975 * (n_boot - 1)))]
    flat = [y for ys in by_stratum.values() for y in ys]
    covered = sum(population[h] for h in by_stratum)
    return {
        "n": n,
        "estimate": point,
        "ci95": [low, high],
        "unweighted": sum(flat) / len(flat),
        "population_coverage": covered / total_population if total_population else None,
    }


def _kappa_block(labels_a: list[Any], labels_b: list[Any]) -> dict[str, Any]:
    n = len(labels_a)
    agree = sum(1 for a, b in zip(labels_a, labels_b) if a == b)
    return {
        "n": n,
        "agreement": agree / n if n else None,
        "cohen_kappa": cohen_kappa(labels_a, labels_b) if n else None,
        "gwet_ac1": gwet_ac1(labels_a, labels_b) if n else None,
    }


def inter_annotator(labels: list[dict[str, Any]], key_rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    by_item: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for label in labels:
        if completed(label) and key_rows.get(label["item_id"], {}).get("shared"):
            by_item[label["item_id"]][label["annotator"]] = label
    annotators = sorted({label["annotator"] for label in labels})
    pairs = {}
    for i, first in enumerate(annotators):
        for second in annotators[i + 1 :]:
            items = [item for item, by in by_item.items() if first in by and second in by]
            a = [by_item[item][first] for item in items]
            b = [by_item[item][second] for item in items]
            pairs[f"{first}|{second}"] = {
                "reference_3way": _kappa_block([x["reference"] for x in a], [x["reference"] for x in b]),
                "reference_acceptable": _kappa_block(
                    [x["reference"] != "wrong" for x in a], [x["reference"] != "wrong" for x in b]
                ),
                "reference_correct": _kappa_block(
                    [x["reference"] == "correct" for x in a], [x["reference"] == "correct" for x in b]
                ),
                "question_clear": _kappa_block([x["clarity"] for x in a], [x["clarity"] for x in b]),
                "verdict_pass": _kappa_block(
                    [x["reference"] == "correct" and x["clarity"] == "clear" for x in a],
                    [x["reference"] == "correct" and x["clarity"] == "clear" for x in b],
                ),
                "disagreements": [
                    {"item_id": item, first: by_item[item][first]["reference"], second: by_item[item][second]["reference"]}
                    for item in items
                    if by_item[item][first]["reference"] != by_item[item][second]["reference"]
                ],
            }
    return pairs


def item_outcomes(
    labels: list[dict[str, Any]],
    adjudication: dict[str, dict[str, str]] | None = None,
) -> dict[str, dict[str, float]]:
    """Per-item outcome rates, averaging annotators (shared items count 0, 0.5, or 1).

    An adjudication entry ``{item_id: {"reference": ..., "clarity": ...}}``
    overrides the annotators' labels for that item.
    """

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for label in labels:
        if completed(label):
            grouped[label["item_id"]].append(label)
    outcomes: dict[str, dict[str, float]] = {}
    for item_id, group in grouped.items():
        override = (adjudication or {}).get(item_id) or {}
        refs = [override["reference"]] if override.get("reference") in REFERENCE_LABELS else [g["reference"] for g in group]
        clar = [override["clarity"]] if override.get("clarity") in CLARITY_LABELS else [g["clarity"] for g in group]
        outcomes[item_id] = {
            "wrong": sum(r == "wrong" for r in refs) / len(refs),
            "wrong_or_minor": sum(r in ("wrong", "minor") for r in refs) / len(refs),
            "ambiguous": sum(c == "ambiguous" for c in clar) / len(clar),
            "human_ok_strict": sum(r == "correct" for r in refs) / len(refs) * (sum(c == "clear" for c in clar) / len(clar)),
            "human_ok_lenient": sum(r != "wrong" for r in refs) / len(refs),
        }
        if not override:
            # Mean over annotators of the per-label verdict (strict = the judges' rule for checklist labels).
            outcomes[item_id]["fail"] = sum(
                not (g["reference"] == "correct" and g["clarity"] == "clear") for g in group
            ) / len(group)
        else:
            outcomes[item_id]["fail"] = 1.0 - outcomes[item_id]["human_ok_strict"]
    return outcomes


def criterion_report(
    labels: list[dict[str, Any]],
    key_rows: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Per-criterion results for checklist labels.

    ``fail_rate``: share of completed labels failing the criterion (unweighted).
    ``vs_judges``: for each judge whose checklist is stored in the key
    (``judge_checklists``), agreement on the criterion's pass/fail and on the
    exact answer, one comparison per (item, annotator) label.
    ``between_annotators``: the same on shared items.
    """

    checklist_labels = [label for label in labels if completed(label) and label.get("checklist")]
    if not checklist_labels:
        return {}
    judges = sorted({name for row in key_rows.values() for name in (row.get("judge_checklists") or {})})
    report: dict[str, Any] = {}
    for name in CHECKLIST_CRITERIA:
        entry: dict[str, Any] = {
            "n": len(checklist_labels),
            "fail_rate": sum(_criterion_fails(name, label["checklist"][name]) for label in checklist_labels) / len(checklist_labels),
            "vs_judges": {},
        }
        for judge in judges:
            human_fail, judge_fail, exact = [], [], 0
            for label in checklist_labels:
                answers = ((key_rows.get(label["item_id"], {}).get("judge_checklists") or {}).get(judge) or {}).get("checklist") or {}
                answer = answers.get(name)
                if answer not in CHECKLIST_ANSWERS:
                    continue
                human_fail.append(_criterion_fails(name, label["checklist"][name]))
                judge_fail.append(_criterion_fails(name, answer))
                exact += answer == label["checklist"][name]
            block = _kappa_block(human_fail, judge_fail)
            block["exact_answer_agreement"] = exact / len(human_fail) if human_fail else None
            block["judge_fail_rate"] = sum(judge_fail) / len(judge_fail) if judge_fail else None
            entry["vs_judges"][judge] = block
        by_item: dict[str, dict[str, str]] = defaultdict(dict)
        for label in checklist_labels:
            if key_rows.get(label["item_id"], {}).get("shared"):
                by_item[label["item_id"]][label["annotator"]] = label["checklist"][name]
        pairs = [tuple(v.values()) for v in by_item.values() if len(v) == 2]
        entry["between_annotators"] = _kappa_block(
            [_criterion_fails(name, a) for a, _ in pairs], [_criterion_fails(name, b) for _, b in pairs]
        )
        report[name] = entry
    return report


def judge_human_agreement(
    labels: list[dict[str, Any]],
    verdicts: dict[str, dict[str, bool]],
) -> dict[str, Any]:
    """Agreement between each judge's pass/fail and the human label.

    Each completed (item, annotator) label is one comparison. Two human
    definitions: ``lenient`` (reference not wrong) and ``strict`` (reference
    correct and question clear).
    """

    judges = sorted({name for item in verdicts.values() for name in item})
    report = {}
    for judge in judges:
        block = {}
        for definition in ("lenient", "strict"):
            human, machine = [], []
            for label in labels:
                if not completed(label):
                    continue
                verdict = verdicts.get(label["item_id"], {}).get(judge)
                if verdict is None:
                    continue
                ok = label["reference"] != "wrong" if definition == "lenient" else (
                    label["reference"] == "correct" and label["clarity"] == "clear"
                )
                human.append(ok)
                machine.append(verdict)
            n = len(human)
            judge_pass = sum(machine)
            pass_and_ok = sum(1 for h, m in zip(human, machine) if h and m)
            fail_and_bad = sum(1 for h, m in zip(human, machine) if not h and not m)
            human_bad = n - sum(human)
            block[definition] = {
                **_kappa_block(human, machine),
                "judge_pass_rate": judge_pass / n if n else None,
                "human_ok_rate": sum(human) / n if n else None,
                # Of items the judge passed, how many humans also accept (gate precision).
                "precision": pass_and_ok / judge_pass if judge_pass else None,
                "precision_ci95": list(wilson_interval(pass_and_ok, judge_pass)) if judge_pass else None,
                # Of items humans reject, how many the judge also flags (defect recall).
                "defect_recall": fail_and_bad / human_bad if human_bad else None,
                "defect_recall_ci95": list(wilson_interval(fail_and_bad, human_bad)) if human_bad else None,
            }
        report[judge] = block
    return report


def summarize_labels(
    labels: list[dict[str, Any]],
    key_rows: list[dict[str, Any]],
    *,
    verdicts: dict[str, dict[str, bool]] | None = None,
    adjudication: dict[str, dict[str, str]] | None = None,
    set_id: str | None = None,
    n_boot: int = 2000,
    seed: int = 17,
) -> dict[str, Any]:
    if set_id:
        labels = [label for label in labels if label["set_id"] == set_id]
        key_rows = [row for row in key_rows if row.get("set_id", set_id) == set_id]
    keys = {row["item_id"]: row for row in key_rows}
    labels = [label for label in labels if label["item_id"] in keys]
    outcomes = item_outcomes(labels, adjudication)
    expected = Counter()
    for row in key_rows:
        for name in row.get("annotators") or []:
            expected[name] += 1
    done = Counter(label["annotator"] for label in labels if completed(label))
    skipped = Counter(label["annotator"] for label in labels if label.get("skipped"))
    rates = {
        name: weighted_rate({item: o[name] for item, o in outcomes.items()}, keys, n_boot=n_boot, seed=seed)
        for name in ("wrong", "wrong_or_minor", "ambiguous", "fail")
    }
    by_slice: dict[str, dict[str, Any]] = {}
    for slice_name, field_name in (("graph", "graph_profile"), ("tier", "tier"), ("category", "category")):
        groups: dict[str, list[str]] = defaultdict(list)
        for item_id in outcomes:
            groups[str(keys[item_id].get(field_name))].append(item_id)
        by_slice[slice_name] = {
            value: {
                "n": len(ids),
                "wrong": sum(outcomes[i]["wrong"] for i in ids) / len(ids),
                "wrong_or_minor": sum(outcomes[i]["wrong_or_minor"] for i in ids) / len(ids),
                "ambiguous": sum(outcomes[i]["ambiguous"] for i in ids) / len(ids),
                "fail": sum(outcomes[i]["fail"] for i in ids) / len(ids),
            }
            for value, ids in sorted(groups.items())
        }
    unclear = Counter(
        label["unclear_convention"] or "unspecified"
        for label in labels
        if completed(label) and label["clarity"] == "ambiguous"
    )
    return {
        "privacy": PRIVATE_NOTICE + " This summary holds no literal values.",
        "set_id": set_id,
        "labels": len(labels),
        "items_labeled": len(outcomes),
        "items_in_sample": len(key_rows),
        "progress": {
            name: {"expected": expected[name], "completed": done.get(name, 0), "skipped": skipped.get(name, 0)}
            for name in sorted(set(expected) | set(done))
        },
        "reference_error_rate": rates["wrong"],
        "reference_error_or_minor_rate": rates["wrong_or_minor"],
        "question_ambiguity_rate": rates["ambiguous"],
        "verdict_fail_rate": rates["fail"],
        "criteria": criterion_report(labels, keys),
        "unclear_conventions": dict(unclear.most_common()),
        "by_slice_unweighted": by_slice,
        "inter_annotator": inter_annotator(labels, keys),
        "judge_human": judge_human_agreement(labels, verdicts or {}) if verdicts else {},
        "estimator": (
            "Item outcome = mean over annotators (adjudication overrides). Rates are ratio estimates "
            "sum_h N_h * mean_h / sum_h N_h over strata with labels; 95% CI from an item-level bootstrap with inverse-inclusion weights."
        ),
    }
