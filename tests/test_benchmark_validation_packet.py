from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

import pytest

from pipecypher.benchmark_validation_packet import (
    ERROR_TYPES,
    RUBRIC_FIELDS,
    analyze_validation_sheets,
    build_instance_packet,
    build_template_packet,
    normalize_error_types,
    proportional_allocation,
    signature_for_row,
    stratified_rate,
    validation_disagreement_rows,
    write_validation_packet,
)
from pipecypher.judge_agreement import PRIVATE_NOTICE, cohen_kappa, rate_with_ci, read_csv_rows
from pipecypher.schema import load_schema
from scripts import analyze_benchmark_validation as analyze_script
from scripts import build_benchmark_validation_packet as build_script

ROOT = Path(__file__).resolve().parents[1]


def _row(idx: int, graph: str, category: str, template: int = 0) -> dict:
    cypher_templates = [
        "MATCH (p:Person {{personName: '{v}'}})-[:OWN_ACCOUNT]->(a:Account) RETURN DISTINCT a.accountId AS AccountId",
        "MATCH (a:Account {{accountId: '{v}'}})-[:TRANSFER_TO]->(b:Account) RETURN DISTINCT b.accountId AS Dest LIMIT {n}",
        "MATCH (c:Company {{companyName: '{v}'}})-[:OWN_ACCOUNT]->(a:Account) RETURN DISTINCT COUNT(DISTINCT a) AS Total",
    ]
    cypher = cypher_templates[template].format(v=f"Value{idx}", n=10 + idx)
    return {
        "id": f"pc_{idx:04d}",
        "graph_profile": graph,
        "category": category,
        "difficulty": "easy",
        "question": f"Question {idx} about 'Value{idx}'?",
        "cypher": cypher,
        "normalized_cypher": cypher,
        "structural_features": {"difficulty": "easy", "primary_strategy": "single_hop"},
        "result_rows_sample": [{"AccountId": str(idx)}, {"AccountId": str(idx + 1)}],
        "result_row_count_observed": 25 if idx % 7 == 0 else 2,
        "gates": {"judge_pass": True},
        "judge_scores": {"semantic_alignment": 1.0},
        "source": {"run": "run_a"},
    }


def _population() -> list[dict]:
    rows = []
    idx = 0
    sizes = {("finbench", "simple_retrieval"): 40, ("finbench", "ranking_topk"): 40, ("snb", "simple_retrieval"): 20, ("snb", "ranking_topk"): 3}
    for (graph, category), size in sizes.items():
        for _ in range(size):
            rows.append(_row(idx, graph, category, template=idx % 3))
            idx += 1
    return rows


def test_wilson_interval_known_values():
    zero = rate_with_ci(0, 10)
    assert zero["rate"] == 0.0
    assert zero["ci95"][0] == pytest.approx(0.0)
    assert zero["ci95"][1] == pytest.approx(0.2775, abs=1e-4)
    half = rate_with_ci(5, 10)
    assert half["ci95"] == pytest.approx([0.2366, 0.7634], abs=1e-4)
    assert rate_with_ci(0, 0)["rate"] is None


def test_proportional_allocation_largest_remainder_and_floor():
    population = {"a": 250, "b": 250, "c": 125, "d": 125, "e": 3}
    alloc = proportional_allocation(population, 60, min_per_stratum=1, seed=3)
    assert sum(alloc.values()) == 60
    assert alloc["e"] >= 1
    # quotas: a=b=19.92, c=d=9.96, e=0.24 -> floors 19/19/9/9 + floor-of-1 for e = 57;
    # the 3 remaining seats go to the largest remainders (c, d) and one seeded tie-break (a or b).
    assert alloc["c"] == alloc["d"] == 10 and alloc["e"] == 1
    assert sorted([alloc["a"], alloc["b"]]) == [19, 20]
    assert proportional_allocation(population, 10_000) == population
    assert proportional_allocation(population, 60, seed=3) == alloc


def test_instance_packet_is_stratified_and_deterministic():
    rows = _population()
    first = build_instance_packet(rows, n=30, seed=5)
    second = build_instance_packet(list(reversed(rows)), n=30, seed=5)
    other = build_instance_packet(rows, n=30, seed=6)
    assert [r["item_id"] for r in first] == [r["item_id"] for r in second]
    assert {r["item_id"] for r in first} != {r["item_id"] for r in other}
    assert len(first) == 30 and len({r["item_id"] for r in first}) == 30
    counts = Counter(r["stratum"] for r in first)
    assert counts["finbench::simple_retrieval"] == counts["finbench::ranking_topk"]
    assert counts["snb::ranking_topk"] >= 1
    for row in first:
        assert row["stratum_sample_size"] == counts[row["stratum"]]
    assert {r["stratum_population"] for r in first if r["stratum"] == "snb::simple_retrieval"} == {20}


def test_template_packet_one_row_per_signature_times_two():
    rows = [_row(i, "finbench", "simple_retrieval", template=0) for i in range(5)]
    rows += [_row(10, "finbench", "complex_aggregation", template=2)]
    rows += [_row(20 + i, "snb", "ranking_topk", template=1) for i in range(3)]
    packet = build_template_packet(rows, realizations=2, seed=11)
    by_sig = Counter(r["signature_id"] for r in packet)
    signatures = {signature_for_row(r) for r in rows}
    assert len(by_sig) == len(signatures) == 3
    assert sorted(by_sig.values()) == [1, 2, 2]
    sizes = {r["signature_id"]: r["signature_group_size"] for r in packet}
    assert sorted(sizes.values()) == [1, 3, 5]
    assert {r["realization_index"] for r in packet} == {1, 2}
    assert [r["item_id"] for r in build_template_packet(rows, seed=11)] == [r["item_id"] for r in packet]
    assert all("Value" not in r["canonical_signature"] for r in packet)


def test_write_packet_creates_shuffled_identical_sheets(tmp_path: Path):
    packet = build_instance_packet(_population(), n=20, seed=1)
    schema = load_schema(ROOT / "configs" / "schema_finbench.json")
    manifest = write_validation_packet(
        packet,
        tmp_path,
        mode="instances",
        annotators=["ann_a", "ann_b", "ann_c"],
        seed=9,
        schemas={"finbench": schema},
    )
    orders = []
    for sheet in manifest["annotator_sheets"]:
        with open(sheet["path"], encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 20
        assert all(row[field] == "" for row in rows for field in RUBRIC_FIELDS)
        assert {row["annotator"] for row in rows} == {sheet["annotator"]}
        assert "judge_pass" not in rows[0]  # annotators are blind to the original judge
        orders.append([row["item_id"] for row in rows])
    assert all(set(order) == set(orders[0]) for order in orders)
    assert orders[0] != orders[1] or orders[1] != orders[2]
    key = read_csv_rows(manifest["key"]["path"])
    assert {row["item_id"] for row in key} == set(orders[0])
    assert "judge_pass" in key[0] and "question" not in key[0]
    rubric = Path(manifest["rubric"]["path"]).read_text()
    assert PRIVATE_NOTICE in rubric and all(name in rubric for name in ERROR_TYPES)
    assert (tmp_path / "schema_finbench.txt").exists()


def _fill(path: str, labels: dict[str, tuple[str, str, str, str]]) -> None:
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        rows = list(reader)
    for row in rows:
        q, ref, cols, err = labels[row["item_id"]]
        row.update({"question_unambiguous": q, "reference_correct": ref, "answer_columns_appropriate": cols, "error_type": err})
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_analyze_two_annotators_kappa_ci_disagreements_and_adjudication(tmp_path: Path):
    packet = build_instance_packet(_population(), n=20, seed=2)
    manifest = write_validation_packet(packet, tmp_path, mode="instances", annotators=["a", "b"], seed=4)
    ids = sorted(r["item_id"] for r in packet)
    # a: items 0-3 incorrect; b: items 0-2 and 4 incorrect -> 3 joint no, 2 disagreements.
    a = {i: ("yes", "no" if k < 4 else "yes", "yes", "wrong_filter" if k < 4 else "") for k, i in enumerate(ids)}
    b = {i: ("yes", "no" if k in (0, 1, 2, 4) else "yes", "yes", "missing results" if k in (0, 1, 2, 4) else "") for k, i in enumerate(ids)}
    sheet_a, sheet_b = (s["path"] for s in manifest["annotator_sheets"])
    _fill(sheet_a, a)
    _fill(sheet_b, b)
    key = manifest["key"]["path"]

    report = analyze_validation_sheets([sheet_a, sheet_b], key_path=key)
    ref = report["fields"]["reference_correct"]
    assert ref["unresolved"] == 2
    assert ref["consensus_no_rate"]["count"] == 3 and ref["consensus_no_rate"]["n"] == 18
    assert ref["all_annotators_no_rate"]["count"] == 3
    assert ref["any_annotator_no_rate"]["count"] == 5
    pair = report["agreement"]["reference_correct"]["pairwise"][0]
    la = [a[i][1] == "yes" for i in ids]
    lb = [b[i][1] == "yes" for i in ids]
    assert pair["cohen_kappa"] == pytest.approx(cohen_kappa(la, lb))
    assert pair["agreement"] == pytest.approx(18 / 20)
    assert report["agreement"]["question_unambiguous"]["pairwise"][0]["cohen_kappa"] is None
    assert report["headline"]["ready_for_paper"] is False
    assert report["error_types"]["per_annotator"]["b"]["missing_results"] == 4
    assert report["estimates"]["stratified_reference_error"]["rate"] is not None
    assert set(report["slices"]["by_graph"]) == {"finbench", "snb"}

    rows, fields = validation_disagreement_rows([sheet_a, sheet_b], key_path=key)
    assert {row["item_id"] for row in rows} == {ids[3], ids[4]}
    disagreements = tmp_path / "disagreements.csv"
    code = analyze_script.main(
        [
            "--sheets", sheet_a, sheet_b,
            "--key", key,
            "--output-json", str(tmp_path / "report.json"),
            "--output-md", str(tmp_path / "report.md"),
            "--output-tex", str(tmp_path / "report.tex"),
            "--output-disagreements-csv", str(disagreements),
            "--require-complete",
        ]
    )
    assert code == 1  # unresolved disagreements block paper use
    assert disagreements.read_text(encoding="utf-8").startswith("# PRIVATE/internal")

    adjudicated = read_csv_rows(disagreements)
    for row in adjudicated:
        row["adjudicated_reference_correct"] = "no" if row["item_id"] == ids[3] else "yes"
    with open(tmp_path / "adjudicated.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(adjudicated[0]))
        writer.writeheader()
        writer.writerows(adjudicated)
    code = analyze_script.main(
        [
            "--sheets", sheet_a, sheet_b,
            "--key", key,
            "--adjudication", str(tmp_path / "adjudicated.csv"),
            "--output-json", str(tmp_path / "report2.json"),
            "--require-complete",
        ]
    )
    assert code == 0
    final = json.loads((tmp_path / "report2.json").read_text())
    rate = final["headline"]["reference_error_rate"]
    assert (rate["count"], rate["n"]) == (4, 20)
    assert rate["ci95"] == pytest.approx(rate_with_ci(4, 20)["ci95"])
    assert "\\begin{tabular}" in (tmp_path / "report.tex").read_text()


def test_three_annotators_report_fleiss_and_majority(tmp_path: Path):
    packet = build_template_packet(_population(), realizations=2, seed=3)
    manifest = write_validation_packet(packet, tmp_path, mode="templates", annotators=["a", "b", "c"], seed=4)
    ids = sorted(r["item_id"] for r in packet)
    sheets = [s["path"] for s in manifest["annotator_sheets"]]
    for n, path in enumerate(sheets):
        _fill(path, {i: ("yes", "no" if (k == 0 or (k == 1 and n == 0)) else "yes", "yes", "other") for k, i in enumerate(ids)})
    report = analyze_validation_sheets(sheets, key_path=manifest["key"]["path"])
    assert "fleiss" in report["agreement"]["reference_correct"]
    assert report["fields"]["reference_correct"]["consensus_sources"].get("majority") == 1
    assert report["fields"]["reference_correct"]["unresolved"] == 0
    sig = report["estimates"]["signatures"]
    assert sig["signatures_labeled"] == 3
    assert sig["signatures_with_incorrect_realization"]["count"] == 1
    assert 0 < sig["frequency_weighted_reference_error"] < 1


def test_normalize_error_types_and_stratified_rate():
    assert normalize_error_types("Wrong filter; missing-results") == ["wrong_filter", "missing_results"]
    assert normalize_error_types("typo") == ["nonstandard:typo"]
    estimate = stratified_rate({"a": (100, [True] * 9 + [False]), "b": (100, [True] * 10)})
    assert estimate["rate"] == pytest.approx(0.05)
    assert estimate["ci95"][0] >= 0.0 and estimate["ci95"][1] > 0.05


def test_build_script_writes_packet(tmp_path: Path):
    bench = tmp_path / "all.jsonl"
    bench.write_text("".join(json.dumps(r) + "\n" for r in _population()), encoding="utf-8")
    code = build_script.main(
        [
            "--benchmark", str(bench),
            "--mode", "instances",
            "--n", "12",
            "--annotators", "3",
            "--output-dir", str(tmp_path / "packet"),
        ]
    )
    assert code == 0
    manifest = json.loads((tmp_path / "packet" / "benchmark_validation_instances_manifest.json").read_text())
    assert manifest["row_count"] == 12 and len(manifest["annotator_sheets"]) == 3
    assert manifest["source"]["rows_sha256"]
