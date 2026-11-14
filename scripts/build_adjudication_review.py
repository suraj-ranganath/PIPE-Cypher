#!/usr/bin/env python3
"""Evidence for resolving human-label disagreements (PRIVATE/internal).

For each shared item the two annotators labeled differently, runs the
reference query and a proposed fix on the live graph (read-only, no row cap)
and writes ``adjudication.json`` for the review view of the labeling page:
both annotators' labels and notes, the conventions in question, the fix, how
the two answers differ, and a few diagnostic counts.

The fixes are proposals written to test whether a flaw changes the answer
("wrong") or not ("minor"). They are evidence for the annotators' discussion,
not labels.

Example:
  python scripts/build_adjudication_review.py --sample-dir artifacts/human_validation_v3/v3d \
      --labels artifacts/human_validation_v3/v3d/db_dump_notes_update
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase

BOLT = {"finbench": "bolt://127.0.0.1:17687", "snb": "bolt://127.0.0.1:17688"}
AUTH = ("neo4j", "password")
SAMPLE = 8

FIXES: dict[str, dict[str, Any]] = {
    "pc_4336f86aed7d3d9f": {
        "conventions": ["C10 Self-matches", "C13 One reading"],
        "concern": "The friend's 'knows nobody living in China' check also counts the named person. If that person lives in China, every friend fails the check.",
        "fix_note": "Leave the named person out of the 'knows nobody in China' check.",
        "fix": "MATCH (p:Person {id: 4398046511274})-[:KNOWS]-(f:Person) WHERE NOT EXISTS { MATCH (f)-[:KNOWS]-(o:Person)-[:IS_LOCATED_IN]->(:City)-[:IS_PART_OF]->(:Country {name: 'China'}) WHERE o <> p } RETURN count(f) > 0 AS result",
        "diagnostics": [
            ("Where the named person lives", "MATCH (p:Person {id: 4398046511274})-[:IS_LOCATED_IN]->(c:City)-[:IS_PART_OF]->(co:Country) RETURN c.name AS city, co.name AS country"),
            ("Friends of the named person", "MATCH (p:Person {id: 4398046511274})-[:KNOWS]-(f:Person) RETURN count(DISTINCT f) AS friends"),
        ],
    },
    "pc_30f9fc75774b617c": {
        "conventions": ["C2 Direction"],
        "concern": "Both labeled the reference wrong (it counts only accounts that sent transfers to the named account). The open point is whether the question is clear: 'connected by' is a neutral verb.",
        "fix_note": "Count accounts linked in either direction, as C2 reads a neutral verb.",
        "fix": "MATCH (s:Account)-[:TRANSFER_TO]-(e:Account {accountId: '132011764077299163'}) RETURN COUNT(DISTINCT s) AS AccountCount",
        "diagnostics": [
            ("Accounts the named account sent transfers to", "MATCH (e:Account {accountId: '132011764077299163'})-[:TRANSFER_TO]->(t:Account) RETURN count(DISTINCT t) AS receivers"),
            ("Accounts that sent transfers to the named account", "MATCH (s:Account)-[:TRANSFER_TO]->(e:Account {accountId: '132011764077299163'}) RETURN count(DISTINCT s) AS senders"),
        ],
    },
    "pc_02f90111aabc0853": {
        "conventions": ["C8 Paths"],
        "ordered": True,
        "concern": "In one MATCH, Cypher never reuses a relationship. The 1-3 hop KNOWS path and the KNOWS edge from the person to the moderator therefore cannot share an edge, which can drop forums when the moderator is on the path.",
        "fix_note": "Find the people in a first MATCH, then the moderator and forum in a second MATCH, so the edges may overlap.",
        "fix": "MATCH (p:Person {id: 6597069766841})-[:KNOWS*1..3]-(other:Person) WHERE other <> p WITH DISTINCT other MATCH (other)-[:KNOWS]-(mod:Person)<-[:HAS_MODERATOR]-(f:Forum)-[:HAS_MEMBER]->(other) RETURN other.id AS personId, COUNT(DISTINCT f) AS forumCount ORDER BY forumCount DESC, personId ASC LIMIT 5",
        "full_pair": (
            "MATCH (p:Person {id: 6597069766841})-[:KNOWS*1..3]-(other:Person)-[:KNOWS]-(mod:Person)<-[:HAS_MODERATOR]-(f:Forum)-[:HAS_MEMBER]->(other) WHERE other <> p RETURN other.id AS personId, COUNT(DISTINCT f) AS forumCount",
            "MATCH (p:Person {id: 6597069766841})-[:KNOWS*1..3]-(other:Person) WHERE other <> p WITH DISTINCT other MATCH (other)-[:KNOWS]-(mod:Person)<-[:HAS_MODERATOR]-(f:Forum)-[:HAS_MEMBER]->(other) RETURN other.id AS personId, COUNT(DISTINCT f) AS forumCount",
        ),
        "diagnostics": [],
    },
    "pc_4abe21902cf04b54": {
        "conventions": ["C10 Self-matches"],
        "concern": "The question rules out transfers 'from another account', but the query rules out every incoming transfer, including an account's transfers to itself.",
        "fix_note": "Rule out only incoming transfers from a different account.",
        "fix": "MATCH (a:Account) WHERE a.isBlocked = false AND NOT EXISTS { MATCH (o:Account)-[:TRANSFER_TO]->(a) WHERE o <> a } RETURN DISTINCT a.accountId AS accountId",
        "diagnostics": [
            ("Self-transfers in the whole graph", "MATCH (a:Account)-[t:TRANSFER_TO]->(a) RETURN count(t) AS selfTransfers, count(DISTINCT a) AS accounts"),
            ("Unblocked accounts whose only incoming transfers are to themselves", "MATCH (a:Account) WHERE a.isBlocked = false AND (a)-[:TRANSFER_TO]->(a) AND NOT EXISTS { MATCH (o:Account)-[:TRANSFER_TO]->(a) WHERE o <> a } RETURN count(a) AS accounts"),
        ],
    },
    "pc_c59da28f4a5a0efa": {
        "conventions": ["C10 Self-matches"],
        "concern": "The question rules out transfers 'from any other account', but the query rules out every incoming transfer, including an account's transfers to itself.",
        "fix_note": "Rule out only incoming transfers from a different account.",
        "fix": "MATCH (p:Person {personId: '19791209300686'})-[:OWN_ACCOUNT]->(a:Account) WHERE NOT EXISTS { MATCH (o:Account)-[:TRANSFER_TO]->(a) WHERE o <> a } RETURN DISTINCT a.accountId AS accountId, a.accountType AS accountType, a.createTime AS createTime",
        "diagnostics": [
            ("The person's accounts: self-transfers and incoming transfers from others", "MATCH (p:Person {personId: '19791209300686'})-[:OWN_ACCOUNT]->(a:Account) OPTIONAL MATCH (a)-[s:TRANSFER_TO]->(a) WITH a, count(s) AS selfTransfers OPTIONAL MATCH (o:Account)-[t:TRANSFER_TO]->(a) WHERE o <> a RETURN a.accountId AS accountId, selfTransfers, count(t) AS fromOtherAccounts ORDER BY accountId"),
        ],
    },
    "pc_c8ae16a5acf229f4": {
        "conventions": ["C12 Grouping", "C13 One reading"],
        "interpretive": "Execution cannot settle this one: the two queries answer two readings of the question. Decide which reading the question means.",
        "concern": "The reference averages over every account of a type, including accounts with no outgoing transfers (they count as 0). The other reading averages only over accounts that made at least one transfer.",
        "fix_note": "Average only over accounts with at least one outgoing transfer.",
        "fix": "MATCH (a:Account)-[t:TRANSFER_TO]->() WITH a.accountType AS accountType, a, count(t) AS outTransfers RETURN accountType, avg(outTransfers) AS avgOutgoingTransfers ORDER BY accountType",
        "diagnostics": [
            ("Accounts per type, and how many made no outgoing transfer", "MATCH (a:Account) OPTIONAL MATCH (a)-[t:TRANSFER_TO]->() WITH a.accountType AS accountType, a, count(t) AS n RETURN accountType, count(a) AS accounts, sum(CASE WHEN n = 0 THEN 1 ELSE 0 END) AS withNoOutgoing ORDER BY accountType"),
        ],
    },
    "pc_96aadbfd62ae1c48": {
        "conventions": ["C12 Grouping", "C6 Columns"],
        "concern": "The query groups by forum title and moderator name instead of by forum. Two forums with the same title and moderator name would be merged into one row with a combined member count.",
        "fix_note": "Group by the forum itself (its id), then compare on title, moderator name and member count.",
        "fix": "MATCH (f:Forum)-[:HAS_MODERATOR]->(mod:Person)-[:IS_LOCATED_IN]->(:City)-[:IS_PART_OF]->(:Country {name: 'China'}) OPTIONAL MATCH (f)-[:HAS_MEMBER]->(m:Person) RETURN f.id AS forumId, f.title AS forumTitle, mod.firstName + ' ' + mod.lastName AS moderatorName, COUNT(DISTINCT m) AS memberCount",
        "compare_on": ["forumTitle", "moderatorName", "memberCount"],
        "diagnostics": [
            ("Title and moderator-name pairs shared by more than one forum", "MATCH (f:Forum)-[:HAS_MODERATOR]->(mod:Person)-[:IS_LOCATED_IN]->(:City)-[:IS_PART_OF]->(:Country {name: 'China'}) WITH f.title AS title, mod.firstName + ' ' + mod.lastName AS name, count(DISTINCT f) AS forums WHERE forums > 1 RETURN count(*) AS sharedPairs, sum(forums) AS forumsInvolved"),
        ],
    },
    "pc_702315dac5e12517": {
        "conventions": ["C10 Self-matches"],
        "concern": "Both labeled the reference wrong (nothing keeps the three companies distinct). The open point is whether the question is clear: 'the other' and 'a third company' imply three different companies.",
        "fix_note": "Require the guarantor, the guaranteed company, and the third company to be three different companies.",
        "fix": "MATCH (c1:Company)-[g:GUARANTEE]->(c2:Company)-[i:INVEST]->(c3:Company) WHERE i.createTime > g.createTime AND c1 <> c2 AND c3 <> c1 AND c3 <> c2 RETURN DISTINCT c1.companyId AS guarantorCompanyId, c2.companyId AS investorCompanyId",
        "diagnostics": [
            ("Self-guarantees (a company guaranteeing itself)", "MATCH (c:Company)-[g:GUARANTEE]->(c) RETURN count(g) AS selfGuarantees"),
            ("Matches where the 'third' company is one of the first two", "MATCH (c1:Company)-[g:GUARANTEE]->(c2:Company)-[i:INVEST]->(c3:Company) WHERE i.createTime > g.createTime AND (c3 = c1 OR c3 = c2) RETURN count(*) AS matches"),
        ],
    },
}


def _plain(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6) if math.isfinite(value) else str(value)
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if hasattr(value, "iso_format"):
        return value.iso_format()
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return str(value)


def run(driver, cypher: str) -> tuple[list[str], list[list[Any]], float]:
    start = time.time()
    with driver.session(database="neo4j", default_access_mode="READ") as session:
        result = session.run(cypher)
        columns = list(result.keys())
        rows = [[_plain(record[c]) for c in columns] for record in result]
    return columns, rows, time.time() - start


def compare(ref_cols, ref_rows, fix_cols, fix_rows, *, on=None, ordered=False) -> dict[str, Any]:
    on = on or ref_cols
    ref_idx = [ref_cols.index(c) for c in on]
    fix_idx = [fix_cols.index(c) for c in on]
    ref_keys = [json.dumps([r[i] for i in ref_idx], sort_keys=True, default=str) for r in ref_rows]
    fix_keys = [json.dumps([r[i] for i in fix_idx], sort_keys=True, default=str) for r in fix_rows]
    if ordered:
        same = ref_keys == fix_keys
    else:
        same = set(ref_keys) == set(fix_keys)
    only_ref = sorted(set(ref_keys) - set(fix_keys))
    only_fix = sorted(set(fix_keys) - set(ref_keys))
    return {
        "compared_on": on,
        "ordered": ordered,
        "same_answer": same,
        "only_in_reference": {"count": len(only_ref), "sample": [json.loads(k) for k in only_ref[:SAMPLE]]},
        "only_in_fix": {"count": len(only_fix), "sample": [json.loads(k) for k in only_fix[:SAMPLE]]},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sample-dir", required=True)
    parser.add_argument("--labels", required=True, help="ArtifactData dump directory (labels/*.json)")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    sample = Path(args.sample_dir)
    page = json.loads((sample / "items.json").read_text(encoding="utf-8"))
    ids = json.loads((sample / "adjudication_items.json").read_text(encoding="utf-8"))["items"]
    conventions = {c["name"]: c["rule"] for c in page["conventions"] if c.get("name")}
    labels = {}
    for path in glob.glob(str(Path(args.labels) / "labels" / "*.json")):
        body = json.loads(Path(path).read_text(encoding="utf-8"))
        body = body.get("data", body)
        labels[(body["annotator"], body["item_id"])] = body
    drivers = {graph: GraphDatabase.driver(uri, auth=AUTH) for graph, uri in BOLT.items()}
    out_items = []
    try:
        for item_id in ids:
            spec = FIXES[item_id]
            item = page["items"][item_id]
            driver = drivers[item["graph"]]
            ref_cols, ref_rows, ref_s = run(driver, item["cypher"])
            fix_cols, fix_rows, fix_s = run(driver, spec["fix"])
            comparison = compare(ref_cols, ref_rows, fix_cols, fix_rows, on=spec.get("compare_on"), ordered=bool(spec.get("ordered")))
            entry: dict[str, Any] = {
                "item_id": item_id,
                "graph": item["graph"],
                "question": item["question"],
                "cypher": item["cypher"],
                "positions": {name: queue.index(item_id) + 1 for name, queue in page["annotators"].items() if item_id in queue},
                "labels": {
                    name: {k: labels[(name, item_id)].get(k) for k in ("reference", "clarity", "unclear_convention", "note")}
                    for name in ("A", "B")
                },
                "conventions": [{"name": name, "rule": conventions[name]} for name in spec["conventions"]],
                "concern": spec["concern"],
                "interpretive": spec.get("interpretive", ""),
                "fix": {"note": spec["fix_note"], "cypher": spec["fix"]},
                "reference_result": {"columns": ref_cols, "count": len(ref_rows), "sample": ref_rows[:SAMPLE], "seconds": round(ref_s, 2)},
                "fix_result": {"columns": fix_cols, "count": len(fix_rows), "sample": fix_rows[:SAMPLE], "seconds": round(fix_s, 2)},
                "comparison": comparison,
                "diagnostics": [],
            }
            if spec.get("full_pair"):
                ref_full = run(driver, spec["full_pair"][0])
                fix_full = run(driver, spec["full_pair"][1])
                ref_map = {r[0]: r[1] for r in ref_full[1]}
                fix_map = {r[0]: r[1] for r in fix_full[1]}
                changed = sorted(k for k in set(ref_map) | set(fix_map) if ref_map.get(k) != fix_map.get(k))
                entry["diagnostics"].append({
                    "label": "Whole ranking, not just the top 5: people whose forum count changes",
                    "columns": ["peopleRanked", "peopleWithChangedCount", "example personId", "reference count", "fix count"],
                    "rows": [[len(set(ref_map) | set(fix_map)), len(changed)] + ([changed[0], ref_map.get(changed[0]), fix_map.get(changed[0])] if changed else [None, None, None])],
                })
            for label, cypher in spec["diagnostics"]:
                cols, rows, _ = run(driver, cypher)
                entry["diagnostics"].append({"label": label, "cypher": cypher, "columns": cols, "rows": rows[:20]})
            out_items.append(entry)
            print(f"{item_id}: reference {len(ref_rows)} rows, fix {len(fix_rows)} rows, same answer: {comparison['same_answer']}")
    finally:
        for driver in drivers.values():
            driver.close()
    payload = {
        "set_id": page["set_id"],
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": "Proposed fixes were written to test whether each flaw changes the answer. Results come from the same Neo4j graphs the benchmark was built on, without a row cap.",
        "items": out_items,
    }
    output = Path(args.output) if args.output else sample / "adjudication.json"
    output.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {output}")


if __name__ == "__main__":
    main()
