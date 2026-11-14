from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from pipecypher.config import load_config
from pipecypher.models import (
    ExecutionResult,
    NodeProperty,
    RelationshipPattern,
    RelationshipProperty,
    SchemaSummary,
)
from pipecypher.refresh_audit import (
    RefreshAuditOptions,
    accuracy_misestimate,
    assemble_refreshed_rows,
    atom_matches,
    audit_benchmark_refresh,
    classify_refresh_outcome,
    compare_answers,
    endpoints_match,
    extract_schema_atoms,
    incremental_refresh_plan,
    normalize_bolt_endpoint,
    refresh_table_rows,
    rename_rewrite_cypher,
    static_action_for,
    summarize_refresh_audit,
)
from pipecypher.schema import load_schema
from pipecypher.schema_diff import check_expected_diff, diff_schemas, prune_ghost_schema_entries
from pipecypher.validator import assert_read_only
from scripts import apply_graph_migration as migration_cli
from scripts.audit_benchmark_refresh import (
    emit_full_refresh_config,
    emit_regeneration_configs,
)
from scripts.audit_benchmark_refresh import main as audit_cli_main

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_ROOT / "configs" / "migrations" / "finbench"


# ---------------------------------------------------------------------------
# Fakes


class FakeClient:
    """Read-only-enforcing stand-in for Neo4jCypherClient (no Neo4j needed)."""

    def __init__(self, responder: Callable[[str, dict[str, Any], bool], Any] | dict[str, Any]):
        self.responder = responder
        self.calls: list[tuple[str, dict[str, Any], bool]] = []
        self.closed = False

    def run(self, query, params=None, *, read_only=True, limit_rows=None):
        if read_only:
            assert_read_only(query)
        params = dict(params or {})
        self.calls.append((query, params, read_only))
        if callable(self.responder):
            value = self.responder(query, params, read_only)
        else:
            if query not in self.responder:
                raise AssertionError(f"unexpected query: {query}")
            value = self.responder[query]
        if isinstance(value, ExecutionResult):
            return value
        if isinstance(value, str) and value.startswith("ERROR"):
            return ExecutionResult(success=False, error=value)
        return ExecutionResult(success=True, rows=list(value), latency_ms=1.0)

    def writes(self) -> list[str]:
        return [query for query, _params, read_only in self.calls if not read_only]

    def close(self) -> None:
        self.closed = True


def _small_schema() -> SchemaSummary:
    return SchemaSummary(
        node_properties=[
            NodeProperty("Account", "accountId", "String"),
            NodeProperty("Account", "accountType", "String"),
            NodeProperty("Account", "isBlocked", "Boolean"),
            NodeProperty("Person", "personName", "String"),
            NodeProperty("Person", "isBlocked", "Boolean"),
            NodeProperty("Company", "companyId", "String"),
            NodeProperty("Company", "companyName", "String"),
        ],
        relationship_properties=[
            RelationshipProperty("TRANSFER_TO", "amount", "Double"),
            RelationshipProperty("TRANSFER_TO", "createTime", "DateTime"),
            RelationshipProperty("OWN_ACCOUNT", "createTime", "DateTime"),
            RelationshipProperty("GUARANTEE", "relation", "String"),
        ],
        relationships=[
            RelationshipPattern("Account", "TRANSFER_TO", "Account", 100),
            RelationshipPattern("Person", "OWN_ACCOUNT", "Account", 50),
            RelationshipPattern("Company", "OWN_ACCOUNT", "Account", 40),
            RelationshipPattern("Person", "GUARANTEE", "Person", 10),
            RelationshipPattern("Company", "GUARANTEE", "Company", 5),
        ],
        categorical_properties={"Account.accountType": ["credit card", "debit card"]},
        graph_name="finbench",
    )


def _renamed_schema(before: SchemaSummary) -> SchemaSummary:
    """M1 + M2: TRANSFER_TO -> SENDS_FUNDS and Account.isBlocked -> blocked."""

    data = copy.deepcopy(before.to_dict())
    for rel in data["relationships"]:
        if rel["type"] == "TRANSFER_TO":
            rel["type"] = "SENDS_FUNDS"
    for prop in data["relationship_properties"]:
        if prop["type"] == "TRANSFER_TO":
            prop["type"] = "SENDS_FUNDS"
    for prop in data["node_properties"]:
        if prop["label"] == "Account" and prop["property"] == "isBlocked":
            prop["property"] = "blocked"
    return SchemaSummary.from_dict(data)


# ---------------------------------------------------------------------------
# Atom extraction and matching


def test_extract_schema_atoms_handles_chains_negation_and_aliases():
    query = (
        "MATCH (p:Person {personName: 'Kant (Jr.)'})-[:OWN_ACCOUNT]->(src:Account)"
        "-[t:TRANSFER_TO*1..2]->(dst:Account) WHERE NOT (src)<-[:SIGN_IN]-(:Medium) "
        "AND dst.accountType = 'debit card' WITH src AS acct, sum(t.amount) AS total "
        "RETURN DISTINCT acct.isBlocked AS IsBlocked, duration.between(1, 2) AS d, total"
    )
    atoms = extract_schema_atoms(query)

    assert "pattern:(:Person)-[:OWN_ACCOUNT]->(:Account)" in atoms
    # Second hop of a chain is still resolved to labeled endpoints.
    assert "pattern:(:Account)-[:TRANSFER_TO]->(:Account)" in atoms
    # Incoming arrow is normalized to the stored direction.
    assert "pattern:(:Medium)-[:SIGN_IN]->(:Account)" in atoms
    assert "relprop:TRANSFER_TO.amount" in atoms
    assert "prop:Account.isBlocked" in atoms  # through the WITH alias
    assert "cat:Account.accountType" in atoms
    assert "cat:Person.personName" in atoms
    assert not any("between" in atom for atom in atoms)  # namespaced function call
    assert not any("Jr" in atom for atom in atoms)  # literals are masked


def test_atom_matching_supports_unlabeled_wildcards():
    assert atom_matches(
        "pattern:(:*)-[:OWN_ACCOUNT]->(:Account)", "pattern:(:Company)-[:OWN_ACCOUNT]->(:Account)"
    )
    assert not atom_matches(
        "pattern:(:Person)-[:OWN_ACCOUNT]->(:Account)", "pattern:(:Company)-[:OWN_ACCOUNT]->(:Account)"
    )
    assert atom_matches("prop:*.isBlocked", "prop:Account.isBlocked")
    assert not atom_matches("prop:Person.isBlocked", "prop:Account.isBlocked")


# ---------------------------------------------------------------------------
# Classification


def _ok(rows):
    return ExecutionResult(success=True, rows=rows)


def test_classify_refresh_outcome_covers_every_class():
    rows = [{"id": "a"}, {"id": "b"}]
    cases = {
        "unchanged_answer": dict(original=_ok(rows), migrated=_ok(list(reversed(rows))), new_schema_errors=[]),
        "silently_changed_answer": dict(original=_ok(rows), migrated=_ok(rows[:1]), new_schema_errors=[]),
        "now_empty": dict(original=_ok(rows), migrated=_ok([]), new_schema_errors=[]),
        "execution_error": dict(
            original=_ok(rows), migrated=ExecutionResult(success=False, error="boom"), new_schema_errors=[]
        ),
        "broken_schema": dict(original=_ok(rows), migrated=_ok([]), new_schema_errors=["unknown_relationship"]),
        "original_execution_error": dict(
            original=ExecutionResult(success=False, error="bad"), migrated=_ok(rows), new_schema_errors=[]
        ),
    }
    for expected, kwargs in cases.items():
        assert classify_refresh_outcome(**kwargs)["refresh_class"] == expected

    broken = classify_refresh_outcome(**cases["broken_schema"])
    assert broken["migrated_runtime_outcome"] == "empty"  # Neo4j stays silent
    assert classify_refresh_outcome(
        original=_ok([]), migrated=_ok([]), new_schema_errors=[]
    )["refresh_class"] == "unchanged_answer"


def test_compare_answers_tolerates_float_summation_order_and_row_order():
    original = [{"total": 0.1 + 0.2, "ids": ["b", "a"]}, {"total": 3.0, "ids": []}]
    migrated = [{"total": 3, "ids": []}, {"total": 0.3, "ids": ["a", "b"]}]
    comparison = compare_answers(original, migrated)
    assert comparison["equal"] is True
    assert comparison["ordered_equal"] is False
    assert compare_answers([{"x": 1.0}], [{"x": 1.001}])["equal"] is False


# ---------------------------------------------------------------------------
# Schema diff and rename heuristics


def test_schema_diff_detects_relationship_and_property_renames():
    before = _small_schema()
    diff = diff_schemas(before, _renamed_schema(before))

    assert diff.removed_relationship_types == ["TRANSFER_TO"]
    assert diff.added_relationship_types == ["SENDS_FUNDS"]
    assert "Account.isBlocked" in diff.removed_node_properties
    assert "Person.isBlocked" not in diff.removed_node_properties
    rel = diff.renames("relationship_type")
    assert [(c.before, c.after) for c in rel] == [("TRANSFER_TO", "SENDS_FUNDS")]
    assert rel[0].evidence["endpoint_jaccard"] == 1.0
    prop = diff.renames("node_property")
    assert [(c.scope, c.before, c.after) for c in prop] == [("Account", "isBlocked", "blocked")]
    # Every breaking atom is covered by a confident rename -> rewritable.
    assert set(diff.breaking_atoms()) <= set(diff.renamed_atoms())


def test_rename_heuristic_requires_shared_endpoints():
    before = _small_schema()
    data = copy.deepcopy(before.to_dict())
    data["relationships"] = [r for r in data["relationships"] if r["type"] != "GUARANTEE"]
    data["relationships"].append(
        {"start_label": "Account", "type": "VOUCHES_FOR", "end_label": "Company", "count": 15}
    )
    diff = diff_schemas(before, SchemaSummary.from_dict(data))
    assert diff.removed_relationship_types == ["GUARANTEE"]
    assert diff.renames("relationship_type", min_confidence=0.0) == []


def test_schema_diff_label_split_count_drift_and_ghost_pruning():
    before = _small_schema()
    data = copy.deepcopy(before.to_dict())
    # M3-like: Merchant split off Company, plus a new relationship type.
    data["node_properties"] += [
        {"label": "Merchant", "property": p["property"], "type": p["type"]}
        for p in before.to_dict()["node_properties"]
        if p["label"] == "Company"
    ]
    for rel in data["relationships"]:
        if rel["start_label"] == "Company" and rel["type"] == "OWN_ACCOUNT":
            rel["count"] = 34
    data["relationships"] += [
        {"start_label": "Merchant", "type": "OWN_ACCOUNT", "end_label": "Account", "count": 6},
        {"start_label": "Merchant", "type": "SETTLES_TO", "end_label": "Account", "count": 6},
    ]
    # M4-like: GUARANTEE patterns gone, but relTypeProperties still lists the type.
    data["relationships"] = [r for r in data["relationships"] if r["type"] != "GUARANTEE"]
    after = SchemaSummary.from_dict(data)

    pruned, ghosts = prune_ghost_schema_entries(after)
    assert ghosts == ["relprop:GUARANTEE.relation"]
    assert "GUARANTEE" not in pruned.relationship_types

    diff = diff_schemas(before, after)
    assert diff.added_labels == ["Merchant"]
    assert "GUARANTEE" in diff.removed_relationship_types
    assert "rel:GUARANTEE" in diff.breaking_atoms()
    split = diff.renames("label_split", min_confidence=0.6)
    assert [(c.before, c.after) for c in split] == [("Company", "Merchant")]
    assert "label:Company" in diff.drift_atoms()
    assert "pattern:(:Company)-[:OWN_ACCOUNT]->(:Account)" in diff.drift_atoms()
    assert diff.pruned_ghost_entries == {"after": ["relprop:GUARANTEE.relation"]}

    company_query = "MATCH (c:Company)-[:OWN_ACCOUNT]->(a:Account) RETURN DISTINCT c.companyName AS n"
    person_query = "MATCH (p:Person)-[:OWN_ACCOUNT]->(a:Account) RETURN DISTINCT p.personName AS n"
    guarantee_query = "MATCH (p:Person)-[:GUARANTEE]->(q:Person) RETURN DISTINCT q.personName AS n"
    assert static_action_for(extract_schema_atoms(company_query), diff)[0] == "reexecute"
    assert static_action_for(extract_schema_atoms(person_query), diff)[0] == "reuse"
    assert static_action_for(extract_schema_atoms(guarantee_query), diff)[0] == "regenerate"


def _simulate_migration(schema: dict[str, Any], migration_id: str) -> dict[str, Any]:
    data = copy.deepcopy(schema)
    rels, rel_props, node_props = data["relationships"], data["relationship_properties"], data["node_properties"]
    if migration_id == "m1_rename_transfer_to":
        for item in [*rels, *rel_props]:
            if item["type"] == "TRANSFER_TO":
                item["type"] = "SENDS_FUNDS"
    elif migration_id == "m2_rename_account_isblocked":
        for prop in node_props:
            if prop["label"] == "Account" and prop["property"] == "isBlocked":
                prop["property"] = "blocked"
    elif migration_id == "m3_relabel_merchant_companies":
        node_props += [dict(p, label="Merchant") for p in node_props if p["label"] == "Company"]
        extra = []
        for rel in rels:
            if "Company" in (rel["start_label"], rel["end_label"]):
                moved = max(1, int(rel["count"] * 0.15))
                extra.append(
                    {
                        "start_label": "Merchant" if rel["start_label"] == "Company" else rel["start_label"],
                        "type": rel["type"],
                        "end_label": "Merchant" if rel["end_label"] == "Company" else rel["end_label"],
                        "count": moved,
                    }
                )
                rel["count"] -= moved
        rels += extra
        rels.append({"start_label": "Merchant", "type": "SETTLES_TO", "end_label": "Account", "count": 280})
        rel_props.append({"type": "SETTLES_TO", "property": "createTime", "value_type": "DateTime"})
    elif migration_id == "m4_drop_guarantee":
        data["relationships"] = [r for r in rels if r["type"] != "GUARANTEE"]  # ghosts stay
    elif migration_id in {"d1_delete_transfer_sample", "d2_insert_synthetic_transfers"}:
        factor = 0.9 if migration_id.startswith("d1") else 1.05
        for rel in rels:
            if rel["type"] == "TRANSFER_TO":
                rel["count"] = int(rel["count"] * factor)
    else:  # pragma: no cover - new migrations must add a simulation
        raise AssertionError(f"no simulation for {migration_id}")
    return data


def test_every_migration_metadata_matches_its_simulated_schema_diff():
    before = load_schema(REPO_ROOT / "configs" / "schema_finbench.json")
    specs = migration_cli.list_migrations(MIGRATIONS_DIR)
    assert {spec.id for spec in specs} == {
        "m1_rename_transfer_to",
        "m2_rename_account_isblocked",
        "m3_relabel_merchant_companies",
        "m4_drop_guarantee",
        "d1_delete_transfer_sample",
        "d2_insert_synthetic_transfers",
    }
    for spec in specs:
        after = SchemaSummary.from_dict(_simulate_migration(before.to_dict(), spec.id))
        diff = diff_schemas(before, after)
        assert spec.expected_schema_diff, spec.id
        assert check_expected_diff(diff, spec.expected_schema_diff) == [], spec.id
        if spec.id in {"m1_rename_transfer_to", "m2_rename_account_isblocked"}:
            # Pure renames must be rewrite-grade: every breaking atom has a confident target.
            assert diff.breaking_atoms() and diff.breaking_atoms() <= set(diff.renamed_atoms()), spec.id
        if spec.kind == "data_drift":
            assert not diff.breaking_atoms() and diff.drift_atoms(), spec.id


def test_check_expected_diff_reports_mismatches_and_unknown_keys():
    before = _small_schema()
    diff = diff_schemas(before, before)
    problems = check_expected_diff(
        diff,
        {"removed_relationship_types": ["TRANSFER_TO"], "count_changes": [{"type": "X"}], "typo": 1},
    )
    assert any("unknown expected_schema_diff keys: typo" in p for p in problems)
    assert any("removed_relationship_types missing: TRANSFER_TO" in p for p in problems)
    assert any("count change for X" in p for p in problems)
    assert diff.is_empty()


# ---------------------------------------------------------------------------
# Rename-aware rewrite


def test_rename_rewrite_replaces_tokens_but_not_literals():
    before = _small_schema()
    diff = diff_schemas(before, _renamed_schema(before))
    query = (
        "MATCH (a:Account {accountType: 'TRANSFER_TO isBlocked'})-[t:TRANSFER_TO]->(b:Account) "
        "WHERE b.isBlocked = true RETURN DISTINCT a.accountId AS id, sum(t.amount) AS total"
    )
    rewrite = rename_rewrite_cypher(query, diff)
    assert rewrite.applied
    assert rewrite.cypher == (
        "MATCH (a:Account {accountType: 'TRANSFER_TO isBlocked'})-[t:SENDS_FUNDS]->(b:Account) "
        "WHERE b.blocked = true RETURN DISTINCT a.accountId AS id, sum(t.amount) AS total"
    )
    assert [r["kind"] for r in rewrite.replacements] == ["relationship_type", "node_property"]


def test_rename_rewrite_skips_ambiguous_or_risky_queries():
    before = _small_schema()
    diff = diff_schemas(before, _renamed_schema(before))
    unresolved = rename_rewrite_cypher(
        "MATCH (x)-[:OWN_ACCOUNT]->(y) RETURN DISTINCT y.isBlocked AS b", diff
    )
    assert not unresolved.applied and "unresolved owner" in unresolved.skipped_reason
    backticks = rename_rewrite_cypher("MATCH (a:`Account`)-[:TRANSFER_TO]->(b) RETURN a", diff)
    assert not backticks.applied and backticks.skipped_reason == "backtick-quoted identifiers"
    untouched = rename_rewrite_cypher("MATCH (p:Person) RETURN DISTINCT p.personName AS n", diff)
    assert not untouched.applied and untouched.skipped_reason == "query uses no renamed schema atoms"


# ---------------------------------------------------------------------------
# End-to-end audit with fake graphs


Q_UNCHANGED = "MATCH (p:Person {personName: 'Kant'})-[:OWN_ACCOUNT]->(a:Account) RETURN DISTINCT a.accountId AS AccountId"
Q_TRANSFER = (
    "MATCH (src:Account {accountId: 'A1'})-[t:TRANSFER_TO]->(dst:Account) "
    "RETURN DISTINCT dst.accountId AS AccountId, dst.isBlocked AS IsBlocked"
)
Q_TRANSFER_REWRITTEN = (
    "MATCH (src:Account {accountId: 'A1'})-[t:SENDS_FUNDS]->(dst:Account) "
    "RETURN DISTINCT dst.accountId AS AccountId, dst.blocked AS IsBlocked"
)
Q_COMPANY = "MATCH (c:Company)-[:OWN_ACCOUNT]->(a:Account) RETURN DISTINCT count(DISTINCT c) AS n"
Q_EMPTY = "MATCH (p:Person {personName: 'Gone'})-[:OWN_ACCOUNT]->(a:Account) RETURN DISTINCT a.accountId AS AccountId"
Q_ERROR = "MATCH (p:Person)-[:OWN_ACCOUNT]->(a:Account) RETURN DISTINCT toInteger(p.personName) AS n"
Q_BAD_ORIGINAL = "MATCH (p:Person)-[:OWN_ACCOUNT]->(a:Account) RETURN DISTINCT p.personId / 0 AS n"


def _rows():
    def row(item_id, category, query, family=None):
        return {
            "id": item_id,
            "graph_profile": "finbench",
            "category": category,
            "difficulty": "easy",
            "question": f"question {item_id}",
            "cypher": query,
            "normalized_cypher": query,
            "template": family,
            "template_metadata": {},
            "structural_features": {},
            "result_rows_sample": [],
            "result_row_count_observed": 1,
        }

    return [
        row("pc_unchanged", "simple_retrieval", Q_UNCHANGED),
        row("pc_transfer", "complex_retrieval", Q_TRANSFER),
        row("pc_company", "simple_aggregation", Q_COMPANY),
        row("pc_empty", "simple_retrieval", Q_EMPTY),
        row("pc_error", "complex_aggregation", Q_ERROR),
        row("pc_bad", "complex_aggregation", Q_BAD_ORIGINAL),
        {**row("pc_snb", "simple_retrieval", "MATCH (p:Person) RETURN p"), "graph_profile": "snb"},
    ]


def _graphs():
    original = FakeClient(
        {
            Q_UNCHANGED: [{"AccountId": "A1"}, {"AccountId": "A2"}],
            Q_TRANSFER: [{"AccountId": "A2", "IsBlocked": False}],
            Q_COMPANY: [{"n": 10}],
            Q_EMPTY: [{"AccountId": "A9"}],
            Q_ERROR: [{"n": 1}],
            Q_BAD_ORIGINAL: "ERROR: division by zero",
        }
    )
    migrated = FakeClient(
        {
            Q_UNCHANGED: [{"AccountId": "A2"}, {"AccountId": "A1"}],
            Q_TRANSFER: [],  # Neo4j does not raise on the unknown relationship type
            Q_TRANSFER_REWRITTEN: [{"AccountId": "A2", "IsBlocked": False}],
            Q_COMPANY: [{"n": 8}],
            Q_EMPTY: [],
            Q_ERROR: "ERROR: cannot convert",
            Q_BAD_ORIGINAL: "ERROR: division by zero",
        }
    )
    return original, migrated


def _run_audit(rename_rewrite: bool = True):
    before = _small_schema()
    after = _renamed_schema(before)
    diff = diff_schemas(before, after)
    original, migrated = _graphs()
    options = RefreshAuditOptions(
        migration_id="m1m2_test", graph_profile="finbench", rename_rewrite=rename_rewrite
    )
    items, carried = audit_benchmark_refresh(
        _rows(),
        original_client=original,
        migrated_client=migrated,
        original_schema=before,
        migrated_schema=after,
        options=options,
        diff=diff,
        split_by_id={"pc_transfer": "test", "pc_empty": "test", "pc_error": "train"},
    )
    return items, carried, options, diff, original, migrated


def test_audit_classifies_items_plans_refresh_and_never_writes():
    items, carried, options, diff, original, migrated = _run_audit()
    by_id = {item["id"]: item for item in items}

    assert "pc_snb" not in by_id  # other graph profiles are not audited
    assert by_id["pc_unchanged"]["refresh_class"] == "unchanged_answer"
    assert by_id["pc_unchanged"]["refresh_action"] == "reuse"
    assert by_id["pc_company"]["refresh_class"] == "silently_changed_answer"
    assert by_id["pc_company"]["refresh_action"] == "refresh_answer"
    assert by_id["pc_empty"]["refresh_class"] == "now_empty"
    assert by_id["pc_error"]["refresh_class"] == "execution_error"
    assert by_id["pc_bad"]["refresh_class"] == "original_execution_error"
    assert by_id["pc_bad"]["refresh_action"] == "exclude"

    transfer = by_id["pc_transfer"]
    assert transfer["refresh_class"] == "broken_schema"
    assert transfer["migrated_runtime_outcome"] == "empty"
    assert {e["code"] for e in transfer["new_schema_errors"]} >= {"unknown_relationship", "unknown_property"}
    assert transfer["static_action"] == "rewrite"
    assert transfer["refresh_action"] == "rename_rewrite"
    assert transfer["rename_rewrite"]["answer_preserved"] is True

    assert original.writes() == [] and migrated.writes() == []
    assert all(read_only for _q, _p, read_only in original.calls + migrated.calls)

    carried_by_id = {row["id"]: row for row in carried}
    assert set(carried_by_id) == {"pc_unchanged", "pc_company", "pc_transfer"}
    assert carried_by_id["pc_transfer"]["cypher"] == Q_TRANSFER_REWRITTEN
    assert carried_by_id["pc_transfer"]["refresh"]["judge_recheck_required"] is True
    assert carried_by_id["pc_transfer"]["refresh"]["split"] == "test"
    assert carried_by_id["pc_company"]["result_rows_sample"] == [{"n": 8}]
    assert carried_by_id["pc_company"]["result_row_count_observed"] == 1

    summary = summarize_refresh_audit(items, options=options, diff=diff, n_rows_total=7)
    overall = summary["overall"]
    assert overall["n"] == 6 and overall["n_valid_original"] == 5
    assert overall["counts"]["broken_schema"] == 1
    assert overall["rates"]["unchanged_answer"] == pytest.approx(0.2)
    assert summary["broken_schema_runtime_outcomes"] == {"empty": 1}
    assert summary["rename_rewrite"]["applied"] == 1

    plan = summary["incremental_plan"]
    assert plan["actions"] == {
        "reuse": 1,
        "refresh_answer": 1,
        "rename_rewrite": 1,
        "regenerate": 2,
        "exclude": 1,
    }
    assert plan["regeneration_targets"] == {"complex_aggregation": 1, "simple_retrieval": 1}
    assert plan["regeneration_targets_by_split"]["simple_retrieval"] == {"test": 1}
    assert "complex_retrieval" in plan["categories_reusable"]
    assert plan["carried_forward_fraction"] == pytest.approx(3 / 5)

    static = summary["static_impact"]
    # Pure data drift (pc_company, pc_empty, pc_error) is invisible to schema atoms here.
    assert static["broken_schema_recall"] == 1.0
    assert static["missed_by_static"] == 3


def test_audit_without_rewrite_regenerates_broken_items():
    items, carried, *_ = _run_audit(rename_rewrite=False)
    transfer = next(item for item in items if item["id"] == "pc_transfer")
    assert transfer["refresh_action"] == "regenerate"
    assert "pc_transfer" not in {row["id"] for row in carried}


def test_incremental_plan_marks_fully_reusable_categories():
    items = [
        {"id": "1", "category": "a", "refresh_action": "reuse", "refresh_class": "unchanged_answer", "template_family": "f"},
        {"id": "2", "category": "b", "refresh_action": "regenerate", "refresh_class": "now_empty", "template_family": "g", "split": "dev"},
    ]
    plan = incremental_refresh_plan(items)
    assert plan["categories_reusable"] == ["a"]
    assert plan["categories_needing_regeneration"] == ["b"]
    assert plan["template_families_needing_regeneration"] == 1
    assert plan["generation_load_proxy"]["incremental_to_full_ratio"] == pytest.approx(0.5)


def test_refresh_table_refuses_partial_summaries():
    items, _carried, options, diff, *_ = _run_audit()
    summary = summarize_refresh_audit(items, options=options, diff=diff, partial=True)
    with pytest.raises(ValueError, match="partial"):
        refresh_table_rows([summary])
    rows = refresh_table_rows(
        [summary], allow_partial=True, timings={"m1m2_test": {"full_refresh_gpu_hours": 2.5}}
    )
    assert rows[0]["pct_broken_schema"] == pytest.approx(20.0)
    assert rows[0]["full_refresh_gpu_hours"] == 2.5


# ---------------------------------------------------------------------------
# Accuracy misestimate


def test_accuracy_misestimate_exposes_stale_reference_credit():
    stale = _rows()[:3]
    refreshed = [
        {**stale[0]},
        {**stale[1], "cypher": Q_TRANSFER_REWRITTEN, "normalized_cypher": Q_TRANSFER_REWRITTEN, "refresh": {"action": "rename_rewrite"}},
    ]  # pc_company is retired
    predictions = [
        {"id": "pc_unchanged", "predicted_cypher": Q_UNCHANGED},
        # A model prompted with the stale schema keeps TRANSFER_TO: empty on the migrated graph.
        {"id": "pc_transfer", "predicted_cypher": Q_TRANSFER},
        {"id": "pc_company", "predicted_cypher": Q_COMPANY},
        {"id": "pc_missing", "predicted_cypher": Q_UNCHANGED},
        {"id": "pc_write", "predicted_cypher": "MATCH (n) DETACH DELETE n"},
    ]
    stale.append({**stale[0], "id": "pc_write"})
    _original, migrated = _graphs()
    summary, rows = accuracy_misestimate(
        predictions, stale, refreshed, migrated_clients={"finbench": migrated}
    )

    by_id = {row["id"]: row for row in rows}
    assert by_id["pc_transfer"]["stale_correct"] is True  # empty == empty
    assert by_id["pc_transfer"]["refreshed_correct"] is False
    assert by_id["pc_write"]["prediction_executed"] is False
    assert migrated.writes() == []
    assert summary["n_unknown_id"] == 1
    assert summary["stale_correct_on_empty_gold"] == 1
    assert summary["paired"]["n"] == 2
    assert summary["paired"]["stale_accuracy"] == pytest.approx(1.0)
    assert summary["paired"]["refreshed_accuracy"] == pytest.approx(0.5)
    assert summary["paired"]["misestimate_pp"] == pytest.approx(50.0)
    assert summary["paired"]["stale_only_correct"] == 1
    assert summary["n_retired"] == 2  # pc_company and pc_write


# ---------------------------------------------------------------------------
# Migration script: metadata, determinism, and safety


def test_migration_metadata_loads_strictly_and_reads_are_read_only():
    specs = migration_cli.list_migrations(MIGRATIONS_DIR)
    assert len(specs) == 6
    for spec in specs:
        assert spec.statements
        assert spec.expected_benchmark_impact
        for check in [*spec.preconditions, *spec.postconditions]:
            assert_read_only(check["query"])
        if spec.selection:
            assert_read_only(spec.selection["query"])
        if spec.generator:
            for key in ("accounts_query", "stats_query", "vocab_query"):
                assert_read_only(spec.generator[key])
        # The write statements really are writes (the read-only guard would block them).
        assert any(not migration_cli_is_read_only(s) for s in spec.statements)


def migration_cli_is_read_only(statement: str) -> bool:
    try:
        assert_read_only(statement)
        return True
    except ValueError:
        return False


def test_migration_metadata_rejects_unknown_keys(tmp_path: Path):
    (tmp_path / "x.cypher").write_text("MATCH (n) DETACH DELETE n;", encoding="utf-8")
    meta = {
        "id": "x",
        "graph_profile": "finbench",
        "kind": "schema_migration",
        "description": "d",
        "cypher_file": "x.cypher",
        "batch_sise": 10,
    }
    path = tmp_path / "x.meta.yaml"
    path.write_text(yaml.safe_dump(meta), encoding="utf-8")
    with pytest.raises(migration_cli.MigrationSpecError, match="batch_sise"):
        migration_cli.load_migration(path)


def test_split_cypher_statements_ignores_comments_and_quoted_semicolons():
    text = "// header; not a split\nMATCH (n {name: 'a;b'}) RETURN n;\n\n// tail\nMATCH (m) RETURN m"
    assert migration_cli.split_cypher_statements(text) == [
        "MATCH (n {name: 'a;b'}) RETURN n",
        "MATCH (m) RETURN m",
    ]


def test_hash_selection_is_deterministic_and_order_independent():
    rows = [{"src": f"A{i}", "dst": f"B{i}", "amount": float(i)} for i in range(2000)]
    first = migration_cli.select_rows(rows, key_fields=["src", "dst", "amount"], fraction=0.1, salt="s")
    second = migration_cli.select_rows(
        list(reversed(rows)), key_fields=["src", "dst", "amount"], fraction=0.1, salt="s"
    )
    other_salt = migration_cli.select_rows(rows, key_fields=["src", "dst", "amount"], fraction=0.1, salt="t")
    assert first == second
    assert migration_cli.rows_digest(first) == migration_cli.rows_digest(second)
    assert 150 <= len(first) <= 250
    assert first != other_salt


def test_synthetic_transfer_generator_is_deterministic():
    responses = {
        "accounts": [{"accountId": f"A{i}"} for i in range(50)],
        "stats": [{"n": 200, "max_create_time": "2022-12-31T00:00:00Z"}],
        "vocab": [{"payType": "card", "goodsType": "food"}, {"payType": "wire", "goodsType": "car"}],
    }
    spec = {
        "accounts_query": "accounts",
        "stats_query": "stats",
        "vocab_query": "vocab",
        "fraction_of_existing": 0.05,
        "salt": "salt",
        "comment_marker": "marker",
    }
    first, info = migration_cli.generate_synthetic_transfers(lambda q: responses[q], spec)
    second, _ = migration_cli.generate_synthetic_transfers(lambda q: responses[q], spec)
    assert first == second and len(first) == 10 == info["generated"]
    assert all(row["src"] != row["dst"] for row in first)
    assert [row["offsetMinutes"] for row in first] == list(range(1, 11))
    assert {row["comment"] for row in first} == {"marker"}


def test_target_safety_refuses_protected_graphs_and_bad_confirmation():
    protected, _notes = migration_cli.load_protected_endpoints(
        str(REPO_ROOT / "configs" / "finbench_full.yaml"),
        [str(REPO_ROOT / "configs" / "snb_full.yaml")],
    )
    refuse = migration_cli.evaluate_target_safety(
        target_uri="neo4j://127.0.0.1:7687",
        target_database="neo4j",
        confirm_copy_database="neo4j",
        protected=protected,
    )
    assert not refuse.ok and "finbench_full.yaml" in refuse.errors[0]
    snb = migration_cli.evaluate_target_safety(
        target_uri="bolt://localhost:7688",
        target_database="neo4j",
        confirm_copy_database="neo4j",
        protected=protected,
    )
    assert not snb.ok
    override = migration_cli.evaluate_target_safety(
        target_uri="bolt://localhost:7687",
        target_database="neo4j",
        confirm_copy_database="neo4j",
        protected=protected,
        allow_override=True,
    )
    assert override.ok and override.warnings
    mismatch = migration_cli.evaluate_target_safety(
        target_uri="bolt://localhost:7697",
        target_database="neo4j",
        confirm_copy_database="finbench_copy",
        protected=protected,
        allow_override=True,
    )
    assert not mismatch.ok  # confirmation mismatch is never overridable
    copy_target = migration_cli.evaluate_target_safety(
        target_uri="bolt://localhost:7697",
        target_database="neo4j",
        confirm_copy_database="neo4j",
        protected=protected,
    )
    assert copy_target.ok


def test_endpoint_normalization():
    assert normalize_bolt_endpoint("bolt://127.0.0.1") == ("localhost", 7687)
    assert endpoints_match("neo4j://localhost:7687", "bolt://0.0.0.0:7687")
    assert not endpoints_match("bolt://localhost:7687", "bolt://localhost:7697")


class FakeGraph:
    """Tiny mutable graph state answering the M4 migration queries."""

    def __init__(self, guarantee: int, store_id: str):
        self.guarantee = guarantee
        self.total = 100 + guarantee
        self.store_id = store_id

    def respond(self, query: str, params: dict[str, Any], read_only: bool):
        if "db.info()" in query:
            return [{"id": self.store_id, "name": "neo4j", "creationDate": "2026-01-01"}]
        if query == migration_cli.NODE_COUNT_QUERY:
            return [{"n": 42}]
        if "DELETE g" in query:
            assert not read_only
            self.total -= self.guarantee
            self.guarantee = 0
            return []
        if "[r:GUARANTEE]" in query:
            return [{"n": self.guarantee}]
        if "MATCH ()-[r]->()" in query:
            return [{"n": self.total}]
        raise AssertionError(f"unexpected query: {query}")


def _factory(graphs: dict[int, FakeGraph], created: list[tuple[str, FakeClient]]):
    def factory(uri, user, password, database, timeout):
        port = normalize_bolt_endpoint(uri)[1]
        client = FakeClient(graphs[port].respond)
        created.append((uri, client))
        return client

    return factory


def _base_args(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "--migration",
        "m4_drop_guarantee",
        "--target-bolt-uri",
        "bolt://localhost:7697",
        "--confirm-copy-database",
        "neo4j",
        "--ledger-out",
        str(tmp_path / "ledger.json"),
        *extra,
    ]


def test_migration_cli_dry_run_by_default_opens_no_connection(tmp_path: Path):
    def exploding_factory(*_args):
        raise AssertionError("dry run must not connect")

    assert migration_cli.main(_base_args(tmp_path), client_factory=exploding_factory) == 0
    assert not (tmp_path / "ledger.json").exists()


def test_migration_cli_refuses_primary_without_connecting(tmp_path: Path):
    def exploding_factory(*_args):
        raise AssertionError("refused runs must not connect")

    args = [
        "--migration",
        "m4_drop_guarantee",
        "--target-bolt-uri",
        "bolt://localhost:7687",
        "--confirm-copy-database",
        "neo4j",
        "--apply",
    ]
    assert migration_cli.main(args, client_factory=exploding_factory) == migration_cli.EXIT_SAFETY


def test_migration_cli_applies_to_copy_and_writes_ledger(tmp_path: Path):
    graphs = {
        7697: FakeGraph(12, "copy-store"),
        7687: FakeGraph(12, "primary-store"),
        7688: FakeGraph(0, "snb-store"),
        7689: FakeGraph(0, "icij-store"),
    }
    created: list[tuple[str, FakeClient]] = []
    code = migration_cli.main(_base_args(tmp_path, "--apply"), client_factory=_factory(graphs, created))

    assert code == migration_cli.EXIT_OK
    assert graphs[7697].guarantee == 0 and graphs[7687].guarantee == 12  # primary untouched
    for uri, client in created:
        if normalize_bolt_endpoint(uri)[1] != 7697:
            assert client.writes() == []
    ledger = json.loads((tmp_path / "ledger.json").read_text(encoding="utf-8"))
    assert ledger["status"] == "applied"
    assert ledger["target_endpoint"] == "localhost:7697"
    assert ledger["target_db_info"]["id"] == "copy-store"
    assert {c["name"]: c["passed"] for c in ledger["postconditions"]} == {
        "guarantee_after": True,
        "relationships_after": True,
    }
    assert "password" not in json.dumps(ledger)


def test_migration_cli_inspect_target_never_writes(tmp_path: Path):
    graphs = {7697: FakeGraph(12, "copy-store"), 7687: FakeGraph(12, "primary-store")}
    graphs[7688] = graphs[7689] = FakeGraph(0, "other")
    created: list[tuple[str, FakeClient]] = []
    code = migration_cli.main(
        _base_args(tmp_path, "--inspect-target"), client_factory=_factory(graphs, created)
    )
    assert code == migration_cli.EXIT_OK
    assert all(client.writes() == [] for _uri, client in created)
    assert json.loads((tmp_path / "ledger.json").read_text(encoding="utf-8"))["status"] == "planned"


def test_migration_cli_refuses_when_store_id_matches_protected_graph(tmp_path: Path):
    same = FakeGraph(12, "primary-store")
    graphs = {7697: same, 7687: FakeGraph(12, "primary-store"), 7688: same, 7689: same}
    created: list[tuple[str, FakeClient]] = []
    code = migration_cli.main(_base_args(tmp_path, "--apply"), client_factory=_factory(graphs, created))
    assert code == migration_cli.EXIT_SAFETY
    assert all(client.writes() == [] for _uri, client in created)
    assert json.loads((tmp_path / "ledger.json").read_text(encoding="utf-8"))["status"] == "identity_refused"


def test_migration_cli_precondition_failure_blocks_writes(tmp_path: Path):
    graphs = {7697: FakeGraph(0, "copy-store"), 7687: FakeGraph(12, "primary-store")}
    graphs[7688] = graphs[7689] = FakeGraph(0, "other")
    created: list[tuple[str, FakeClient]] = []
    code = migration_cli.main(_base_args(tmp_path, "--apply"), client_factory=_factory(graphs, created))
    assert code == migration_cli.EXIT_PRECONDITION
    assert all(client.writes() == [] for _uri, client in created)


# ---------------------------------------------------------------------------
# Configs


def test_copy_run_config_is_strict_valid_and_not_a_protected_endpoint():
    copy_cfg = load_config(MIGRATIONS_DIR / "finbench_copy.run.yaml", strict=True, validate=True)
    primary = load_config(REPO_ROOT / "configs" / "finbench_full.yaml", strict=True, validate=True)
    assert copy_cfg.generation.graph_profile == "finbench"
    assert not endpoints_match(copy_cfg.neo4j.uri, primary.neo4j.uri)


def test_emit_regeneration_configs_are_strict_valid(tmp_path: Path):
    seen = tmp_path / "seen.jsonl"
    seen.write_text("", encoding="utf-8")
    emitted = emit_regeneration_configs(
        base_config=str(MIGRATIONS_DIR / "finbench_copy.run.yaml"),
        migrated_schema="artifacts/refresh/m1/schema_after.json",
        targets={"negation_difference": 7, "ranking_topk": 3},
        out_dir=tmp_path / "regen",
        migration_id="m1_rename_transfer_to",
        seen_records=seen,
        random_seed=13,
    )
    assert [e["category"] for e in emitted] == ["negation_difference", "ranking_topk"]
    cfg = load_config(emitted[0]["config"], strict=True, validate=True)
    assert cfg.generation.categories == ["negation_difference"]
    assert cfg.generation.target_per_category == 7
    assert cfg.paths.schema_path == "artifacts/refresh/m1/schema_after.json"
    script = (tmp_path / "regen" / "regenerate.sh").read_text(encoding="utf-8")
    assert "--seen-records" in script and "--random-seed 13" in script


def test_generated_refresh_scripts_are_valid_bash(tmp_path: Path):
    import shutil
    import subprocess

    full = emit_full_refresh_config(
        base_config=str(MIGRATIONS_DIR / "finbench_copy.run.yaml"),
        migrated_schema="artifacts/refresh/m1/schema_after.json",
        categories=["negation_difference", "ranking_topk"],
        target_per_category=250,
        out_dir=tmp_path,
        migration_id="m1_rename_transfer_to",
        random_seed=13,
    )
    cfg = load_config(full["config"], strict=True, validate=True)
    assert cfg.generation.target_per_category == 250
    seen = tmp_path / "seen.jsonl"
    seen.write_text("", encoding="utf-8")
    emit_regeneration_configs(
        base_config=str(MIGRATIONS_DIR / "finbench_copy.run.yaml"),
        migrated_schema="artifacts/refresh/m1/schema_after.json",
        targets={"ranking_topk": 3},
        out_dir=tmp_path,
        migration_id="m1_rename_transfer_to",
        seen_records=seen,
        random_seed=13,
    )
    bash = shutil.which("bash")
    if bash is None:  # pragma: no cover - bash is present on CI and dev machines
        pytest.skip("bash not available")
    for name in ("full_refresh.sh", "regenerate.sh"):
        script = tmp_path / name
        assert "PIPE_CYPHER_NEO4J_URI" in script.read_text(encoding="utf-8")
        subprocess.run([bash, "-n", str(script)], check=True)


def test_assemble_refreshed_rows_fills_split_deficits_deterministically():
    carried = [
        {"id": "c1", "category": "a", "refresh": {"split": "test"}},
        {"id": "c2", "category": "b", "refresh": {"split": "train"}},
    ]
    regenerated = [
        {"id": "n3", "category": "a"},
        {"id": "n1", "category": "a"},
        {"id": "n2", "category": "a"},
        {"id": "c1", "category": "a"},  # duplicate of a carried item
        {"id": "m1", "category": "b"},
    ]
    splits, report = assemble_refreshed_rows(
        carried, regenerated, {"a": {"train": 1, "test": 1}, "b": {"dev": 2}}
    )
    assert [r["id"] for r in splits["test"]] == ["c1", "n1"]  # held-out split filled first
    assert [r["id"] for r in splits["train"]] == ["c2", "n2"]
    assert [r["id"] for r in splits["dev"]] == ["m1"]
    assert report["surplus_regenerated"] == {"a": 1}
    assert report["unfilled_deficits"] == {"b": {"dev": 1}}
    assert report["regenerated_duplicates_of_carried"] == 1
    assert report["complete"] is False


def test_assemble_cli_keeps_other_graphs_and_refuses_unfilled_deficits(tmp_path: Path):
    original = tmp_path / "orig"
    original.mkdir()
    rows = [
        {"id": "f1", "graph_profile": "finbench", "category": "a"},
        {"id": "f2", "graph_profile": "finbench", "category": "a"},
        {"id": "s1", "graph_profile": "snb", "category": "a"},
    ]
    (original / "all.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    (original / "test.jsonl").write_text(json.dumps(rows[1]) + "\n" + json.dumps(rows[2]) + "\n", encoding="utf-8")
    (original / "train.jsonl").write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    summary = {
        "migration_id": "m1",
        "graph_profile": "finbench",
        "partial": False,
        "incremental_plan": {"regeneration_targets_by_split": {"a": {"test": 1}}},
    }
    (audit_dir / "refresh_audit_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    carried = [{**rows[0], "refresh": {"split": "train", "action": "reuse"}}]
    (audit_dir / "carried_forward_export.jsonl").write_text(json.dumps(carried[0]) + "\n", encoding="utf-8")
    regen = tmp_path / "regen.jsonl"
    regen.write_text(json.dumps({"id": "f9", "graph_profile": "finbench", "category": "a"}) + "\n", encoding="utf-8")
    out = tmp_path / "out"

    code = audit_cli_main(
        [
            "assemble",
            "--original-benchmark", str(original),
            "--audit-dir", str(audit_dir),
            "--regenerated-export", str(regen),
            "--output-dir", str(out),
        ]
    )
    assert code == 0
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["split_counts"] == {"test": 2, "train": 1}
    assert manifest["passthrough_other_graphs"] == 1
    test_ids = [json.loads(line)["id"] for line in (out / "test.jsonl").read_text().splitlines()]
    assert test_ids == ["f9", "s1"]

    code = audit_cli_main(
        [
            "assemble",
            "--original-benchmark", str(original),
            "--audit-dir", str(audit_dir),
            "--output-dir", str(tmp_path / "out2"),
        ]
    )
    assert code == 1  # nothing regenerated -> unfilled test deficit is an error


def test_audit_cli_end_to_end_with_fake_graphs(tmp_path: Path, monkeypatch):
    from pipecypher.schema import save_schema
    from scripts import audit_benchmark_refresh as audit_cli

    before = _small_schema()
    save_schema(before, tmp_path / "before.json")
    save_schema(_renamed_schema(before), tmp_path / "after.json")
    bench = tmp_path / "bench"
    bench.mkdir()
    rows = _rows()
    (bench / "all.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    (bench / "test.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows if r["id"] in {"pc_transfer", "pc_empty"}) + "\n",
        encoding="utf-8",
    )
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text(
        json.dumps({"id": "pc_transfer", "predicted_cypher": Q_TRANSFER}) + "\n", encoding="utf-8"
    )
    original, migrated = _graphs()
    clients = {"original": original, "migrated": migrated}

    def fake_client_for(config_path: str):
        key = "migrated" if "finbench_copy" in config_path else "original"
        return load_config(config_path, strict=True, validate=True), clients[key]

    monkeypatch.setattr(audit_cli, "_client_for", fake_client_for)
    out = tmp_path / "audit"
    code = audit_cli.main(
        [
            "audit",
            "--benchmark", str(bench),
            "--migration-id", "m1m2_test",
            "--graph-profile", "finbench",
            "--original-config", str(REPO_ROOT / "configs" / "finbench_full.yaml"),
            "--migrated-config", str(MIGRATIONS_DIR / "finbench_copy.run.yaml"),
            "--original-schema", str(tmp_path / "before.json"),
            "--migrated-schema", str(tmp_path / "after.json"),
            "--output-dir", str(out),
            "--predictions", str(predictions),
            "--regeneration-base-config", str(MIGRATIONS_DIR / "finbench_copy.run.yaml"),
        ]
    )
    assert code == 0
    summary = json.loads((out / "refresh_audit_summary.json").read_text(encoding="utf-8"))
    assert summary["partial"] is False
    assert summary["overall"]["counts"]["broken_schema"] == 1
    assert summary["provenance"]["migrated_endpoint"] == "localhost:7697"
    assert summary["by_split"]["test"]["n"] == 2
    assert summary["accuracy_misestimate"]["paired"]["misestimate_pp"] == pytest.approx(100.0)
    assert {e["category"] for e in summary["regeneration_configs"]} == {"simple_retrieval", "complex_aggregation"}
    assert summary["full_refresh_config"]["target_per_category"] == 2
    assert (out / "carried_forward_export.jsonl").exists()
    seen = [json.loads(line) for line in (out / "reusable_seen_records.jsonl").read_text().splitlines()]
    assert all(row["accepted"] for row in seen) and len(seen) == 3
    items_text = (out / "refresh_audit_items.jsonl").read_text(encoding="utf-8")
    assert "question pc_" not in items_text  # item log carries ids, not question text
    assert original.writes() == [] and migrated.writes() == []

    table_md = tmp_path / "table.md"
    assert audit_cli.main(
        ["table", "--summaries", str(out / "refresh_audit_summary.json"), "--output-md", str(table_md)]
    ) == 0
    assert "m1m2_test" in table_md.read_text(encoding="utf-8")


def test_audit_cli_refuses_identical_original_and_migrated_graph(tmp_path: Path, monkeypatch):
    from scripts import audit_benchmark_refresh as audit_cli

    monkeypatch.setattr(
        audit_cli,
        "_client_for",
        lambda path: (load_config(path, strict=True, validate=True), FakeClient({})),
    )
    primary = str(REPO_ROOT / "configs" / "finbench_full.yaml")
    with pytest.raises(SystemExit, match="same graph"):
        audit_cli.main(
            [
                "audit",
                "--benchmark", str(tmp_path),
                "--migration-id", "x",
                "--original-config", primary,
                "--migrated-config", primary,
            ]
        )
