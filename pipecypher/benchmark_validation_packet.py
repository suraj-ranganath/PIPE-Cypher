"""Human validation packets for benchmark reference correctness (experiment E2.2).

Two packet modes over an exported benchmark:

* ``templates`` -- exhaustive template-level packet: one group per canonical
  query signature (``diversity_metrics.canonical_query_signature``), with up to
  ``realizations`` seeded instances per signature (default 2).
* ``instances`` -- stratified instance-level sample of accepted items (default
  300) over ``graph_profile x category`` with proportional (self-weighting)
  allocation, deterministic for a given seed.

Each annotator gets an identical set of rows in an independently shuffled
order plus a rubric text file; a key file keeps metadata the annotators should
not see. The analyzer estimates the benchmark reference error rate
(``reference_correct == no``) with Wilson 95% intervals, per-slice rates,
inter-annotator agreement (Cohen's kappa per pair, Fleiss' kappa for >2
annotators), error-type counts, and a disagreement list for adjudication.

Annotator sheets, the disagreement list, and the adjudication file contain
questions, Cypher literals, and result rows: they are PRIVATE/internal.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

from .diversity_metrics import canonical_query_signature
from .judge_agreement import (
    PIPELINE_EXECUTION_ROW_LIMIT,
    PRIVATE_NOTICE,
    cohen_kappa,
    fleiss_kappa_from_ratings,
    format_bool,
    gwet_ac1,
    parse_yes_no,
    rate_with_ci,
    read_csv_rows,
    rows_preview,
    sha256_file,
    tex_escape,
    utc_now,
    write_plain_csv,
    write_private_csv,
)
from .models import SchemaSummary

YES_NO_FIELDS = ("question_unambiguous", "reference_correct", "answer_columns_appropriate")
ERROR_TYPES = (
    "wrong_direction_semantics",
    "missing_results",
    "extra_results",
    "wrong_aggregation",
    "wrong_filter",
    "ambiguous_question",
    "other",
)
RUBRIC_FIELDS = (*YES_NO_FIELDS, "error_type", "notes")

SHEET_FIELDS = [
    "review_order",
    "annotator",
    "item_id",
    "packet_mode",
    "graph_profile",
    "category",
    "difficulty",
    "signature_id",
    "realization_index",
    "question",
    "cypher",
    "result_row_count_observed",
    "result_count_note",
    "result_rows_preview",
    *RUBRIC_FIELDS,
]

KEY_FIELDS = [
    "item_id",
    "packet_mode",
    "graph_profile",
    "category",
    "difficulty",
    "primary_strategy",
    "split",
    "signature_id",
    "canonical_signature",
    "signature_group_size",
    "realization_index",
    "stratum",
    "stratum_population",
    "stratum_sample_size",
    "judge_pass",
    "judge_semantic_alignment",
    "source_run",
]

ADJUDICATION_FIELDS = [f"adjudicated_{name}" for name in (*YES_NO_FIELDS, "error_type")] + [
    "adjudicator",
    "adjudication_notes",
]


# ---------------------------------------------------------------------------
# Packet construction
# ---------------------------------------------------------------------------


def signature_for_row(row: dict[str, Any]) -> str:
    return canonical_query_signature(str(row.get("normalized_cypher") or row.get("cypher") or ""))


def signature_id(signature: str) -> str:
    return "sig_" + hashlib.sha256(signature.encode("utf-8")).hexdigest()[:10]


def _stratum(row: dict[str, Any]) -> str:
    return f"{row.get('graph_profile') or 'unknown'}::{row.get('category') or 'unknown'}"


def _seeded_order_key(seed: Any, key: str) -> str:
    return hashlib.sha256(f"{seed}:{key}".encode("utf-8")).hexdigest()


def _packet_row(
    row: dict[str, Any],
    *,
    mode: str,
    preview_rows: int,
    signature: str,
    signature_size: int,
    realization_index: int | str = "",
    stratum_population: int | str = "",
    stratum_sample_size: int | str = "",
) -> dict[str, Any]:
    features = row.get("structural_features") or {}
    count = int(row.get("result_row_count_observed") or 0)
    scores = row.get("judge_scores") or {}
    gates = row.get("gates") or {}
    source = row.get("source") or {}
    return {
        "item_id": str(row.get("id")),
        "packet_mode": mode,
        "graph_profile": row.get("graph_profile", ""),
        "category": row.get("category", ""),
        "difficulty": row.get("difficulty") or features.get("difficulty", ""),
        "primary_strategy": features.get("primary_strategy", ""),
        "split": row.get("_split", row.get("split", "")),
        "signature_id": signature_id(signature),
        "canonical_signature": signature,
        "signature_group_size": signature_size,
        "realization_index": realization_index,
        "stratum": _stratum(row),
        "stratum_population": stratum_population,
        "stratum_sample_size": stratum_sample_size,
        "judge_pass": format_bool(gates.get("judge_pass")) if "judge_pass" in gates else "",
        "judge_semantic_alignment": scores.get("semantic_alignment", ""),
        "source_run": source.get("run", ""),
        "question": row.get("question", ""),
        "cypher": row.get("normalized_cypher") or row.get("cypher", ""),
        "result_row_count_observed": count,
        "result_count_note": (
            f"at least {PIPELINE_EXECUTION_ROW_LIMIT}: generation stored at most "
            f"{PIPELINE_EXECUTION_ROW_LIMIT} rows"
            if count >= PIPELINE_EXECUTION_ROW_LIMIT
            else ""
        ),
        "result_rows_preview": rows_preview(row.get("result_rows_sample") or [], k=preview_rows),
    }


def build_template_packet(
    rows: list[dict[str, Any]],
    *,
    realizations: int = 2,
    seed: int = 17,
    preview_rows: int = 3,
) -> list[dict[str, Any]]:
    """One group per canonical query signature with up to ``realizations`` items each."""

    if realizations < 1:
        raise ValueError("realizations must be >= 1")
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[signature_for_row(row)].append(row)
    packet: list[dict[str, Any]] = []
    for signature in sorted(groups):
        members = sorted(groups[signature], key=lambda item: str(item.get("id")))
        rng = random.Random(f"{seed}:{signature}")
        chosen = rng.sample(members, min(realizations, len(members)))
        chosen.sort(key=lambda item: str(item.get("id")))
        for index, row in enumerate(chosen, start=1):
            packet.append(
                _packet_row(
                    row,
                    mode="templates",
                    preview_rows=preview_rows,
                    signature=signature,
                    signature_size=len(members),
                    realization_index=index,
                )
            )
    return packet


def proportional_allocation(
    population: dict[str, int],
    n: int,
    *,
    min_per_stratum: int = 1,
    seed: Any = 17,
) -> dict[str, int]:
    """Largest-remainder proportional allocation with a per-stratum floor.

    Ties in fractional remainders are broken by a seeded hash so the result is
    deterministic but not alphabetical.
    """

    total = sum(population.values())
    if n <= 0 or total == 0:
        return {key: 0 for key in population}
    if n >= total:
        return dict(population)
    quotas = {key: n * size / total for key, size in population.items()}
    alloc = {
        key: min(population[key], max(min_per_stratum, math.floor(quotas[key]))) for key in population
    }
    remaining = n - sum(alloc.values())
    order_add = sorted(
        population,
        key=lambda key: (-(quotas[key] - math.floor(quotas[key])), _seeded_order_key(seed, key)),
    )
    while remaining > 0:
        progressed = False
        for key in order_add:
            if remaining == 0:
                break
            if alloc[key] < population[key]:
                alloc[key] += 1
                remaining -= 1
                progressed = True
        if not progressed:
            break
    order_remove = sorted(
        population,
        key=lambda key: (alloc[key] - quotas[key], _seeded_order_key(seed, key)),
        reverse=True,
    )
    while remaining < 0:
        progressed = False
        for key in order_remove:
            if remaining == 0:
                break
            if alloc[key] > min(min_per_stratum, population[key]):
                alloc[key] -= 1
                remaining += 1
                progressed = True
        if not progressed:
            break
    return alloc


def build_instance_packet(
    rows: list[dict[str, Any]],
    *,
    n: int = 300,
    seed: int = 17,
    min_per_stratum: int = 1,
    preview_rows: int = 3,
) -> list[dict[str, Any]]:
    """Seeded stratified sample over graph_profile x category."""

    strata: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        strata[_stratum(row)].append(row)
    signature_sizes = Counter(signature_for_row(row) for row in rows)
    population = {key: len(members) for key, members in strata.items()}
    alloc = proportional_allocation(population, n, min_per_stratum=min_per_stratum, seed=seed)
    packet: list[dict[str, Any]] = []
    for key in sorted(strata):
        members = sorted(strata[key], key=lambda item: str(item.get("id")))
        rng = random.Random(f"{seed}:{key}")
        chosen = rng.sample(members, alloc[key])
        chosen.sort(key=lambda item: str(item.get("id")))
        for row in chosen:
            signature = signature_for_row(row)
            packet.append(
                _packet_row(
                    row,
                    mode="instances",
                    preview_rows=preview_rows,
                    signature=signature,
                    signature_size=signature_sizes[signature],
                    stratum_population=population[key],
                    stratum_sample_size=alloc[key],
                )
            )
    return packet


def annotator_names(count: int = 2, names: list[str] | None = None) -> list[str]:
    if names:
        cleaned = [re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip()).strip("._") for name in names if name.strip()]
        if len(set(cleaned)) != len(cleaned) or not cleaned:
            raise ValueError("annotator names must be unique and non-empty")
        return cleaned
    if count < 1:
        raise ValueError("--annotators must be >= 1")
    return [f"annotator_{index}" for index in range(1, count + 1)]


def rubric_text(mode: str) -> str:
    error_list = "\n".join(f"  - {name}" for name in ERROR_TYPES)
    mode_text = (
        "TEMPLATE PACKET: each canonical query signature (literal values and variable names "
        "masked) appears with up to two realizations. Judge each row on its own; the analysis "
        "aggregates rows by signature_id."
        if mode == "templates"
        else "INSTANCE PACKET: rows are a seeded stratified sample of accepted benchmark items "
        "(graph x category). Judge each row on its own."
    )
    return f"""PIPE-Cypher benchmark validation rubric
{PRIVATE_NOTICE}

{mode_text}

Work independently. Do not discuss items with other annotators until all sheets are
submitted. Do not reorder, delete, or add rows; fill only the five rubric columns.
Use the per-graph schema files in this folder (when present) to check labels,
relationship types, and relationship directions.

Evidence columns
- question: the benchmark natural-language question.
- cypher: the reference Cypher query paired with the question.
- result_row_count_observed: rows returned when the reference was executed during
  generation. Generation kept at most {PIPELINE_EXECUTION_ROW_LIMIT} rows, so
  {PIPELINE_EXECUTION_ROW_LIMIT} means "at least {PIPELINE_EXECUTION_ROW_LIMIT}"
  (see result_count_note).
- result_rows_preview: the first few returned rows (JSON) as observed in the graph.

Rubric columns (answer yes or no)
- question_unambiguous: yes if a competent analyst would read the question one way
  (entities, filters, time windows, and what to return are clear). no otherwise.
- reference_correct: yes if executing the reference Cypher returns what the question
  asks (right entities, relationship directions, filters, aggregation, ordering/limit,
  and nothing systematically missing or extra). If the question is ambiguous, answer
  for the most natural reading and mark question_unambiguous = no. no otherwise.
- answer_columns_appropriate: yes if the returned columns contain what the question asks
  for (plus reasonable identifying context). Extra helpful context columns are fine;
  a missing requested value is not.

error_type (required when any answer above is no; separate several with ';')
{error_list}

notes: free text; required when error_type is other.

Definitions for error_type
- wrong_direction_semantics: relationship direction or role is reversed relative to the
  question (e.g. sender vs. receiver, owner vs. owned).
- missing_results: the query would omit answers the question asks for (over-restrictive
  filter, wrong hop count, inner match where optional data is allowed, etc.).
- extra_results: the query returns answers the question excludes (missing filter,
  missing DISTINCT where it matters, unbounded path, etc.).
- wrong_aggregation: wrong aggregate, grouping, counting unit, or ordering for ranking.
- wrong_filter: wrong literal, property, comparison, or time window.
- ambiguous_question: the question itself supports several readings.
- other: anything else (explain in notes).
"""


def write_validation_packet(
    packet_rows: list[dict[str, Any]],
    output_dir: str | Path,
    *,
    mode: str,
    annotators: list[str],
    prefix: str = "",
    seed: int = 17,
    schemas: dict[str, SchemaSummary] | None = None,
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write per-annotator sheets, key file, rubric, schema text, and manifest."""

    if mode not in {"templates", "instances"}:
        raise ValueError("mode must be templates or instances")
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = prefix or f"benchmark_validation_{mode}"
    sheets = []
    for annotator in annotators:
        ordered = list(packet_rows)
        random.Random(f"{seed}:{annotator}").shuffle(ordered)
        sheet_rows = []
        for index, row in enumerate(ordered):
            sheet = {field: row.get(field, "") for field in SHEET_FIELDS}
            sheet.update({"review_order": index, "annotator": annotator})
            for field in RUBRIC_FIELDS:
                sheet[field] = ""
            sheet_rows.append(sheet)
        path = out_dir / f"{prefix}_{annotator}.csv"
        write_plain_csv(path, sheet_rows, SHEET_FIELDS)
        sheets.append({"annotator": annotator, "path": str(path), "sha256": sha256_file(path)})

    key_path = out_dir / f"{prefix}_key.csv"
    write_plain_csv(key_path, packet_rows, KEY_FIELDS)
    rubric_path = out_dir / f"{prefix}_rubric.txt"
    rubric_path.write_text(rubric_text(mode), encoding="utf-8")
    schema_files = []
    for graph, schema in sorted((schemas or {}).items()):
        schema_path = out_dir / f"schema_{graph}.txt"
        schema_path.write_text(schema.to_prompt(max_items=10_000) + "\n", encoding="utf-8")
        schema_files.append({"graph_profile": graph, "path": str(schema_path), "sha256": sha256_file(schema_path)})

    strata = Counter(row["stratum"] for row in packet_rows)
    manifest = {
        "privacy": PRIVATE_NOTICE + " Annotator sheets are PRIVATE/internal; the key holds no literal values.",
        "created_at": utc_now(),
        "mode": mode,
        "seed": seed,
        "prefix": prefix,
        "row_count": len(packet_rows),
        "unique_items": len({row["item_id"] for row in packet_rows}),
        "signatures": len({row["signature_id"] for row in packet_rows}),
        "strata": dict(sorted(strata.items())),
        "annotators": annotators,
        "annotator_sheets": sheets,
        "key": {"path": str(key_path), "sha256": sha256_file(key_path)},
        "rubric": {"path": str(rubric_path), "sha256": sha256_file(rubric_path)},
        "schema_files": schema_files,
        "source": source or {},
        "rubric_fields": list(RUBRIC_FIELDS),
        "error_types": list(ERROR_TYPES),
        "instructions": (
            "Send each annotator only their own sheet, the rubric, and the schema files. Collect the "
            "filled sheets unchanged, then run scripts/analyze_benchmark_validation.py with --key."
        ),
    }
    manifest_path = out_dir / f"{prefix}_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    return manifest


# ---------------------------------------------------------------------------
# Analysis of filled sheets
# ---------------------------------------------------------------------------


def normalize_error_types(value: Any) -> list[str]:
    text = str(value or "").strip().lower()
    if not text:
        return []
    parts = [part.strip() for part in re.split(r"[;|,]+", text) if part.strip()]
    out = []
    for part in parts:
        canonical = re.sub(r"[\s-]+", "_", part)
        out.append(canonical if canonical in ERROR_TYPES else f"nonstandard:{canonical}")
    return out


def load_validation_sheet(path: str | Path) -> tuple[str, dict[str, dict[str, str]], list[str]]:
    rows = read_csv_rows(path)
    annotator = next((row.get("annotator", "").strip() for row in rows if row.get("annotator", "").strip()), "")
    annotator = annotator or Path(path).stem
    by_id: dict[str, dict[str, str]] = {}
    duplicates: list[str] = []
    for row in rows:
        item_id = str(row.get("item_id") or "").strip()
        if not item_id:
            continue
        if item_id in by_id:
            duplicates.append(item_id)
            continue
        by_id[item_id] = row
    return annotator, by_id, duplicates


def load_adjudication(path: str | Path | None) -> dict[str, dict[str, str]]:
    if not path:
        return {}
    out: dict[str, dict[str, str]] = {}
    for row in read_csv_rows(path):
        item_id = str(row.get("item_id") or "").strip()
        if item_id:
            out[item_id] = row
    return out


def _consensus(labels: list[bool | None], adjudicated: bool | None) -> tuple[bool | None, str]:
    if adjudicated is not None:
        return adjudicated, "adjudicated"
    observed = [label for label in labels if label is not None]
    if not observed or len(observed) < len(labels):
        return None, "unresolved_missing_labels"
    if len(set(observed)) == 1:
        return observed[0], "unanimous"
    yes = sum(1 for label in observed if label)
    no = len(observed) - yes
    if yes != no and len(observed) >= 3:
        return yes > no, "majority"
    return None, "unresolved_disagreement"


def _no_rate(labels: list[bool]) -> dict[str, Any]:
    return rate_with_ci(sum(1 for label in labels if label is False), len(labels))


def stratified_rate(
    strata: dict[str, tuple[int, list[bool]]],
) -> dict[str, Any] | None:
    """Population-weighted 'no' rate with a normal CI and finite-population correction.

    ``strata[key] = (population_size, labels)``. Strata without labels are excluded
    and their population weight is renormalized.
    """

    usable = {key: (size, labels) for key, (size, labels) in strata.items() if labels and size}
    if not usable:
        return None
    total = sum(size for size, _ in usable.values())
    estimate = 0.0
    variance = 0.0
    for size, labels in usable.values():
        weight = size / total
        n_h = len(labels)
        p_h = sum(1 for label in labels if label is False) / n_h
        estimate += weight * p_h
        if n_h > 1:
            fpc = max(0.0, 1 - n_h / size)
            variance += weight * weight * fpc * p_h * (1 - p_h) / (n_h - 1)
    margin = 1.959963984540054 * math.sqrt(variance)
    return {
        "rate": estimate,
        "ci95": [max(0.0, estimate - margin), min(1.0, estimate + margin)],
        "strata_used": len(usable),
        "population": total,
        "method": "stratified (population-weighted) estimate, normal CI with finite-population correction",
    }


def analyze_validation_sheets(
    sheet_paths: list[str | Path],
    *,
    key_path: str | Path | None = None,
    adjudication_path: str | Path | None = None,
) -> dict[str, Any]:
    if not sheet_paths:
        raise ValueError("at least one annotator sheet is required")
    sheets = []
    for path in sheet_paths:
        annotator, by_id, duplicates = load_validation_sheet(path)
        sheets.append({"annotator": annotator, "path": str(path), "rows": by_id, "duplicates": duplicates})
    names = [sheet["annotator"] for sheet in sheets]
    if len(set(names)) != len(names):
        raise ValueError(f"annotator names must be unique across sheets: {names}")
    key_rows = {row["item_id"]: row for row in read_csv_rows(key_path)} if key_path else {}
    adjudication = load_adjudication(adjudication_path)

    universe = sorted(set(key_rows) | set().union(*(set(sheet["rows"]) for sheet in sheets)))
    meta: dict[str, dict[str, Any]] = {}
    for item_id in universe:
        base: dict[str, Any] = dict(key_rows.get(item_id, {}))
        for sheet in sheets:
            row = sheet["rows"].get(item_id)
            if row:
                for field in ("graph_profile", "category", "difficulty", "signature_id", "packet_mode", "question", "cypher", "result_row_count_observed", "result_rows_preview"):
                    base.setdefault(field, row.get(field, ""))
        meta[item_id] = base
    mode = next((str(row.get("packet_mode")) for row in meta.values() if row.get("packet_mode")), "unknown")

    labels: dict[str, dict[str, dict[str, bool | None]]] = {field: {} for field in YES_NO_FIELDS}
    completeness: dict[str, Any] = {}
    error_type_counts: dict[str, Counter[str]] = {}
    for sheet in sheets:
        name = sheet["annotator"]
        missing = [item_id for item_id in universe if item_id not in sheet["rows"]]
        unlabeled = Counter()
        missing_error_type = 0
        counts: Counter[str] = Counter()
        for item_id in universe:
            row = sheet["rows"].get(item_id) or {}
            any_no = False
            for field in YES_NO_FIELDS:
                value = parse_yes_no(row.get(field, "")) if row else None
                labels[field].setdefault(item_id, {})[name] = value
                if row and value is None:
                    unlabeled[field] += 1
                if value is False:
                    any_no = True
            types = normalize_error_types(row.get("error_type", "")) if row else []
            counts.update(types)
            if any_no and not types:
                missing_error_type += 1
        error_type_counts[name] = counts
        completeness[name] = {
            "path": sheet["path"],
            "sha256": sha256_file(sheet["path"]),
            "rows": len(sheet["rows"]),
            "missing_items": len(missing),
            "duplicate_ids": sheet["duplicates"],
            "unlabeled": dict(unlabeled),
            "missing_error_type_when_no": missing_error_type,
            "complete": not missing and not sum(unlabeled.values()) and not sheet["duplicates"],
        }

    consensus: dict[str, dict[str, tuple[bool | None, str]]] = {field: {} for field in YES_NO_FIELDS}
    for field in YES_NO_FIELDS:
        for item_id in universe:
            adjudicated = parse_yes_no((adjudication.get(item_id) or {}).get(f"adjudicated_{field}", ""))
            consensus[field][item_id] = _consensus([labels[field][item_id].get(n) for n in names], adjudicated)

    def _field_summary(field: str) -> dict[str, Any]:
        final = [value for value, _ in consensus[field].values() if value is not None]
        sources = Counter(source for _, source in consensus[field].values())
        fully = [item_id for item_id in universe if all(labels[field][item_id].get(n) is not None for n in names)]
        any_no = sum(1 for item_id in fully if any(labels[field][item_id][n] is False for n in names))
        all_no = sum(1 for item_id in fully if all(labels[field][item_id][n] is False for n in names))
        per_annotator = {
            n: _no_rate([labels[field][i][n] for i in universe if labels[field][i].get(n) is not None]) for n in names
        }
        return {
            "consensus_no_rate": _no_rate(final),
            "consensus_sources": dict(sources),
            "unresolved": sum(count for source, count in sources.items() if source.startswith("unresolved")),
            "any_annotator_no_rate": rate_with_ci(any_no, len(fully)),
            "all_annotators_no_rate": rate_with_ci(all_no, len(fully)),
            "per_annotator_no_rate": per_annotator,
        }

    fields_summary = {field: _field_summary(field) for field in YES_NO_FIELDS}

    agreement: dict[str, Any] = {}
    for field in YES_NO_FIELDS:
        pairs = []
        for a, b in combinations(names, 2):
            ids = [i for i in universe if labels[field][i].get(a) is not None and labels[field][i].get(b) is not None]
            la = [labels[field][i][a] for i in ids]
            lb = [labels[field][i][b] for i in ids]
            pairs.append(
                {
                    "annotator_a": a,
                    "annotator_b": b,
                    "n": len(ids),
                    "agreement": (sum(1 for x, y in zip(la, lb) if x == y) / len(ids)) if ids else None,
                    "cohen_kappa": cohen_kappa(la, lb) if ids else None,
                    "gwet_ac1": gwet_ac1(la, lb) if ids else None,
                }
            )
        entry: dict[str, Any] = {"pairwise": pairs}
        if len(names) > 2:
            ids = [i for i in universe if all(labels[field][i].get(n) is not None for n in names)]
            entry["fleiss"] = {
                "n": len(ids),
                "kappa": fleiss_kappa_from_ratings([[labels[field][i][n] for n in names] for i in ids]),
            }
        agreement[field] = entry
    error_type_pairs = []
    for a, b in combinations(names, 2):
        ids = []
        la, lb = [], []
        for item_id in universe:
            ta = normalize_error_types((sheets[names.index(a)]["rows"].get(item_id) or {}).get("error_type", ""))
            tb = normalize_error_types((sheets[names.index(b)]["rows"].get(item_id) or {}).get("error_type", ""))
            if ta and tb:
                ids.append(item_id)
                la.append(ta[0])
                lb.append(tb[0])
        error_type_pairs.append(
            {"annotator_a": a, "annotator_b": b, "n_both_typed": len(ids), "cohen_kappa_first_type": cohen_kappa(la, lb) if ids else None}
        )
    agreement["error_type"] = {"pairwise": error_type_pairs}

    def _slice(key_fn) -> dict[str, Any]:
        groups: dict[str, list[str]] = defaultdict(list)
        for item_id in universe:
            groups[key_fn(meta[item_id])].append(item_id)
        out = {}
        for key in sorted(groups):
            ids = groups[key]
            final = [consensus["reference_correct"][i][0] for i in ids if consensus["reference_correct"][i][0] is not None]
            fully = [i for i in ids if all(labels["reference_correct"][i].get(n) is not None for n in names)]
            any_no = sum(1 for i in fully if any(labels["reference_correct"][i][n] is False for n in names))
            out[key] = {
                "items": len(ids),
                "reference_error_consensus": _no_rate(final),
                "reference_error_any_annotator": rate_with_ci(any_no, len(fully)),
            }
        return out

    slices = {
        "by_graph": _slice(lambda row: str(row.get("graph_profile") or "unknown")),
        "by_category": _slice(lambda row: str(row.get("category") or "unknown")),
        "by_graph_category": _slice(lambda row: f"{row.get('graph_profile')}::{row.get('category')}"),
        "by_difficulty": _slice(lambda row: str(row.get("difficulty") or "unknown")),
    }
    if any(row.get("split") for row in meta.values()):
        slices["by_split"] = _slice(lambda row: str(row.get("split") or "unknown"))

    estimates: dict[str, Any] = {}
    ref_final = consensus["reference_correct"]
    if mode == "instances":
        strata: dict[str, tuple[int, list[bool]]] = {}
        for item_id in universe:
            row = meta[item_id]
            stratum = str(row.get("stratum") or f"{row.get('graph_profile')}::{row.get('category')}")
            population = int(row.get("stratum_population") or 0)
            size, values = strata.get(stratum, (population, []))
            if ref_final[item_id][0] is not None:
                values.append(ref_final[item_id][0])
            strata[stratum] = (max(size, population), values)
        estimates["stratified_reference_error"] = stratified_rate(strata)
    if mode == "templates":
        by_signature: dict[str, list[str]] = defaultdict(list)
        for item_id in universe:
            by_signature[str(meta[item_id].get("signature_id") or item_id)].append(item_id)
        labeled_signatures = 0
        incorrect_signatures = 0
        weighted_num = 0.0
        weighted_den = 0.0
        for sig, ids in by_signature.items():
            final = [ref_final[i][0] for i in ids if ref_final[i][0] is not None]
            if not final:
                continue
            labeled_signatures += 1
            share_no = sum(1 for value in final if value is False) / len(final)
            if share_no > 0:
                incorrect_signatures += 1
            size = max(int(meta[i].get("signature_group_size") or 1) for i in ids)
            weighted_num += size * share_no
            weighted_den += size
        estimates["signatures"] = {
            "signatures_total": len(by_signature),
            "signatures_labeled": labeled_signatures,
            "signatures_with_incorrect_realization": rate_with_ci(incorrect_signatures, labeled_signatures),
            "frequency_weighted_reference_error": (weighted_num / weighted_den) if weighted_den else None,
            "frequency_weighted_note": (
                "Each signature's share of incorrect realizations weighted by how many benchmark items "
                "share that signature (signature_group_size); valid only for the template packet."
            ),
        }

    consensus_incorrect = [i for i in universe if ref_final[i][0] is False]
    types_on_incorrect: Counter[str] = Counter()
    for item_id in consensus_incorrect:
        seen: set[str] = set()
        for sheet in sheets:
            seen.update(normalize_error_types((sheet["rows"].get(item_id) or {}).get("error_type", "")))
        types_on_incorrect.update(seen)

    all_complete = all(entry["complete"] for entry in completeness.values())
    unresolved = fields_summary["reference_correct"]["unresolved"]
    return {
        "privacy": "Aggregate metrics only; disagreement/adjudication CSVs are PRIVATE/internal.",
        "generated_at": utc_now(),
        "mode": mode,
        "annotators": names,
        "items": len(universe),
        "key_items": len(key_rows),
        "adjudicated_items": len(adjudication),
        "completeness": completeness,
        "fields": fields_summary,
        "headline": {
            "reference_error_rate": fields_summary["reference_correct"]["consensus_no_rate"],
            "reference_error_bounds": {
                "lower_all_annotators_no": fields_summary["reference_correct"]["all_annotators_no_rate"],
                "upper_any_annotator_no": fields_summary["reference_correct"]["any_annotator_no_rate"],
            },
            "unresolved_reference_items": unresolved,
            "ready_for_paper": all_complete and unresolved == 0,
        },
        "estimates": estimates,
        "agreement": agreement,
        "slices": slices,
        "error_types": {
            "per_annotator": {name: dict(counts) for name, counts in error_type_counts.items()},
            "on_consensus_incorrect_items": dict(types_on_incorrect),
            "suggested": list(ERROR_TYPES),
        },
        "notes": [
            "Consensus: adjudicated label if present, else unanimous label, else strict majority (>=3 "
            "annotators); otherwise unresolved and excluded from the consensus rate. Report the any/all "
            "annotator bounds until disagreements are adjudicated.",
            "Wilson 95% intervals; the instance packet uses proportional allocation, so the pooled rate is "
            "self-weighting and the stratified estimate is reported as a check.",
        ],
    }


def validation_disagreement_rows(
    sheet_paths: list[str | Path],
    *,
    key_path: str | Path | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Items where annotators differ (or someone is missing a label) on any yes/no field."""

    loaded = [load_validation_sheet(path) for path in sheet_paths]
    names = [name for name, _, _ in loaded]
    key_rows = {row["item_id"]: row for row in read_csv_rows(key_path)} if key_path else {}
    universe = sorted(set(key_rows) | set().union(*(set(rows) for _, rows, _ in loaded)))
    out_rows = []
    for item_id in universe:
        per = {name: rows.get(item_id) or {} for name, rows, _ in loaded}
        differing = []
        for field in YES_NO_FIELDS:
            values = [parse_yes_no(per[name].get(field, "")) for name in names]
            if len(set(values)) > 1:
                differing.append(field)
        if not differing:
            continue
        base = next((row for row in per.values() if row), {})
        row: dict[str, Any] = {
            "item_id": item_id,
            "graph_profile": base.get("graph_profile", key_rows.get(item_id, {}).get("graph_profile", "")),
            "category": base.get("category", key_rows.get(item_id, {}).get("category", "")),
            "difficulty": base.get("difficulty", ""),
            "signature_id": base.get("signature_id", ""),
            "disagreement_fields": ";".join(differing),
            "question": base.get("question", ""),
            "cypher": base.get("cypher", ""),
            "result_row_count_observed": base.get("result_row_count_observed", ""),
            "result_rows_preview": base.get("result_rows_preview", ""),
        }
        for name in names:
            for field in (*YES_NO_FIELDS, "error_type", "notes"):
                row[f"{name}__{field}"] = per[name].get(field, "") if per[name] else "missing"
        for field in ADJUDICATION_FIELDS:
            row[field] = ""
        out_rows.append(row)
    fieldnames = ["item_id", "graph_profile", "category", "difficulty", "signature_id", "disagreement_fields"]
    for name in names:
        fieldnames.extend(f"{name}__{field}" for field in (*YES_NO_FIELDS, "error_type", "notes"))
    fieldnames.extend(["question", "cypher", "result_row_count_observed", "result_rows_preview", *ADJUDICATION_FIELDS])
    return out_rows, fieldnames


def write_validation_disagreements(path: str | Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    write_private_csv(path, rows, fieldnames)


def _pct(entry: dict[str, Any] | None) -> str:
    if not entry or entry.get("rate") is None:
        return "--"
    low, high = entry["ci95"]
    return f"{100 * entry['rate']:.1f}% [{100 * low:.1f}, {100 * high:.1f}]"


def _num(value: Any) -> str:
    return "--" if value is None else (f"{value:.3f}" if isinstance(value, float) else str(value))


def render_validation_markdown(report: dict[str, Any]) -> str:
    head = report["headline"]
    lines = [
        f"# Benchmark Validation ({report['mode']} packet)",
        "",
        f"Generated: {report['generated_at']}",
        f"Annotators: {', '.join(report['annotators'])}; items: {report['items']}; "
        f"adjudicated: {report['adjudicated_items']}; ready for paper: {head['ready_for_paper']}",
        "",
        "## Headline",
        "",
        f"- Reference error rate (consensus): {_pct(head['reference_error_rate'])} "
        f"(n={head['reference_error_rate']['n']}, unresolved={head['unresolved_reference_items']})",
        f"- Bounds: all annotators no {_pct(head['reference_error_bounds']['lower_all_annotators_no'])}; "
        f"any annotator no {_pct(head['reference_error_bounds']['upper_any_annotator_no'])}",
    ]
    strat = report["estimates"].get("stratified_reference_error")
    if strat:
        lines.append(
            f"- Stratified (population-weighted) reference error: {100 * strat['rate']:.1f}% "
            f"[{100 * strat['ci95'][0]:.1f}, {100 * strat['ci95'][1]:.1f}]"
        )
    sig = report["estimates"].get("signatures")
    if sig:
        weighted = sig["frequency_weighted_reference_error"]
        lines.append(
            f"- Signatures with >=1 incorrect realization: {_pct(sig['signatures_with_incorrect_realization'])} "
            f"of {sig['signatures_labeled']} labeled; frequency-weighted item error: "
            f"{'--' if weighted is None else f'{100 * weighted:.1f}%'}"
        )
    lines += ["", "## Rubric fields (rate of 'no')", "", "| Field | Consensus [95% CI] | Any annotator | All annotators | Unresolved |", "| --- | --- | --- | --- | ---: |"]
    for field, entry in report["fields"].items():
        lines.append(
            f"| {field} | {_pct(entry['consensus_no_rate'])} | {_pct(entry['any_annotator_no_rate'])} | "
            f"{_pct(entry['all_annotators_no_rate'])} | {entry['unresolved']} |"
        )
    lines += ["", "## Inter-annotator agreement", "", "| Field | Pair | n | Agree | Cohen kappa | Gwet AC1 |", "| --- | --- | ---: | ---: | ---: | ---: |"]
    for field in YES_NO_FIELDS:
        for pair in report["agreement"][field]["pairwise"]:
            lines.append(
                f"| {field} | {pair['annotator_a']} vs {pair['annotator_b']} | {pair['n']} | {_num(pair['agreement'])} | "
                f"{_num(pair['cohen_kappa'])} | {_num(pair['gwet_ac1'])} |"
            )
        if "fleiss" in report["agreement"][field]:
            fleiss = report["agreement"][field]["fleiss"]
            lines.append(f"| {field} | Fleiss (all) | {fleiss['n']} | -- | {_num(fleiss['kappa'])} | -- |")
    for slice_name in ("by_graph", "by_category", "by_graph_category"):
        lines += ["", f"## Reference error {slice_name.replace('_', ' ')}", "", "| Slice | Items | Consensus [95% CI] | Any annotator |", "| --- | ---: | --- | --- |"]
        for key, entry in report["slices"][slice_name].items():
            lines.append(
                f"| {key} | {entry['items']} | {_pct(entry['reference_error_consensus'])} | "
                f"{_pct(entry['reference_error_any_annotator'])} |"
            )
    lines += ["", "## Error types on consensus-incorrect items", ""]
    for name, count in sorted(report["error_types"]["on_consensus_incorrect_items"].items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"- {name}: {count}")
    lines += ["", "## Completeness", ""]
    for name, entry in report["completeness"].items():
        lines.append(
            f"- {name}: rows={entry['rows']}, missing={entry['missing_items']}, unlabeled={json.dumps(entry['unlabeled'])}, "
            f"duplicates={len(entry['duplicate_ids'])}, missing error_type when no={entry['missing_error_type_when_no']}"
        )
    lines += ["", "## Notes", ""] + [f"- {note}" for note in report["notes"]] + [""]
    return "\n".join(lines)


def render_validation_latex(report: dict[str, Any], *, label: str = "") -> str:
    label = label or f"tab:benchmark_validation_{report['mode']}"
    head = report["headline"]
    ref_pairs = report["agreement"]["reference_correct"]["pairwise"]
    kappas = [pair["cohen_kappa"] for pair in ref_pairs if pair["cohen_kappa"] is not None]
    kappa_text = _num(sum(kappas) / len(kappas)) if kappas else "--"
    if "fleiss" in report["agreement"]["reference_correct"]:
        kappa_text = _num(report["agreement"]["reference_correct"]["fleiss"]["kappa"]) + " (Fleiss)"

    def _cell(entry: dict[str, Any] | None) -> str:
        if not entry or entry.get("rate") is None:
            return "--"
        return f"{100 * entry['rate']:.1f} [{100 * entry['ci95'][0]:.1f}, {100 * entry['ci95'][1]:.1f}]"

    lines = [
        r"\begin{table}[t]",
        r"\centering",
        r"\small",
        r"\setlength{\tabcolsep}{4pt}",
        r"\begin{tabular}{lrrr}",
        r"\toprule",
        r"Slice & Items & Ref.\ error \% [95\% CI] & Ambiguous Q \% \\",
        r"\midrule",
        (
            f"All & {head['reference_error_rate']['n']} & {_cell(head['reference_error_rate'])} & "
            f"{_cell(report['fields']['question_unambiguous']['consensus_no_rate'])} \\\\"
        ),
    ]
    for key, entry in report["slices"]["by_graph"].items():
        lines.append(
            f"{tex_escape(key)} & {entry['reference_error_consensus']['n']} & {_cell(entry['reference_error_consensus'])} & -- \\\\"
        )
    lines += [
        r"\midrule",
        (
            rf"\multicolumn{{4}}{{l}}{{Annotators: {len(report['annotators'])}; reference\_correct $\kappa$: {kappa_text}; "
            rf"unresolved: {head['unresolved_reference_items']}}} \\"
        ),
        r"\bottomrule",
        r"\end{tabular}",
        (
            rf"\caption{{Human validation of benchmark references ({tex_escape(report['mode'])} packet). "
            r"Reference error is the share of items whose reference Cypher does not return what the "
            r"question asks (consensus after adjudication); Wilson 95\% intervals.}"
        ),
        rf"\label{{{label}}}",
        r"\end{table}",
        "",
    ]
    return "\n".join(lines)
