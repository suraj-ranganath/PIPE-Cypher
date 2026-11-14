"""Convert public Text2Cypher datasets into PIPE-Cypher benchmark packages.

This module supports two revision experiments:

* E3.4 sanity anchor: score the same local downstream models on curated public
  Text2Cypher-2024 test rows whose databases can be loaded locally, using the
  unchanged PIPE-Cypher prediction and evaluation scripts.
* E3.5 ranking agreement: compare model rankings on a PIPE-generated benchmark
  and on the curated rows for the same public example graph.

The converter is deterministic and offline once the source file is local. It
keeps the upstream question/Cypher text byte-for-byte, drops rows that fail
PIPE-Cypher's read-only gate (logging every drop), and writes the same
``train/dev/test/all.jsonl`` layout that ``scripts/export_benchmark.py`` emits,
so ``scripts/generate_text2cypher_predictions.py`` and
``scripts/evaluate_benchmark_predictions.py`` work without changes.

Nothing here downloads data or opens a Neo4j connection; callers pass rows and
clients in. ``scripts/fetch_text2cypher2024.py`` owns the network and CLI side.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .cypher_parser import OptionalCypherParser
from .io import read_jsonl, write_jsonl
from .models import NodeProperty, RelationshipPattern, RelationshipProperty, SchemaSummary
from .validator import (
    WRITE_TOKENS,
    clean_cypher,
    is_read_only,
    structural_features,
    validate_cypher,
)

CONVERTER_VERSION = "external_benchmarks_v1"
CATEGORY_METHOD = "structural_heuristic_v1"

# ---------------------------------------------------------------------------
# Source dataset facts (verified 2026-11-11 against the Hugging Face API).
# ---------------------------------------------------------------------------

T2C2024_DATASET = "neo4j/text2cypher-2024v1"
T2C2024_CITATION_KEY = "text2cypher2024dataset"
# Hub commit of the dataset repository at inspection time (lastModified 2025-08-06).
T2C2024_REVISION = "d9f15541ab2f99a0f54797a0109b50663554f512"
T2C2024_FILES = {
    "train": "data/train-00000-of-00001.parquet",
    "test": "data/test-00000-of-00001.parquet",
}
# sha256 of the parquet files at T2C2024_REVISION. Used to fail loudly when the
# downloaded bytes differ from the inspected release.
T2C2024_SHA256 = {
    "train": "12218000576ed793e468417333b4499517c3d7869c94504941c6741acc229bce",
    "test": "948ae94e4a4345b0fdc7b27f77383a2b68471552d15d7fc8473a4448d8eb502f",
}
T2C2024_SPLIT_SIZES = {"train": 39554, "test": 4833}
T2C2024_FIELDS = (
    "question",
    "schema",
    "cypher",
    "data_source",
    "instance_id",
    "database_reference_alias",
)
DATABASE_ALIAS_PREFIX = "neo4jlabs_demo_db_"
# The dataset card documents this alias typo ("eoflix" should be "neoflix").
DATABASE_ALIAS_TYPOS = {"eoflix": "neoflix"}
GRAPH_PROFILE_PREFIX = "t2c_"
UPSTREAM_SPLITS = ("train", "test")
PACKAGE_SPLITS = ("train", "dev", "test")


def hf_resolve_url(
    path: str,
    *,
    dataset: str = T2C2024_DATASET,
    revision: str = T2C2024_REVISION,
) -> str:
    """Return the Hub ``resolve`` URL for a dataset file pinned to ``revision``."""

    return f"https://huggingface.co/datasets/{dataset}/resolve/{revision}/{path}"


# ---------------------------------------------------------------------------
# Public Neo4j example graphs (github.com/neo4j-graph-examples).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExampleGraphSpec:
    """A public Neo4j example graph that backs Text2Cypher-2024 rows."""

    name: str
    database_alias: str
    repo: str
    commit: str
    dump_path: str
    dump_bytes: int
    dump_sha256: str
    store_format: str
    status: str
    bolt_port: int
    http_port: int
    test_rows: int
    notes: str = ""

    @property
    def graph_profile(self) -> str:
        return GRAPH_PROFILE_PREFIX + self.name

    @property
    def dump_url(self) -> str:
        return f"https://raw.githubusercontent.com/{self.repo}/{self.commit}/{self.dump_path}"

    @property
    def dump_filename(self) -> str:
        return Path(self.dump_path).name


# Facts below were checked on 2026-11-11: HTTP 200 on the commit-pinned raw URL,
# byte size, sha256 of the downloaded file, the Neo4j 5 dump header ("DZV1" +
# zstd), and the record store format read from the dump's ``neostore`` entry.
# ``test_rows`` counts Text2Cypher-2024 test rows with that database alias.
EXAMPLE_GRAPHS: dict[str, ExampleGraphSpec] = {
    spec.name: spec
    for spec in (
        ExampleGraphSpec(
            name="recommendations",
            database_alias="neo4jlabs_demo_db_recommendations",
            repo="neo4j-graph-examples/recommendations",
            commit="f5a3f87b9fa73461750eef564ce8b81f304d940b",
            dump_path="data/recommendations-50.dump",
            dump_bytes=9552166,
            dump_sha256="c22134f5ef8e8239856003134bf746d77b705bc538e40bd7c1fa034673453734",
            store_format="record-standard",
            status="recommended",
            bolt_port=7701,
            http_port=7501,
            test_rows=253,
            notes=(
                "Labels/rel types/property keys in the dump cover every token used by the "
                "253 test queries. A 5.26.8-built aligned dump also exists "
                "(data/recommendations-5.26.dump); the -50 dump is used so Neo4j 5.26.0 "
                "never loads a store written by a newer patch release."
            ),
        ),
        ExampleGraphSpec(
            name="northwind",
            database_alias="neo4jlabs_demo_db_northwind",
            repo="neo4j-graph-examples/northwind",
            commit="56ee0507d33eecd8ef2a9c960ec967cd432eb57e",
            dump_path="data/northwind-50.dump",
            dump_bytes=160712,
            dump_sha256="3aef3fdf2f9e6a7e6e813d7fcd4e46a8ea7e75573ee7d4fb84f6884ec1f66b9f",
            store_format="record-standard",
            status="recommended",
            bolt_port=7702,
            http_port=7502,
            test_rows=197,
            notes=(
                "Dump tokens match the dataset schema exactly (5 labels, 4 rel types). "
                "data/northwind-2026-05.dump targets Neo4j 2026.05 and is not used."
            ),
        ),
        ExampleGraphSpec(
            name="fincen",
            database_alias="neo4jlabs_demo_db_fincen",
            repo="neo4j-graph-examples/fincen",
            commit="41c8ef891e0f7624294cbf6ff8c4b57eda8d9c15",
            dump_path="data/fincen-50.dump",
            dump_bytes=1407783,
            dump_sha256="e0e8f0a5616ef50fa9407a1ee02138f027df6e4a1c2c6d3585e25e88119016b8",
            store_format="record-standard",
            status="recommended",
            bolt_port=7703,
            http_port=7503,
            test_rows=146,
            notes=(
                "Financial-compliance graph (FinCEN Files). Labels and rel types match; "
                "a few test queries reference originator_country/originator_lat/"
                "originator_lng, which are not property keys in the dump."
            ),
        ),
        ExampleGraphSpec(
            name="network",
            database_alias="neo4jlabs_demo_db_network",
            repo="neo4j-graph-examples/network-management",
            commit="15d4a47c0f579d8f2c73ecd76d4e3d9c74f7ecea",
            dump_path="data/network-management-50.dump",
            dump_bytes=3199713,
            dump_sha256="0c54b653a56396191f37a2e0750a52abef649ad542ca6d73802496e46d30ed60",
            store_format="record-aligned",
            status="alternate",
            bolt_port=7704,
            http_port=7504,
            test_rows=109,
            notes="IT/network-management graph; all test-query tokens present in the dump.",
        ),
        ExampleGraphSpec(
            name="movies",
            database_alias="neo4jlabs_demo_db_movies",
            repo="neo4j-graph-examples/movies",
            commit="51cf90d18c1a7f74bce7a77083543697dfb0139d",
            dump_path="data/movies-50.dump",
            dump_bytes=21275,
            dump_sha256="806ea150f5ce7387173e4ba54a8e0054f282e2f2021d4245117807744933a886",
            store_format="record-aligned",
            status="alternate",
            bolt_port=7705,
            http_port=7505,
            test_rows=203,
            notes=(
                "Toy graph (2 labels). 27 of 203 test queries use a `votes` property "
                "that the dump does not contain, and the graph is too small for a "
                "balanced target-per-category PIPE benchmark."
            ),
        ),
    )
}
RECOMMENDED_GRAPHS = tuple(
    name for name, spec in EXAMPLE_GRAPHS.items() if spec.status == "recommended"
)


def canonical_database_name(alias: str | None) -> str | None:
    """Map ``neo4jlabs_demo_db_<name>`` to ``<name>`` (fixing the documented typo)."""

    if alias is None:
        return None
    text = str(alias).strip()
    if not text or text.lower() in {"none", "null", "nan"}:
        return None
    short = text.removeprefix(DATABASE_ALIAS_PREFIX)
    short = short.removeprefix(GRAPH_PROFILE_PREFIX)
    return DATABASE_ALIAS_TYPOS.get(short, short)


def graph_profile_for_alias(alias: str | None) -> str | None:
    name = canonical_database_name(alias)
    return GRAPH_PROFILE_PREFIX + name if name else None


def resolve_database_filter(names: Iterable[str] | None) -> set[str] | None:
    """Return canonical database names to keep, or ``None`` to keep every alias.

    Accepts short names (``northwind``), dataset aliases
    (``neo4jlabs_demo_db_northwind``), graph profiles (``t2c_northwind``),
    ``recommended`` (the three recommended graphs), and ``all``.
    """

    if names is None:
        return set(RECOMMENDED_GRAPHS)
    selected: set[str] = set()
    for raw in names:
        for token in str(raw).split(","):
            token = token.strip()
            if not token:
                continue
            if token == "all":
                return None
            if token == "recommended":
                selected.update(RECOMMENDED_GRAPHS)
                continue
            canonical = canonical_database_name(token)
            if canonical:
                selected.add(canonical)
    return selected


# ---------------------------------------------------------------------------
# Loading rows.
# ---------------------------------------------------------------------------


def load_t2c_rows(path: str | Path) -> list[dict[str, Any]]:
    """Load Text2Cypher rows from a parquet, JSONL, or JSON-list file."""

    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".parquet":
        try:
            import pyarrow.parquet as pq  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise RuntimeError(
                "Reading parquet requires pyarrow (pip install pyarrow), or pass a JSONL export"
            ) from exc
        return [dict(row) for row in pq.read_table(source).to_pylist()]
    if suffix == ".jsonl":
        return read_jsonl(source)
    if suffix == ".json":
        data = json.loads(source.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("rows"), list):
            data = [item.get("row", item) for item in data["rows"]]
        if not isinstance(data, list):
            raise ValueError(f"{source}: expected a JSON list of rows")
        return [dict(row) for row in data]
    raise ValueError(f"{source}: unsupported input format (use .parquet, .jsonl, or .json)")


def find_split_file(directory: str | Path, split: str) -> Path:
    """Locate the file for ``split`` inside a local mirror of the dataset."""

    base = Path(directory)
    patterns = (
        f"{split}-*.parquet",
        f"data/{split}-*.parquet",
        f"{split}.parquet",
        f"{split}.jsonl",
        f"data/{split}.jsonl",
    )
    for pattern in patterns:
        matches = sorted(base.glob(pattern))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(f"{base}: multiple files match {pattern}: {matches}")
    raise FileNotFoundError(f"{base}: no file found for split '{split}'")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Row conversion.
# ---------------------------------------------------------------------------


def t2c_example_id(row: Mapping[str, Any], *, dataset: str = T2C2024_DATASET) -> str:
    """Stable content-addressed id: same upstream row text -> same id."""

    payload = {
        "dataset": dataset,
        "instance_id": str(row.get("instance_id", "")),
        "database_reference_alias": str(row.get("database_reference_alias") or ""),
        "question": str(row.get("question", "")),
        "cypher": str(row.get("cypher", "")),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return f"t2c_{digest[:16]}"


_STRING_LITERAL = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")
_VAR_LENGTH_REL = re.compile(r"\[[^\]]*\*[^\]]*\]")
_AGGREGATE = re.compile(r"\b(count|sum|avg|min|max|collect|stdev|stdevp|percentilecont|percentiledisc)\s*\(", re.IGNORECASE)
# An aggregate inside a WITH clause (before the next MATCH/RETURN/WITH) marks a
# multi-stage aggregation.
_STAGED_AGGREGATE = re.compile(
    r"\bWITH\b(?:(?!\b(?:RETURN|MATCH|WITH)\b).)*?"
    r"\b(?:count|sum|avg|min|max|collect|stdev|stdevp|percentilecont|percentiledisc)\s*\(",
    re.IGNORECASE | re.DOTALL,
)
_BOOLEAN_PROJECTION = re.compile(
    r"\bEXISTS\b|\bCOUNT\s*\([^()]*\)\s*(>|>=|<>|=)\s*\d|\bIS\s+(NOT\s+)?NULL\b|\bTRUE\b|\bFALSE\b",
    re.IGNORECASE,
)


def _strip_string_literals(query: str) -> str:
    return _STRING_LITERAL.sub("''", query)


def _final_return_projection(query: str) -> str:
    matches = list(re.finditer(r"\bRETURN\b", query, re.IGNORECASE))
    if not matches:
        return ""
    tail = query[matches[-1].end():]
    return re.split(r"\b(ORDER\s+BY|SKIP|LIMIT|UNION)\b", tail, maxsplit=1, flags=re.IGNORECASE)[0]


def derive_coarse_category(cypher: str) -> tuple[str, dict[str, Any]]:
    """Map a reference query to the closest PIPE-Cypher category.

    This is a structural heuristic over the query text (string literals are
    masked first), not a gold label: upstream rows have no category. Priority
    follows the PIPE-Cypher taxonomy, from the most specific operator to plain
    retrieval: boolean existence, negation, variable-length path, ranking,
    aggregation, retrieval. Returns the category and the structural features
    computed by ``pipecypher.validator.structural_features``.
    """

    features = structural_features(cypher)
    masked = _strip_string_literals(cypher)
    upper = masked.upper()
    projection = _final_return_projection(masked)
    rel_count = int(features.get("relationship_pattern_count", 0) or 0)
    match_count = len(re.findall(r"\bMATCH\b", upper))
    aggregates = list(_AGGREGATE.finditer(masked))
    projection_items = [item for item in features.get("return_items", []) if item]
    grouped = bool(aggregates) and any(not _AGGREGATE.search(item) for item in projection_items)
    staged_aggregation = bool(_STAGED_AGGREGATE.search(masked))
    negation_text = re.sub(r"\bIS\s+NOT\s+NULL\b", " ", upper)

    if projection and _BOOLEAN_PROJECTION.search(projection):
        category = "boolean_existence"
    elif re.search(r"\bNOT\b", negation_text) or re.search(r"\bNONE\s*\(", upper):
        category = "negation_difference"
    elif _VAR_LENGTH_REL.search(masked) or re.search(r"\b(ALLSHORTESTPATHS|SHORTESTPATH)\s*\(", upper):
        category = "path_temporal"
    elif features.get("ordering") and features.get("limit"):
        category = "ranking_topk"
    elif aggregates:
        complex_agg = grouped or staged_aggregation or rel_count >= 2 or len(aggregates) >= 2
        category = "complex_aggregation" if complex_agg else "simple_aggregation"
    elif rel_count >= 2 or match_count >= 2 or "OPTIONAL MATCH" in upper:
        category = "complex_retrieval"
    else:
        category = "simple_retrieval"
    return category, features


def _compact_features(features: Mapping[str, Any]) -> dict[str, Any]:
    keep = (
        "node_pattern_count",
        "relationship_pattern_count",
        "optional_match",
        "aggregation",
        "ordering",
        "limit",
        "skip",
        "negation",
        "path_pattern",
        "return_arity",
        "labels",
        "relationship_types",
        "return_items",
        "risky_features",
        "difficulty",
        "strategy_tags",
        "primary_strategy",
    )
    return {key: features.get(key) for key in keep if key in features}


def _read_only_detail(cypher: str) -> dict[str, Any]:
    """Explain a read-only rejection without overriding it."""

    upper = cypher.upper()
    tokens = [
        token
        for token in WRITE_TOKENS
        if re.search(rf"(?<![A-Z0-9_]){re.escape(token)}(?![A-Z0-9_])", upper)
    ]
    masked_read_only = is_read_only(_strip_string_literals(cypher))
    return {
        "blocked_tokens": tokens,
        # True when every blocked token sits inside a string literal or is a
        # property/alias name. The row is still dropped: the gate is not weakened.
        "suspected_false_positive": masked_read_only,
    }


def reference_flags(cypher: str) -> dict[str, bool]:
    """Flags that make a reference's answer set unstable or ambiguous to score.

    ``unordered_limit``: LIMIT with no ORDER BY anywhere, so which rows come back
    depends on storage order; a correct prediction can legitimately differ.
    ``ordered_limit``: ORDER BY + LIMIT; stable unless the order key has ties at
    the cut (not detectable statically).
    """

    masked = _strip_string_literals(cypher).upper()
    has_limit = bool(re.search(r"\bLIMIT\b", masked))
    has_order = bool(re.search(r"\bORDER\s+BY\b", masked))
    return {
        "unordered_limit": has_limit and not has_order,
        "ordered_limit": has_limit and has_order,
    }


def annotate_upstream_train_overlap(
    test_examples: Sequence[dict[str, Any]],
    train_examples: Sequence[Mapping[str, Any]],
) -> int:
    """Set ``reference_flags.question_in_upstream_train`` on each test row.

    Upstream train and test share many question strings (paired with different
    Cypher). Checkpoints fine-tuned on Text2Cypher-2024 train have seen those
    questions, so they need a separate unseen-question slice. Returns the count
    of flagged rows.
    """

    def key(item: Mapping[str, Any]) -> tuple[str, str]:
        return str(item.get("graph_profile")), " ".join(str(item.get("question", "")).lower().split())

    seen = {key(item) for item in train_examples}
    flagged = 0
    for example in test_examples:
        hit = key(example) in seen
        example.setdefault("reference_flags", {})["question_in_upstream_train"] = hit
        flagged += int(hit)
    return flagged


def standard_test_slices(test_examples: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Robustness slices of the test split, written to ``slices/<name>.jsonl``.

    Pass a slice file directly as ``--benchmark`` to the prediction/evaluation
    scripts (a file path bypasses ``--split``).
    """

    def flag(item: Mapping[str, Any], name: str) -> bool | None:
        return (item.get("reference_flags") or {}).get(name)

    slices: dict[str, list[dict[str, Any]]] = {
        "test_no_unordered_limit": [dict(row) for row in test_examples if not flag(row, "unordered_limit")],
    }
    # Per-graph test files for per-graph runs and rank agreement (E3.5).
    for profile in sorted({str(row.get("graph_profile")) for row in test_examples}):
        slices[f"test_{profile}"] = [dict(row) for row in test_examples if row.get("graph_profile") == profile]
    if any(flag(row, "question_in_upstream_train") is not None for row in test_examples):
        slices["test_unseen_question"] = [
            dict(row) for row in test_examples if flag(row, "question_in_upstream_train") is False
        ]
        slices["test_unseen_question_no_unordered_limit"] = [
            dict(row)
            for row in test_examples
            if flag(row, "question_in_upstream_train") is False and not flag(row, "unordered_limit")
        ]
    return slices


@dataclass
class ConversionResult:
    examples: list[dict[str, Any]] = field(default_factory=list)
    dropped: list[dict[str, Any]] = field(default_factory=list)
    counts: dict[str, Any] = field(default_factory=dict)


def convert_t2c_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    split: str,
    databases: set[str] | None = None,
    dataset: str = T2C2024_DATASET,
    revision: str = T2C2024_REVISION,
    category_mode: str = "external",
) -> ConversionResult:
    """Convert upstream rows for one split into PIPE-Cypher benchmark rows.

    ``databases`` holds canonical names (see ``resolve_database_filter``);
    ``None`` keeps every row that names a database. Rows without a database
    alias are always dropped because they cannot be executed locally.
    ``category_mode`` is ``external`` (category="external", the default) or
    ``derived`` (category=derived_category, for per-category slicing and
    category-matched few-shot selection).
    """

    if category_mode not in {"external", "derived"}:
        raise ValueError("category_mode must be 'external' or 'derived'")
    result = ConversionResult()
    reasons: Counter[str] = Counter()
    by_db_input: Counter[str] = Counter()
    by_db_kept: Counter[str] = Counter()
    by_db_not_read_only: Counter[str] = Counter()
    seen_content: set[tuple[str, str, str]] = set()
    question_cyphers: dict[tuple[str, str], set[str]] = defaultdict(set)
    parser = OptionalCypherParser()

    for row in rows:
        alias = row.get("database_reference_alias")
        name = canonical_database_name(alias)
        base_drop = {
            "id": t2c_example_id(row, dataset=dataset),
            "split": split,
            "original_id": row.get("instance_id"),
            "database_reference_alias": alias,
            "data_source": row.get("data_source"),
        }
        if name is None:
            reasons["no_database_alias"] += 1
            continue  # not logged per row: ~half the dataset, never executable locally
        by_db_input[name] += 1
        if databases is not None and name not in databases:
            reasons["database_not_selected"] += 1
            continue
        question = str(row.get("question") or "")
        cypher = str(row.get("cypher") or "")
        if not question.strip() or not cypher.strip():
            reasons["empty_question_or_cypher"] += 1
            result.dropped.append({**base_drop, "reason": "empty_question_or_cypher"})
            continue
        # Schema-free validation: only the read-only gate filters rows. Syntax
        # findings are recorded as diagnostics, never used to drop curated rows.
        validation = validate_cypher(cypher, parser=parser)
        if not validation.read_only:
            reasons["not_read_only"] += 1
            by_db_not_read_only[name] += 1
            result.dropped.append(
                {
                    **base_drop,
                    "reason": "not_read_only",
                    "detail": _read_only_detail(cypher),
                    "cypher": cypher,
                }
            )
            continue
        graph_profile = GRAPH_PROFILE_PREFIX + name
        content_key = (graph_profile, " ".join(question.lower().split()), " ".join(cypher.split()))
        if content_key in seen_content:
            reasons["duplicate_question_and_cypher"] += 1
            result.dropped.append({**base_drop, "reason": "duplicate_question_and_cypher"})
            continue
        seen_content.add(content_key)
        question_cyphers[content_key[:2]].add(content_key[2])

        derived_category, features = derive_coarse_category(cypher)
        schema_text = str(row.get("schema") or "")
        example = {
            "id": base_drop["id"],
            "graph_profile": graph_profile,
            "category": derived_category if category_mode == "derived" else "external",
            "derived_category": derived_category,
            "derived_category_method": CATEGORY_METHOD,
            "difficulty": "unknown",
            "structural_difficulty": features.get("difficulty", "unknown"),
            "question": question,
            "cypher": cypher,
            "structural_features": _compact_features(features),
            "reference_flags": reference_flags(cypher),
            "gates": {"read_only": True},
            "pipe_validation": {
                "syntax_valid": validation.syntax_valid,
                "error_codes": sorted({issue.code for issue in validation.errors}),
                "parser_available": parser.available,
            },
            "source": {
                "dataset": dataset,
                "revision": revision,
                "split": split,
                "original_id": row.get("instance_id"),
                "database_reference_alias": alias,
                "data_source": row.get("data_source"),
                "schema_sha256": hashlib.sha256(schema_text.encode("utf-8")).hexdigest()
                if schema_text
                else None,
            },
        }
        result.examples.append(example)
        by_db_kept[name] += 1

    ambiguous = sum(1 for cyphers in question_cyphers.values() if len(cyphers) > 1)
    result.examples.sort(key=lambda item: item["id"])
    result.counts = {
        "split": split,
        "input_rows": len(rows),
        "kept": len(result.examples),
        "drop_reasons": dict(sorted(reasons.items())),
        "by_database_input": dict(sorted(by_db_input.items())),
        "by_database_kept": dict(sorted(by_db_kept.items())),
        "by_database_not_read_only": dict(sorted(by_db_not_read_only.items())),
        "questions_with_multiple_distinct_cypher": ambiguous,
        "not_read_only_suspected_false_positives": sum(
            1
            for item in result.dropped
            if item.get("reason") == "not_read_only"
            and item.get("detail", {}).get("suspected_false_positive")
        ),
    }
    return result


def assign_external_splits(
    train_examples: Sequence[dict[str, Any]],
    test_examples: Sequence[dict[str, Any]],
    *,
    dev_fraction: float = 0.1,
    seed: str = "t2c2024-dev-v1",
) -> dict[str, list[dict[str, Any]]]:
    """Keep the upstream test split as ``test``; carve ``dev`` out of upstream train.

    The dev slice is a deterministic hash-ordered fraction per graph profile, so
    adding a new graph never reshuffles another graph's train/dev rows.
    """

    if not 0 <= dev_fraction < 1:
        raise ValueError("dev_fraction must be in [0, 1)")
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for example in train_examples:
        groups[str(example.get("graph_profile"))].append(example)
    train: list[dict[str, Any]] = []
    dev: list[dict[str, Any]] = []
    for profile in sorted(groups):
        ordered = sorted(
            groups[profile],
            key=lambda item: hashlib.sha256(f"{seed}:{item['id']}".encode()).hexdigest(),
        )
        n_dev = round(len(ordered) * dev_fraction)
        dev.extend(ordered[:n_dev])
        train.extend(ordered[n_dev:])
    return {
        "train": sorted(train, key=lambda item: item["id"]),
        "dev": sorted(dev, key=lambda item: item["id"]),
        "test": sorted(test_examples, key=lambda item: item["id"]),
    }


def question_overlap(
    train_examples: Sequence[Mapping[str, Any]],
    test_examples: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    """Count test rows whose normalized question also appears in train (same graph)."""

    def key(item: Mapping[str, Any]) -> tuple[str, str]:
        return str(item.get("graph_profile")), " ".join(str(item.get("question", "")).lower().split())

    train_keys = {key(item) for item in train_examples}
    train_query_keys = {(key(item), " ".join(str(item.get("cypher", "")).split())) for item in train_examples}
    return {
        "test_questions_seen_in_train": sum(1 for item in test_examples if key(item) in train_keys),
        "test_question_cypher_pairs_seen_in_train": sum(
            1
            for item in test_examples
            if (key(item), " ".join(str(item.get("cypher", "")).split())) in train_query_keys
        ),
    }


def _canonical_sha256(examples: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        json.dumps(example, ensure_ascii=False, sort_keys=True, default=str)
        for example in sorted(examples, key=lambda item: str(item["id"]))
    ]
    return hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest()


def external_stats(splits: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    all_rows = [row for split in PACKAGE_SPLITS for row in splits.get(split, [])]

    def count(rows: Iterable[Mapping[str, Any]], key: str) -> dict[str, int]:
        return dict(sorted(Counter(str(row.get(key)) for row in rows).items()))

    by_split_graph = {
        split: count(splits.get(split, []), "graph_profile") for split in PACKAGE_SPLITS
    }
    by_split_graph_category = {
        split: dict(
            sorted(
                Counter(
                    f"{row.get('graph_profile')}::{row.get('derived_category')}"
                    for row in splits.get(split, [])
                ).items()
            )
        )
        for split in PACKAGE_SPLITS
    }
    return {
        "total": len(all_rows),
        "by_split": {split: len(splits.get(split, [])) for split in PACKAGE_SPLITS},
        "by_graph": count(all_rows, "graph_profile"),
        "by_category": count(all_rows, "category"),
        "by_derived_category": count(all_rows, "derived_category"),
        "by_structural_difficulty": count(all_rows, "structural_difficulty"),
        "by_split_graph": by_split_graph,
        "by_split_graph_derived_category": by_split_graph_category,
        "by_data_source": dict(
            sorted(Counter(str(row.get("source", {}).get("data_source")) for row in all_rows).items())
        ),
    }


def write_external_benchmark_package(
    output_dir: str | Path,
    splits: Mapping[str, Sequence[dict[str, Any]]],
    *,
    dropped: Sequence[Mapping[str, Any]] = (),
    manifest_extra: Mapping[str, Any] | None = None,
    slices: Mapping[str, Sequence[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Write ``{train,dev,test,all}.jsonl``, ``stats.json``, ``dropped.jsonl``, ``manifest.json``.

    ``slices`` (default: ``standard_test_slices`` of the test split) go to
    ``slices/<name>.jsonl``.
    """

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    all_rows = sorted(
        (row for split in PACKAGE_SPLITS for row in splits.get(split, [])),
        key=lambda item: item["id"],
    )
    ids = [row["id"] for row in all_rows]
    duplicates = sorted(item for item, n in Counter(ids).items() if n > 1)
    if duplicates:
        raise ValueError(f"duplicate example ids across splits: {duplicates[:5]}")
    for split in PACKAGE_SPLITS:
        write_jsonl(out / f"{split}.jsonl", list(splits.get(split, [])))
    write_jsonl(out / "all.jsonl", all_rows)
    write_jsonl(out / "dropped.jsonl", list(dropped))
    slice_rows = standard_test_slices(splits.get("test", [])) if slices is None else slices
    for name, rows in slice_rows.items():
        write_jsonl(out / "slices" / f"{name}.jsonl", list(rows))
    stats = external_stats(splits)
    stats["slices"] = {name: len(rows) for name, rows in sorted(slice_rows.items())}
    stats["reference_flags_test"] = {
        key: sum(1 for row in splits.get("test", []) if (row.get("reference_flags") or {}).get(key))
        for key in ("unordered_limit", "ordered_limit", "question_in_upstream_train")
    }
    (out / "stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "converter_version": CONVERTER_VERSION,
        "category_method": CATEGORY_METHOD,
        "evidence_status": "external_curated_input_not_pipe_generated",
        "total_examples": len(all_rows),
        "split_counts": stats["by_split"],
        "dropped_rows_logged": len(dropped),
        "split_sha256": {
            split: _canonical_sha256(splits.get(split, [])) for split in PACKAGE_SPLITS
        },
        "slice_counts": stats["slices"],
        "sha256": _canonical_sha256(all_rows),
        **dict(manifest_extra or {}),
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    return {"manifest": manifest, "stats": stats, "output_dir": str(out)}


def read_external_package(directory: str | Path) -> dict[str, list[dict[str, Any]]]:
    base = Path(directory)
    return {split: read_jsonl(base / f"{split}.jsonl") for split in PACKAGE_SPLITS}


# ---------------------------------------------------------------------------
# Gold-execution audit (requires a live graph; the client is injected).
# ---------------------------------------------------------------------------


def audit_gold_execution(
    examples: Sequence[Mapping[str, Any]],
    client: Any,
    *,
    max_rows: int = 1000,
) -> list[dict[str, Any]]:
    """Execute each reference query as written (read-only) and record the outcome.

    Upstream rows were written against Neo4j's hosted demo databases, not the
    public dumps, so some references fail or return nothing locally. This audit
    makes that loss explicit instead of letting it surface as model error.
    """

    audit: list[dict[str, Any]] = []
    for example in examples:
        query = clean_cypher(str(example.get("cypher", "")))
        result = client.run(query, read_only=True, limit_rows=max_rows)
        audit.append(
            {
                "id": example.get("id"),
                "graph_profile": example.get("graph_profile"),
                "gold_execution_success": bool(result.success),
                "gold_row_count": len(result.rows) if result.success else 0,
                "gold_row_count_capped": bool(result.success and len(result.rows) >= max_rows),
                "error": None if result.success else str(result.error)[:500],
                "latency_ms": result.latency_ms,
            }
        )
    return audit


def apply_gold_audit(
    examples: Sequence[dict[str, Any]],
    audit_rows: Sequence[Mapping[str, Any]],
    *,
    require_non_empty: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep rows whose reference executed (and, by default, returned rows).

    Rows without an audit record are dropped with reason ``gold_not_audited``
    so a partial audit can never silently pass rows through.
    """

    by_id = {str(row.get("id")): row for row in audit_rows}
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for example in examples:
        record = by_id.get(str(example.get("id")))
        reason = None
        if record is None:
            reason = "gold_not_audited"
        elif not record.get("gold_execution_success"):
            reason = "gold_execution_failed"
        elif require_non_empty and int(record.get("gold_row_count", 0) or 0) == 0:
            reason = "gold_empty_result"
        if reason:
            dropped.append(
                {
                    "id": example.get("id"),
                    "graph_profile": example.get("graph_profile"),
                    "upstream_split": example.get("source", {}).get("split"),
                    "original_id": example.get("source", {}).get("original_id"),
                    "reason": reason,
                    "error": (record or {}).get("error"),
                }
            )
            continue
        updated = dict(example)
        gates = dict(updated.get("gates", {}))
        gates.update(
            {
                "execution_success": True,
                "non_empty": int(record.get("gold_row_count", 0) or 0) > 0,
            }
        )
        updated["gates"] = gates
        kept.append(updated)
    return kept, dropped


def oracle_predictions(
    examples: Sequence[Mapping[str, Any]],
    *,
    model: str = "oracle_gold_reference",
) -> list[dict[str, Any]]:
    """Predictions that copy the reference query: a harness self-check.

    Scoring these with ``scripts/evaluate_benchmark_predictions.py`` should give
    execution accuracy 1.0 on every row whose reference executes. Anything less
    is a harness defect (gating, normalization, or result comparison), not a
    model effect.
    """

    return [
        {
            "id": example.get("id"),
            "question": example.get("question"),
            "graph_profile": example.get("graph_profile"),
            "category": example.get("category"),
            "difficulty": example.get("difficulty"),
            "predicted_cypher": example.get("cypher"),
            "raw_text": example.get("cypher"),
            "model": model,
            "gold_cypher": example.get("cypher"),
            "error": None,
        }
        for example in examples
    ]


# ---------------------------------------------------------------------------
# Derived schemas from the dataset's ``schema`` field.
# ---------------------------------------------------------------------------

_REL_PATTERN = re.compile(r"^\(:`?([^`)\s]+)`?\)-\[:`?([^`\]\s]+)`?\]->\(:`?([^`)\s]+)`?\)\s*$")
_COMPACT_ENTITY = re.compile(r"^`?([A-Za-z_][\w]*)`?\s*\{(.*)\}\s*$")
_ENHANCED_HEADER = re.compile(r"^-\s+\*\*`?([^*`]+?)`?\*\*\s*$")
_ENHANCED_NODE_PROP = re.compile(r"^\s+-\s+`([^`:]+)`\s*:\s*([A-Z_]+)")
_ENHANCED_REL_PROP = re.compile(r"^\s+-\s+`([^`:]+)\s*:\s*([A-Z_]+)`")


def _split_schema_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {"node": [], "rel_props": [], "rels": []}
    current: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered.startswith("node properties"):
            current = "node"
            continue
        if lowered.startswith("relationship properties"):
            current = "rel_props"
            continue
        if lowered.startswith("the relationships"):
            current = "rels"
            continue
        if current and stripped:
            sections[current].append(line.rstrip())
    return sections


def _parse_property_block(lines: Sequence[str], *, relationship: bool) -> list[tuple[str, str, str]]:
    """Return (owner, property, type) triples from compact or enhanced lines."""

    triples: list[tuple[str, str, str]] = []
    owner: str | None = None
    enhanced_prop = _ENHANCED_REL_PROP if relationship else _ENHANCED_NODE_PROP
    for line in lines:
        compact = _COMPACT_ENTITY.match(line.strip())
        if compact:
            owner = None
            name, body = compact.group(1), compact.group(2)
            for item in body.split(","):
                if ":" not in item:
                    continue
                prop, value_type = item.split(":", 1)
                prop = prop.strip().strip("`")
                value_type = value_type.strip().split()[0] if value_type.strip() else "ANY"
                if prop:
                    triples.append((name, prop, value_type))
            continue
        header = _ENHANCED_HEADER.match(line.strip())
        if header:
            owner = header.group(1).strip()
            continue
        prop_match = enhanced_prop.match(line) or _ENHANCED_NODE_PROP.match(line)
        if prop_match and owner:
            triples.append((owner, prop_match.group(1).strip(), prop_match.group(2).strip()))
    return triples


def parse_t2c_schema_text(
    text: str,
    *,
    graph_name: str,
    source: str = f"derived:{T2C2024_DATASET}@{T2C2024_REVISION}:schema_field",
) -> SchemaSummary:
    """Parse the LangChain-style schema string carried by each dataset row.

    Supports both the compact (``Label {prop: TYPE}``) and the enhanced
    (``- **Label**`` / ``- `prop`: TYPE Example: ...``) layouts. Value samples
    ("Example", "Available options") are deliberately ignored: they are
    truncated upstream and must not become categorical literal constraints.
    """

    sections = _split_schema_sections(text)
    seen_nodes: set[tuple[str, str]] = set()
    node_properties: list[NodeProperty] = []
    for label, prop, value_type in _parse_property_block(sections["node"], relationship=False):
        if (label, prop) not in seen_nodes:
            seen_nodes.add((label, prop))
            node_properties.append(NodeProperty(label, prop, value_type))
    seen_rel_props: set[tuple[str, str]] = set()
    rel_properties: list[RelationshipProperty] = []
    for rel_type, prop, value_type in _parse_property_block(sections["rel_props"], relationship=True):
        if (rel_type, prop) not in seen_rel_props:
            seen_rel_props.add((rel_type, prop))
            rel_properties.append(RelationshipProperty(rel_type, prop, value_type))
    seen_patterns: set[tuple[str, str, str]] = set()
    relationships: list[RelationshipPattern] = []
    for line in sections["rels"]:
        match = _REL_PATTERN.match(line.strip())
        if match and match.groups() not in seen_patterns:
            seen_patterns.add(match.groups())
            relationships.append(RelationshipPattern(*match.groups()))
    return SchemaSummary(
        node_properties=node_properties,
        relationship_properties=rel_properties,
        relationships=relationships,
        categorical_properties={},
        graph_name=graph_name,
        source=source,
    )


def derived_schemas_by_profile(
    rows: Iterable[Mapping[str, Any]],
    *,
    databases: set[str] | None = None,
    revision: str = T2C2024_REVISION,
) -> dict[str, dict[str, Any]]:
    """Derive one schema per graph profile from its most frequent schema string.

    Returns ``{graph_profile: {"schema": SchemaSummary, "schema_sha256": ...,
    "variants": n, "rows_with_selected_variant": k, "rows_total": m}}``.
    """

    texts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        name = canonical_database_name(row.get("database_reference_alias"))
        if name is None or (databases is not None and name not in databases):
            continue
        text = str(row.get("schema") or "")
        if text:
            texts[GRAPH_PROFILE_PREFIX + name][text] += 1
    derived: dict[str, dict[str, Any]] = {}
    for profile, counter in sorted(texts.items()):
        # Most frequent first; ties broken by text hash for determinism.
        text, count = min(
            counter.items(), key=lambda item: (-item[1], hashlib.sha256(item[0].encode()).hexdigest())
        )
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        schema = parse_t2c_schema_text(
            text,
            graph_name=profile,
            source=f"derived:{T2C2024_DATASET}@{revision}:schema_field:sha256={digest[:16]}",
        )
        derived[profile] = {
            "schema": schema,
            "schema_sha256": digest,
            "variants": len(counter),
            "rows_with_selected_variant": count,
            "rows_total": sum(counter.values()),
        }
    return derived


def schema_drift(reference: SchemaSummary, live: SchemaSummary) -> dict[str, Any]:
    """Compare a derived (dataset) schema with a live-introspected schema.

    Missing labels, relationship types, or properties mean some upstream
    reference queries cannot execute on the local dump; report them before E3.4.
    """

    ref_node_props = {(p.label, p.property) for p in reference.node_properties}
    live_node_props = {(p.label, p.property) for p in live.node_properties}
    ref_rel_props = {(p.type, p.property) for p in reference.relationship_properties}
    live_rel_props = {(p.type, p.property) for p in live.relationship_properties}
    ref_patterns = {(r.start_label, r.type, r.end_label) for r in reference.relationships}
    live_patterns = {(r.start_label, r.type, r.end_label) for r in live.relationships}
    drift = {
        "missing_labels": sorted(reference.labels - live.labels),
        "extra_labels": sorted(live.labels - reference.labels),
        "missing_relationship_types": sorted(reference.relationship_types - live.relationship_types),
        "missing_node_properties": sorted(f"{a}.{b}" for a, b in ref_node_props - live_node_props),
        "missing_relationship_properties": sorted(f"{a}.{b}" for a, b in ref_rel_props - live_rel_props),
        "missing_relationship_patterns": sorted(
            f"(:{a})-[:{b}]->(:{c})" for a, b, c in ref_patterns - live_patterns
        ),
    }
    drift["compatible"] = not any(
        drift[key]
        for key in (
            "missing_labels",
            "missing_relationship_types",
            "missing_node_properties",
            "missing_relationship_properties",
            "missing_relationship_patterns",
        )
    )
    return drift


def graph_spec_records() -> list[dict[str, Any]]:
    """Serializable registry rows (used in manifests and the protocol)."""

    records = []
    for spec in EXAMPLE_GRAPHS.values():
        record = asdict(spec)
        record.update(
            {
                "graph_profile": spec.graph_profile,
                "dump_url": spec.dump_url,
                "dump_filename": spec.dump_filename,
            }
        )
        records.append(record)
    return records
