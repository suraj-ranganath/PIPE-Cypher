from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from pipecypher.config import load_config
from pipecypher.external_benchmarks import (
    EXAMPLE_GRAPHS,
    RECOMMENDED_GRAPHS,
    T2C2024_REVISION,
    annotate_upstream_train_overlap,
    apply_gold_audit,
    assign_external_splits,
    audit_gold_execution,
    canonical_database_name,
    convert_t2c_rows,
    derive_coarse_category,
    derived_schemas_by_profile,
    graph_profile_for_alias,
    hf_resolve_url,
    load_t2c_rows,
    oracle_predictions,
    parse_t2c_schema_text,
    reference_flags,
    resolve_database_filter,
    schema_drift,
    standard_test_slices,
    t2c_example_id,
    write_external_benchmark_package,
)
from pipecypher.io import read_jsonl, write_jsonl
from pipecypher.models import ExecutionResult
from scripts.fetch_text2cypher2024 import main as fetch_main

ROOT = Path(__file__).resolve().parents[1]

COMPACT_SCHEMA = """Node properties:
Product {productName: STRING, unitPrice: FLOAT, discontinued: BOOLEAN}
Category {categoryName: STRING}
Relationship properties:
ORDERS {quantity: INTEGER}
The relationships:
(:Product)-[:PART_OF]->(:Category)
(:Order)-[:ORDERS]->(:Product)"""

ENHANCED_SCHEMA = """Node properties:
- **Movie**
  - `title`: STRING Example: "Toy Story"
  - `year`: INTEGER Min: 1902, Max: 2016
- **Genre**
  - `name`: STRING Available options: ['Adventure', 'Comedy']
Relationship properties:
- **RATED**
  - `rating: FLOAT` Example: "2.0"
The relationships:
(:Movie)-[:IN_GENRE]->(:Genre)
(:User)-[:RATED]->(:Movie)"""


def _row(instance: str, alias: str | None, question: str, cypher: str, schema: str = COMPACT_SCHEMA, source="neo4jLabs_synthetic_gpt4o"):
    return {
        "question": question,
        "schema": schema,
        "cypher": cypher,
        "data_source": source,
        "instance_id": f"instance_id_{instance}",
        "database_reference_alias": alias,
    }


NW = "neo4jlabs_demo_db_northwind"
REC = "neo4jlabs_demo_db_recommendations"

TEST_ROWS = [
    _row("1", NW, "How many products are discontinued?", "MATCH (p:Product) WHERE p.discontinued = true RETURN count(p)"),
    _row("2", NW, "List products in category 'Dairy  Products'.", "MATCH (p:Product)-[:PART_OF]->(c:Category {categoryName: 'Dairy  Products'}) RETURN p.productName"),
    _row("3", NW, "Remove every product.", "MATCH (n) DETACH DELETE n"),
    _row("4", NW, "Products titled like 'Create box'?", "MATCH (p:Product {productName: 'Create box'}) RETURN p.unitPrice"),
    _row("5", NW, "How many products are discontinued?", "MATCH (p:Product) WHERE p.discontinued = true RETURN count(p)"),
    _row("6", None, "What is the total number of companies?", "MATCH (c:Company) RETURN COUNT(c)"),
    _row("7", "neo4jlabs_demo_db_companies", "Which organizations have a CEO?", "MATCH (o:Organization)-[:HAS_CEO]->(p:Person) RETURN o.name"),
    _row("8", REC, "Top 3 movies by rating?", "MATCH (m:Movie) RETURN m.title ORDER BY m.imdbRating DESC LIMIT 3", schema=ENHANCED_SCHEMA),
    _row("9", REC, "Any three movies?", "MATCH (m:Movie) RETURN m.title LIMIT 3", schema=ENHANCED_SCHEMA),
    _row("10", "neo4jlabs_demo_db_eoflix", "List movie titles.", "MATCH (m:Movie) RETURN m.title"),
    _row("11", NW, "", "MATCH (p:Product) RETURN p"),
]
TRAIN_ROWS = [
    _row("101", NW, "How many products are discontinued?", "MATCH (p:Product {discontinued: true}) RETURN count(*)"),
    _row("102", NW, "Which categories exist?", "MATCH (c:Category) RETURN c.categoryName"),
    _row("103", REC, "Which genres exist?", "MATCH (g:Genre) RETURN g.name", schema=ENHANCED_SCHEMA),
    _row("104", REC, "Count movies.", "MATCH (m:Movie) RETURN count(m)", schema=ENHANCED_SCHEMA),
    _row("105", NW, "Products per category?", "MATCH (p:Product)-[:PART_OF]->(c:Category) RETURN c.categoryName, count(p)"),
]


class FakeClient:
    def __init__(self, outcomes: dict[str, ExecutionResult]):
        self.outcomes = outcomes
        self.queries: list[str] = []

    def run(self, query, params=None, *, read_only=True, limit_rows=None):
        assert read_only
        self.queries.append(query)
        return self.outcomes.get(query, ExecutionResult(success=True, rows=[{"x": 1}]))


def test_alias_canonicalization_and_profiles():
    assert canonical_database_name(NW) == "northwind"
    assert canonical_database_name("neo4jlabs_demo_db_eoflix") == "neoflix"
    assert canonical_database_name("t2c_fincen") == "fincen"
    assert canonical_database_name(None) is None
    assert canonical_database_name("None") is None
    assert graph_profile_for_alias(REC) == "t2c_recommendations"


def test_database_filter_resolution():
    assert resolve_database_filter(None) == set(RECOMMENDED_GRAPHS)
    assert resolve_database_filter(["recommended"]) == {"recommendations", "northwind", "fincen"}
    assert resolve_database_filter(["all"]) is None
    assert resolve_database_filter(["t2c_movies,neo4jlabs_demo_db_network", "fincen"]) == {
        "movies",
        "network",
        "fincen",
    }


def test_example_ids_are_stable_and_content_addressed():
    row = TEST_ROWS[0]
    reordered = dict(reversed(list(row.items())))
    assert t2c_example_id(row) == t2c_example_id(reordered)
    assert re.fullmatch(r"t2c_[0-9a-f]{16}", t2c_example_id(row))
    changed = {**row, "cypher": row["cypher"] + " LIMIT 1"}
    assert t2c_example_id(changed) != t2c_example_id(row)
    # The schema text and data_source do not affect identity.
    assert t2c_example_id({**row, "schema": "x", "data_source": "y"}) == t2c_example_id(row)


def test_conversion_filters_databases_and_drops_writes():
    result = convert_t2c_rows(TEST_ROWS, split="test", databases={"northwind", "recommendations"})
    kept_ids = {row["source"]["original_id"] for row in result.examples}
    assert kept_ids == {"instance_id_1", "instance_id_2", "instance_id_8", "instance_id_9"}

    reasons = result.counts["drop_reasons"]
    assert reasons["no_database_alias"] == 1
    assert reasons["database_not_selected"] == 2  # companies + neoflix
    assert reasons["not_read_only"] == 2
    assert reasons["duplicate_question_and_cypher"] == 1
    assert reasons["empty_question_or_cypher"] == 1
    assert result.counts["by_database_not_read_only"] == {"northwind": 2}

    dropped = {row["original_id"]: row for row in result.dropped}
    assert dropped["instance_id_3"]["detail"]["blocked_tokens"] == ["DELETE", "DETACH"]
    assert dropped["instance_id_3"]["detail"]["suspected_false_positive"] is False
    # 'Create' inside a string literal still fails the gate, but is flagged.
    assert dropped["instance_id_4"]["reason"] == "not_read_only"
    assert dropped["instance_id_4"]["detail"]["suspected_false_positive"] is True
    assert result.counts["not_read_only_suspected_false_positives"] == 1
    # Rows without an alias are counted, not logged one by one.
    assert "instance_id_6" not in dropped


def test_converted_rows_keep_text_verbatim_and_carry_provenance():
    result = convert_t2c_rows(TEST_ROWS, split="test", databases={"northwind"})
    by_original = {row["source"]["original_id"]: row for row in result.examples}
    row = by_original["instance_id_2"]
    assert row["cypher"] == TEST_ROWS[1]["cypher"]  # double space inside the literal survives
    assert row["question"] == TEST_ROWS[1]["question"]
    assert row["graph_profile"] == "t2c_northwind"
    assert row["category"] == "external"
    assert row["derived_category"] == "simple_retrieval"
    assert row["difficulty"] == "unknown"
    assert row["gates"] == {"read_only": True}
    assert row["source"]["dataset"] == "neo4j/text2cypher-2024v1"
    assert row["source"]["revision"] == T2C2024_REVISION
    assert row["source"]["split"] == "test"
    assert row["source"]["database_reference_alias"] == NW
    assert len(row["source"]["schema_sha256"]) == 64
    assert "schema" not in row  # schema text is not copied into every row
    assert [r["id"] for r in result.examples] == sorted(r["id"] for r in result.examples)


def test_derived_category_mode_sets_category():
    result = convert_t2c_rows(TEST_ROWS, split="test", databases={"northwind"}, category_mode="derived")
    for row in result.examples:
        assert row["category"] == row["derived_category"]
    with pytest.raises(ValueError):
        convert_t2c_rows(TEST_ROWS, split="test", category_mode="nope")


@pytest.mark.parametrize(
    ("cypher", "expected"),
    [
        ("MATCH (p:Product) RETURN p.productName", "simple_retrieval"),
        ("MATCH (s:Supplier)-[:SUPPLIES]->(p:Product)-[:PART_OF]->(c:Category) RETURN s.companyName", "complex_retrieval"),
        ("MATCH (p:Product) RETURN count(*)", "simple_aggregation"),
        ("MATCH (p:Product)-[:PART_OF]->(c:Category) RETURN c.categoryName, avg(p.unitPrice)", "complex_aggregation"),
        ("MATCH (p:Product) WITH count(p) AS n RETURN n", "complex_aggregation"),
        ("MATCH (p:Product) RETURN p.productName ORDER BY p.unitPrice DESC LIMIT 5", "ranking_topk"),
        ("MATCH (c:Customer) WHERE NOT (c)-[:PURCHASED]->(:Order) RETURN c.companyName", "negation_difference"),
        ("MATCH (c:Customer) WHERE c.region IS NOT NULL RETURN c.companyName", "simple_retrieval"),
        ("MATCH (a:Person)-[:KNOWS*1..3]->(b:Person) RETURN b.name", "path_temporal"),
        ("MATCH (p:Product {productName: 'Chai'}) RETURN count(p) > 0 AS exists", "boolean_existence"),
        ("MATCH (p:Product) WHERE p.productName = 'NOT a filter' RETURN p", "simple_retrieval"),
    ],
)
def test_derive_coarse_category(cypher, expected):
    category, features = derive_coarse_category(cypher)
    assert category == expected
    assert "relationship_pattern_count" in features


def test_reference_flags_detect_unstable_truncation():
    assert reference_flags("MATCH (m:Movie) RETURN m.title LIMIT 3") == {
        "unordered_limit": True,
        "ordered_limit": False,
    }
    assert reference_flags("MATCH (m:Movie) RETURN m.title ORDER BY m.year LIMIT 3")["ordered_limit"]
    assert not any(reference_flags("MATCH (m:Movie {title: 'LIMIT'}) RETURN m").values())


def test_splits_keep_upstream_test_and_carve_dev_deterministically():
    train = convert_t2c_rows(TRAIN_ROWS, split="train", databases={"northwind", "recommendations"}).examples
    test = convert_t2c_rows(TEST_ROWS, split="test", databases={"northwind", "recommendations"}).examples
    first = assign_external_splits(train, test, dev_fraction=0.5)
    second = assign_external_splits(list(reversed(train)), list(reversed(test)), dev_fraction=0.5)
    assert first == second
    assert [r["id"] for r in first["test"]] == sorted(r["id"] for r in test)
    assert len(first["dev"]) + len(first["train"]) == len(train)
    assert {r["graph_profile"] for r in first["dev"]} == {"t2c_northwind", "t2c_recommendations"}
    assert not {r["id"] for r in first["dev"]} & {r["id"] for r in first["train"]}
    with pytest.raises(ValueError):
        assign_external_splits(train, test, dev_fraction=1.0)


def test_upstream_overlap_flags_and_slices():
    train = convert_t2c_rows(TRAIN_ROWS, split="train", databases={"northwind", "recommendations"}).examples
    test = convert_t2c_rows(TEST_ROWS, split="test", databases={"northwind", "recommendations"}).examples
    flagged = annotate_upstream_train_overlap(test, train)
    assert flagged == 1  # "How many products are discontinued?" also in train (different Cypher)
    slices = standard_test_slices(test)
    assert len(slices["test_unseen_question"]) == len(test) - 1
    assert len(slices["test_no_unordered_limit"]) == len(test) - 1  # instance 9
    assert len(slices["test_unseen_question_no_unordered_limit"]) == len(test) - 2
    assert {row["graph_profile"] for row in slices["test_t2c_northwind"]} == {"t2c_northwind"}
    assert len(slices["test_t2c_northwind"]) + len(slices["test_t2c_recommendations"]) == len(test)


def test_package_layout_matches_benchmark_scripts(tmp_path):
    train = convert_t2c_rows(TRAIN_ROWS, split="train", databases={"northwind", "recommendations"}).examples
    test = convert_t2c_rows(TEST_ROWS, split="test", databases={"northwind", "recommendations"}).examples
    splits = assign_external_splits(train, test, dev_fraction=0.2)
    out = tmp_path / "pkg"
    written = write_external_benchmark_package(out, splits, dropped=[{"id": "x", "reason": "r"}])
    for name in ("train", "dev", "test", "all", "dropped"):
        assert (out / f"{name}.jsonl").exists()
    assert (out / "slices" / "test_no_unordered_limit.jsonl").exists()
    all_rows = read_jsonl(out / "all.jsonl")
    assert len(all_rows) == len(train) + len(test)
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["split_counts"] == {split: len(rows) for split, rows in splits.items()}
    assert manifest["evidence_status"] == "external_curated_input_not_pipe_generated"
    rewritten = write_external_benchmark_package(tmp_path / "pkg2", splits)
    assert rewritten["manifest"]["sha256"] == written["manifest"]["sha256"]

    from scripts.evaluate_benchmark_predictions import _benchmark_records_path as eval_path
    from scripts.generate_text2cypher_predictions import _benchmark_records_path as gen_path

    assert eval_path(str(out), "test") == out / "test.jsonl"
    assert gen_path(str(out), "all") == out / "all.jsonl"
    for row in read_jsonl(gen_path(str(out), "test")):
        assert {"id", "question", "cypher", "graph_profile", "category", "difficulty"} <= set(row)

    with pytest.raises(ValueError, match="duplicate example ids"):
        write_external_benchmark_package(tmp_path / "bad", {"train": test, "dev": [], "test": test})


def test_gold_audit_keeps_only_executable_non_empty_references():
    test = convert_t2c_rows(TEST_ROWS, split="test", databases={"northwind", "recommendations"}).examples
    failing = test[0]["cypher"]
    empty = test[1]["cypher"]
    client = FakeClient(
        {
            failing: ExecutionResult(success=False, error="Unknown property"),
            empty: ExecutionResult(success=True, rows=[]),
        }
    )
    audit = audit_gold_execution(test[:3], client)
    assert client.queries == [row["cypher"] for row in test[:3]]  # executed as written
    kept, dropped = apply_gold_audit(test, audit)
    reasons = {row["id"]: row["reason"] for row in dropped}
    assert reasons[test[0]["id"]] == "gold_execution_failed"
    assert reasons[test[1]["id"]] == "gold_empty_result"
    assert all(reasons[row["id"]] == "gold_not_audited" for row in test[3:])
    assert [row["id"] for row in kept] == [test[2]["id"]]
    assert kept[0]["gates"]["execution_success"] and kept[0]["gates"]["non_empty"]

    kept_lenient, _ = apply_gold_audit(test[:3], audit, require_non_empty=False)
    assert {row["id"] for row in kept_lenient} == {test[1]["id"], test[2]["id"]}


def test_oracle_predictions_copy_reference():
    test = convert_t2c_rows(TEST_ROWS, split="test", databases={"northwind"}).examples
    preds = oracle_predictions(test)
    assert [p["id"] for p in preds] == [r["id"] for r in test]
    assert all(p["predicted_cypher"] == r["cypher"] and p["error"] is None for p, r in zip(preds, test))


def test_schema_text_parsing_compact_and_enhanced():
    compact = parse_t2c_schema_text(COMPACT_SCHEMA, graph_name="t2c_northwind")
    assert ("Product", "unitPrice", "FLOAT") in {(p.label, p.property, p.type) for p in compact.node_properties}
    assert {(p.type, p.property) for p in compact.relationship_properties} == {("ORDERS", "quantity")}
    assert compact.has_relationship("Product", "PART_OF", "Category")
    assert compact.categorical_properties == {}
    assert compact.source.startswith("derived:")

    enhanced = parse_t2c_schema_text(ENHANCED_SCHEMA, graph_name="t2c_recommendations")
    assert {(p.label, p.property) for p in enhanced.node_properties} == {
        ("Movie", "title"),
        ("Movie", "year"),
        ("Genre", "name"),
    }
    assert {(p.type, p.property, p.value_type) for p in enhanced.relationship_properties} == {
        ("RATED", "rating", "FLOAT")
    }
    assert enhanced.has_relationship("User", "RATED", "Movie")
    assert enhanced.categorical_properties == {}  # "Available options" are truncated upstream


def test_derived_schemas_pick_most_frequent_variant_and_drift():
    rows = TEST_ROWS + [_row("20", REC, "q", "MATCH (m:Movie) RETURN m", schema="Node properties:\nMovie {title: STRING}")]
    derived = derived_schemas_by_profile(rows, databases={"recommendations"})
    assert set(derived) == {"t2c_recommendations"}
    info = derived["t2c_recommendations"]
    assert info["variants"] == 2 and info["rows_with_selected_variant"] == 2
    schema = info["schema"]
    assert schema.has_relationship("Movie", "IN_GENRE", "Genre")

    live = parse_t2c_schema_text(ENHANCED_SCHEMA.replace("(:User)-[:RATED]->(:Movie)", ""), graph_name="live")
    drift = schema_drift(schema, live)
    assert drift["missing_relationship_patterns"] == ["(:User)-[:RATED]->(:Movie)"]
    assert drift["compatible"] is False
    assert schema_drift(schema, schema)["compatible"] is True


def test_load_rows_from_jsonl_and_json(tmp_path):
    jsonl = tmp_path / "test.jsonl"
    write_jsonl(jsonl, TEST_ROWS[:2])
    assert load_t2c_rows(jsonl) == TEST_ROWS[:2]
    js = tmp_path / "rows.json"
    js.write_text(json.dumps({"rows": [{"row": TEST_ROWS[0]}]}))
    assert load_t2c_rows(js) == [TEST_ROWS[0]]
    with pytest.raises(ValueError):
        load_t2c_rows(tmp_path / "rows.csv")


def test_cli_convert_end_to_end(tmp_path, capsys):
    train = tmp_path / "src" / "train.jsonl"
    test = tmp_path / "src" / "test.jsonl"
    write_jsonl(train, TRAIN_ROWS)
    write_jsonl(test, TEST_ROWS)
    out = tmp_path / "pkg"
    schema_dir = tmp_path / "schemas"
    code = fetch_main(
        [
            "convert",
            "--input", str(tmp_path / "src"),
            "--output-dir", str(out),
            "--databases", "northwind,recommendations",
            "--dev-fraction", "0.2",
            "--derived-schema-dir", str(schema_dir),
        ]
    )
    assert code == 0
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["filters"]["databases"] == ["northwind", "recommendations"]
    assert manifest["conversion_counts"]["test"]["drop_reasons"]["not_read_only"] == 2
    assert manifest["train_test_question_overlap"]["test_questions_seen_in_train"] == 1
    assert {g["name"] for g in manifest["example_graphs"]} == {"northwind", "recommendations"}
    assert manifest["source"]["files"]["test"]["sha256"]
    dropped = read_jsonl(out / "dropped.jsonl")
    assert sum(1 for row in dropped if row["reason"] == "not_read_only") == 2
    derived = json.loads((schema_dir / "schema_t2c_northwind_derived.json").read_text())
    assert derived["provenance"]["kind"] == "derived_from_dataset_schema_text"

    # Refuses to overwrite a populated package unless asked.
    with pytest.raises(SystemExit):
        fetch_main(["convert", "--input", str(tmp_path / "src"), "--output-dir", str(out)])

    oracle_out = tmp_path / "oracle.jsonl"
    assert fetch_main(["oracle", "--benchmark", str(out), "--split", "test", "--output", str(oracle_out)]) == 0
    assert len(read_jsonl(oracle_out)) == len(read_jsonl(out / "test.jsonl"))

    # Slice scoring: filter full-test rows to a per-graph slice's ids.
    sliced = tmp_path / "oracle_northwind.jsonl"
    slice_file = out / "slices" / "test_t2c_northwind.jsonl"
    assert fetch_main(["subset", "--rows", str(oracle_out), "--benchmark", str(slice_file), "--output", str(sliced)]) == 0
    assert {r["id"] for r in read_jsonl(sliced)} == {r["id"] for r in read_jsonl(slice_file)}
    with pytest.raises(SystemExit):
        fetch_main(["subset", "--rows", str(sliced), "--benchmark", str(out / "test.jsonl"), "--output", str(tmp_path / "x.jsonl")])
    capsys.readouterr()


def test_hf_url_is_pinned():
    url = hf_resolve_url("data/test-00000-of-00001.parquet")
    assert url == (
        "https://huggingface.co/datasets/neo4j/text2cypher-2024v1/resolve/"
        f"{T2C2024_REVISION}/data/test-00000-of-00001.parquet"
    )


def test_shell_script_matches_graph_registry():
    script = (ROOT / "scripts" / "fetch_neo4j_example_graphs.sh").read_text()
    specs = dict(re.findall(r"^\s+([a-z_]+)\)\n\s+echo \"([^\"]+)\" ;;", script, re.MULTILINE))
    assert set(specs) == set(EXAMPLE_GRAPHS)
    for name, spec in EXAMPLE_GRAPHS.items():
        repo, commit, path, sha, bolt, http = specs[name].split()
        assert (repo, commit, path, sha) == (spec.repo, spec.commit, spec.dump_path, spec.dump_sha256)
        assert (int(bolt), int(http)) == (spec.bolt_port, spec.http_port)
    assert "GRAPHS=\"${GRAPHS:-recommendations northwind fincen}\"" in script
    assert set(RECOMMENDED_GRAPHS) == {"recommendations", "northwind", "fincen"}


@pytest.mark.parametrize("name", sorted(RECOMMENDED_GRAPHS))
def test_t2c_configs_pass_strict_validation_and_match_registry(name):
    path = ROOT / "configs" / f"t2c_{name}.yaml"
    config = load_config(path, strict=True, validate=True)
    raw = yaml.safe_load(path.read_text())
    spec = EXAMPLE_GRAPHS[name]
    assert raw["generation"]["graph_profile"] == spec.graph_profile == config.generation.graph_profile
    assert raw["neo4j"]["uri"] == f"bolt://localhost:{spec.bolt_port}"
    assert raw["paths"]["schema_path"] == f"configs/schema_t2c_{name}.json"
    assert raw["models"]["generation_model"] == "Qwen/Qwen3.5-9B"
    assert raw["generation"]["target_per_category"] >= 50


@pytest.mark.parametrize("name", sorted(RECOMMENDED_GRAPHS))
def test_committed_derived_schemas_are_marked_derived(name):
    path = ROOT / "configs" / f"schema_t2c_{name}_derived.json"
    data = json.loads(path.read_text())
    assert data["source"].startswith("derived:neo4j/text2cypher-2024v1@")
    assert data["provenance"]["kind"] == "derived_from_dataset_schema_text"
    assert data["categorical_properties"] == {}
    assert data["graph_name"] == f"t2c_{name}"
    assert data["node_properties"] and data["relationships"]
