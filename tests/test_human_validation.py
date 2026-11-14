from __future__ import annotations

import json
from collections import Counter

import pytest

from pipecypher.human_validation import (
    allocate,
    assign_annotators,
    build_key,
    build_page_data,
    item_outcomes,
    load_solve_counts,
    load_verdicts,
    normalize_conventions,
    page_item,
    parse_label_dump,
    sample_items,
    schema_slice_text,
    summarize_labels,
    weighted_rate,
)
from pipecypher.models import NodeProperty, RelationshipPattern, RelationshipProperty, SchemaSummary

GRAPHS = ("finbench", "snb")
CATEGORIES = ("simple_retrieval", "ranking_topk", "path_temporal", "negation_difference")


def _rows(n_per_cell: int = 30) -> list[dict]:
    rows = []
    for graph in GRAPHS:
        for ci, category in enumerate(CATEGORIES):
            for i in range(n_per_cell):
                tier = "hard" if i % 10 == 0 else ("medium" if i % 3 == 0 else "easy")
                rows.append(
                    {
                        "id": f"pc_{graph[0]}{ci}{i:03d}",
                        "graph_profile": graph,
                        "category": category,
                        "difficulty": tier,
                        "question": f"Which accounts did account {i} transfer to?",
                        "cypher": "MATCH (a:Account)-[:TRANSFER_TO]->(b:Account) RETURN b.accountId AS id",
                        "result_rows_sample": [{"id": str(k), "big": 2**60, "nested": {"x": 1}} for k in range(8)],
                        "result_row_count_observed": 8,
                        "structural_features": {"labels": ["Account"], "relationship_types": ["TRANSFER_TO"]},
                        "gates": {"judge_pass": True},
                    }
                )
    return rows


def test_allocate_respects_caps_floor_and_total():
    sizes = {"a": 100, "b": 10, "c": 2, "d": 0}
    alloc = allocate(sizes, {"a": 1.0, "b": 1.0, "c": 5.0}, 40, min_per_stratum=1, seed=1)
    assert sum(alloc.values()) == 40
    assert alloc["d"] == 0
    assert all(alloc[k] <= sizes[k] for k in sizes)
    assert alloc["c"] == 2  # boosted small stratum is taken whole
    assert alloc["a"] > alloc["b"] >= 1


def test_allocate_caps_total_at_population():
    alloc = allocate({"a": 3, "b": 2}, {}, 50)
    assert alloc == {"a": 3, "b": 2}


def test_sample_is_stratified_weighted_and_deterministic():
    rows = _rows()
    solved = {row["id"]: 0 if row["id"].endswith(("1", "2")) else 3 for row in rows}
    evaluated = {row["id"]: 5 for row in rows}
    items = sample_items(rows, n=120, seed=7, solved=solved, evaluated=evaluated)
    again = sample_items(rows, n=120, seed=7, solved=solved, evaluated=evaluated)
    assert [i.item_id for i in items] == [i.item_id for i in again]
    assert len(items) == 120
    assert len({i.item_id for i in items}) == 120
    # Every graph x category x tier cell with members is represented.
    cells = {(r["graph_profile"], r["category"], r["difficulty"]) for r in rows}
    assert {(i.row["graph_profile"], i.row["category"], i.tier) for i in items} == cells
    # Weights reconstruct the population exactly.
    assert sum(i.weight for i in items) == pytest.approx(len(rows))
    # Hard and unsolved items are oversampled relative to their population share.
    hard_share_pop = sum(r["difficulty"] == "hard" for r in rows) / len(rows)
    hard_share_sample = sum(i.tier == "hard" for i in items) / len(items)
    assert hard_share_sample > hard_share_pop
    focus_pop = sum(solved[r["id"]] == 0 for r in rows) / len(rows)
    focus_sample = sum("unsolved" in i.focus_reasons for i in items) / len(items)
    assert focus_sample > focus_pop
    # A different seed gives a different sample.
    other = sample_items(rows, n=120, seed=8, solved=solved, evaluated=evaluated)
    assert [i.item_id for i in other] != [i.item_id for i in items]


def test_judge_disagreement_marks_focus():
    rows = _rows(5)
    verdicts = {rows[0]["id"]: {"glm": True, "luna": False}, rows[1]["id"]: {"glm": True, "luna": True}}
    items = sample_items(rows, n=len(rows), verdicts=verdicts)
    reasons = {i.item_id: i.focus_reasons for i in items}
    assert reasons[rows[0]["id"]] == ["judge_disagreement"]
    assert reasons[rows[1]["id"]] == []


def test_assignment_overlap_and_order():
    items = sample_items(_rows(), n=200, seed=3)
    assignment = assign_annotators(items, annotators=("A", "B"), per_annotator=130, shared=60, seed=3)
    queues = assignment["queues"]
    shared = set(assignment["shared"])
    assert len(shared) == 60
    assert len(queues["A"]) == len(queues["B"]) == 130
    assert len(set(queues["A"])) == 130 and len(set(queues["B"])) == 130
    assert set(queues["A"]) & set(queues["B"]) == shared
    assert set(queues["A"]) | set(queues["B"]) == {i.item_id for i in items}
    assert assignment["unassigned"] == []
    # Shared items sit in the first part of each queue, in different orders.
    for queue in queues.values():
        assert {item_id for item_id in queue[:120]} >= shared
    shared_order_a = [i for i in queues["A"] if i in shared]
    shared_order_b = [i for i in queues["B"] if i in shared]
    assert shared_order_a != shared_order_b
    # Shared items span strata.
    by_id = {i.item_id: i for i in items}
    assert len({by_id[i].row["category"] for i in shared}) == len(CATEGORIES)


def test_assignment_requires_enough_items():
    items = sample_items(_rows(2), n=10)
    with pytest.raises(ValueError):
        assign_annotators(items, per_annotator=130, shared=60)


def _schema() -> SchemaSummary:
    return SchemaSummary(
        node_properties=[NodeProperty("Account", "accountId", "String"), NodeProperty("Person", "name", "String")],
        relationship_properties=[RelationshipProperty("TRANSFER_TO", "amount", "Double"), RelationshipProperty("KNOWS", "since", "Long")],
        relationships=[
            RelationshipPattern("Account", "TRANSFER_TO", "Account"),
            RelationshipPattern("Person", "KNOWS", "Person"),
        ],
        categorical_properties={"Account.accountType": ["debit card"], "Person.gender": ["f"]},
        graph_name="finbench",
        symmetric_relationships=["KNOWS"],
    )


def test_schema_slice_keeps_only_used_labels_and_types():
    text = schema_slice_text(_schema(), ["Account"], ["TRANSFER_TO"])
    assert "TRANSFER_TO" in text and "accountId" in text and "Account.accountType" in text
    assert "KNOWS" not in text and "Person" not in text
    sym = schema_slice_text(_schema(), ["Person"], ["KNOWS"])
    assert "Symmetric relationship types" in sym


def test_page_data_is_blind_and_safe():
    rows = _rows()
    verdicts = {rows[0]["id"]: {"glm": True, "luna": False}}
    items = sample_items(rows, n=200, seed=3, verdicts=verdicts)
    assignment = assign_annotators(items, seed=3)
    page = build_page_data(items, assignment, schemas={"finbench": _schema()}, set_id="test-set", conventions=[{"name": "C1 Values", "rule": "Quoted text is exact."}])
    blob = json.dumps(page)
    for forbidden in ("difficulty", "category", "verdict", "judge", "solved", "luna", "simple_retrieval", "weight"):
        assert forbidden not in blob, forbidden
    item = next(iter(page["items"].values()))
    assert set(item) == {"id", "graph", "question", "cypher", "columns", "rows", "row_count", "row_count_capped", "schema"}
    assert len(item["rows"]) == 5
    assert item["rows"][0][1] == str(2**60)  # beyond JS safe integers -> text
    assert page["unclear_conventions"][0] == {"value": "C1", "label": "C1 Values"}
    assert page["unclear_conventions"][-1]["value"] == "not_covered"
    key = build_key(items, assignment, set_id="test-set")
    assert {row["item_id"] for row in key} == set(page["items"])
    shared_rows = [row for row in key if row["shared"]]
    assert len(shared_rows) == 60 and all(row["annotators"] == ["A", "B"] for row in shared_rows)
    assert all(len(row["annotators"]) == 1 for row in key if not row["shared"])


def test_page_item_row_count_cap_flag():
    row = _rows(1)[0]
    row["result_row_count_observed"] = 25
    assert page_item(row, None)["row_count_capped"] is True


def test_normalize_conventions_parses_sheet_text():
    sheet = "Benchmark conventions:\nC1 Values. Quoted text is exact.\nC2 Direction. Verbs fix direction.\n"
    entries = normalize_conventions(sheet)
    assert entries[0] == {"name": "", "rule": "Benchmark conventions:"}
    assert entries[1] == {"name": "C1 Values", "rule": "Quoted text is exact."}
    assert entries[2]["name"] == "C2 Direction"
    assert normalize_conventions([{"name": "x", "rule": "y"}]) == [{"name": "x", "rule": "y"}]
    assert normalize_conventions(None) == []


def test_load_solve_counts_and_verdicts(tmp_path):
    for model, results in (("m1", [True, False]), ("m2", [False, False])):
        path = tmp_path / f"{model}.jsonl"
        path.write_text(
            "\n".join(json.dumps({"id": f"i{k}", "projected_execution_accuracy": ok}) for k, ok in enumerate(results)) + "\n"
        )
    solved, evaluated = load_solve_counts(sorted(tmp_path.glob("m*.jsonl")))
    assert solved == {"i0": 1} and evaluated == {"i0": 2, "i1": 2}
    verdict_path = tmp_path / "judge.jsonl"
    verdict_path.write_text(
        json.dumps({"item_id": "i0", "decision": False})
        + "\n"
        + json.dumps({"item_id": "i1", "decision": None, "error": "timeout"})
        + "\n"
        + json.dumps({"id": "i2", "verdict": "pass"})
        + "\n"
    )
    assert load_verdicts({"j": verdict_path}) == {"i0": {"j": False}, "i2": {"j": True}}


def _labels_fixture():
    items = sample_items(_rows(), n=200, seed=5)
    assignment = assign_annotators(items, seed=5)
    key = build_key(items, assignment, set_id="s")
    labels = []
    shared = set(assignment["shared"])
    for name, queue in assignment["queues"].items():
        for index, item_id in enumerate(queue):
            reference = "wrong" if index % 10 == 0 else ("minor" if index % 10 == 1 else "correct")
            if item_id in shared and name == "B" and index % 7 == 0:
                reference = "correct" if reference != "correct" else "wrong"  # some disagreement
            labels.append(
                {
                    "id": f"s--{name}--{item_id}",
                    "data": {
                        "set_id": "s", "item_id": item_id, "annotator": name,
                        "clarity": "ambiguous" if index % 5 == 0 else "clear",
                        "unclear_convention": "C4" if index % 5 == 0 else "",
                        "reference": reference, "note": "", "skipped": False,
                        "updated_at": f"2026-11-13T16:{index % 60:02d}:00Z",
                    },
                }
            )
    return items, assignment, key, labels


def test_parse_label_dump_keeps_newest_and_handles_shapes():
    old = {"set_id": "s", "item_id": "i1", "annotator": "A", "clarity": "clear", "reference": "wrong", "updated_at": "2026-11-13T10:00:00Z"}
    new = dict(old, reference="correct", updated_at="2026-11-13T11:00:00Z")
    download = {"set_id": "s", "annotator": "A", "labels": [old]}
    parsed = parse_label_dump([download, {"documents": [{"id": "x", "data": new}]}, {"junk": 1}])
    assert len(parsed) == 1 and parsed[0]["reference"] == "correct"


def test_summary_kappa_rates_and_judge_agreement():
    items, assignment, key, labels = _labels_fixture()
    parsed = parse_label_dump(labels)
    verdicts = {row["item_id"]: {"glm": True, "luna": not row["item_id"].endswith("3")} for row in key}
    summary = summarize_labels(parsed, key, verdicts=verdicts, set_id="s", n_boot=300)
    pair = summary["inter_annotator"]["A|B"]
    assert pair["reference_3way"]["n"] == 60
    assert 0 < pair["reference_3way"]["agreement"] < 1
    assert pair["reference_3way"]["cohen_kappa"] is not None
    err = summary["reference_error_rate"]
    assert err["n"] == 200
    low, high = err["ci95"]
    assert 0 <= low <= err["estimate"] <= high <= 1
    assert summary["reference_error_or_minor_rate"]["estimate"] >= err["estimate"]
    assert summary["question_ambiguity_rate"]["estimate"] > 0
    assert summary["unclear_conventions"] == {"C4": sum(1 for l in parsed if l["clarity"] == "ambiguous")}
    assert summary["progress"]["A"] == {"expected": 130, "completed": 130, "skipped": 0}
    luna = summary["judge_human"]["luna"]["lenient"]
    assert luna["n"] == len(parsed)
    assert 0 <= luna["precision"] <= 1
    # glm passes everything: kappa undefined or 0, precision equals human ok rate.
    glm = summary["judge_human"]["glm"]["lenient"]
    assert glm["precision"] == pytest.approx(glm["human_ok_rate"])


def test_weighted_rate_reweights_oversampled_strata():
    key = {
        "a1": {"stratum": "big", "stratum_population": 90},
        "a2": {"stratum": "big", "stratum_population": 90},
        "b1": {"stratum": "small", "stratum_population": 10},
        "b2": {"stratum": "small", "stratum_population": 10},
    }
    result = weighted_rate({"a1": 0.0, "a2": 0.0, "b1": 1.0, "b2": 1.0}, key, n_boot=200)
    assert result["unweighted"] == pytest.approx(0.5)
    assert result["estimate"] == pytest.approx(0.1)
    assert result["population_coverage"] == pytest.approx(1.0)


def test_item_outcomes_average_annotators_and_adjudication():
    labels = [
        {"item_id": "i", "annotator": "A", "clarity": "clear", "reference": "wrong", "skipped": False},
        {"item_id": "i", "annotator": "B", "clarity": "ambiguous", "reference": "correct", "skipped": False},
        {"item_id": "j", "annotator": "A", "clarity": None, "reference": None, "skipped": True},
    ]
    outcomes = item_outcomes(labels)
    assert outcomes["i"]["wrong"] == 0.5 and outcomes["i"]["ambiguous"] == 0.5
    assert "j" not in outcomes
    adjudicated = item_outcomes(labels, {"i": {"reference": "correct"}})
    assert adjudicated["i"]["wrong"] == 0.0


def test_checklist_label_uses_the_judge_verdict_rule():
    import itertools

    from pipecypher.human_validation import checklist_label_fields, parse_label_dump
    from pipecypher.judge import CHECKLIST_CRITERIA, compute_checklist_verdict

    base = {name: "yes" for name in CHECKLIST_CRITERIA}
    for name, answer in itertools.product(CHECKLIST_CRITERIA, ("yes", "no", "na")):
        checklist = {**base, name: answer}
        fields = checklist_label_fields(checklist)
        passed, failing, _ = compute_checklist_verdict({k: {"answer": v} for k, v in checklist.items()})
        assert fields["passed"] == passed
        assert fields["failing"] == failing
        assert (fields["reference"] == "wrong") == any(f != "unambiguous" for f in failing)
        assert (fields["clarity"] == "ambiguous") == ("unambiguous" in failing)
    assert checklist_label_fields({**base, "values": ""}) is None

    rows = parse_label_dump([{"id": "x", "data": {"set_id": "v3c", "item_id": "i1", "annotator": "A",
                                                  "checklist": {**base, "ranking": "na"}, "updated_at": "1"}}])
    assert rows[0]["reference"] == "correct" and rows[0]["clarity"] == "clear" and rows[0]["passed"] is True


def test_checklist_summary_reports_criteria_against_stored_judges():
    from pipecypher.human_validation import parse_label_dump, summarize_labels
    from pipecypher.judge import CHECKLIST_CRITERIA

    yes = {name: "yes" for name in CHECKLIST_CRITERIA}
    key_rows = [
        {"item_id": f"i{i}", "set_id": "v3c", "stratum": "s", "stratum_population": 10, "shared": True,
         "annotators": ["A", "B"], "graph_profile": "g", "tier": "easy", "category": "c",
         "judge_checklists": {"glm": {"passed": True, "checklist": dict(yes)}}}
        for i in range(4)
    ]
    docs = []
    for i in range(4):
        for annotator in ("A", "B"):
            checklist = dict(yes)
            if i == 0:
                checklist["relationships"] = "no"
            docs.append({"set_id": "v3c", "item_id": f"i{i}", "annotator": annotator, "checklist": checklist, "updated_at": "1"})
    summary = summarize_labels(parse_label_dump(docs), key_rows, set_id="v3c", n_boot=50)
    assert summary["verdict_fail_rate"]["unweighted"] == 0.25
    rel = summary["criteria"]["relationships"]
    assert rel["fail_rate"] == 0.25
    assert rel["vs_judges"]["glm"]["agreement"] == 0.75
    assert rel["between_annotators"]["agreement"] == 1.0
    assert summary["inter_annotator"]["A|B"]["verdict_pass"]["agreement"] == 1.0


def test_collapse_strata_keeps_every_cell_and_merges_smallest_first():
    from pipecypher.human_validation import collapse_strata, sample_items

    strata = {
        "g::c1::easy::regular": list(range(10)), "g::c1::easy::focus": list(range(2)),
        "g::c2::hard::regular": list(range(8)), "g::c2::hard::focus": list(range(5)),
        "g::c3::easy::regular": list(range(3)),
    }
    out = collapse_strata(strata, 4)
    assert len(out) == 4
    assert "g::c1::easy::mixed" in out and len(out["g::c1::easy::mixed"]) == 12
    assert "g::c2::hard::focus" in out  # hard focus has the larger boosted size, so it survives
    assert sum(len(v) for v in out.values()) == 28  # nothing dropped

    rows = [{"id": f"r{i}", "graph_profile": "g", "category": f"c{i % 6}", "difficulty_tier": ("easy", "medium", "hard")[i % 3]} for i in range(120)]
    verdicts = {f"r{i}": {"a": True, "b": i % 4 != 0} for i in range(120)}
    items = sample_items(rows, n=8, verdicts=verdicts, max_strata=7)
    cells = {"::".join(item.stratum.split("::")[:3]) for item in items}
    assert len(items) == 8 and len(cells) == 6  # every graph x category x tier cell sampled
    assert sum({item.stratum: item.population for item in items}.values()) == 120
