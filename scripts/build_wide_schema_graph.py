#!/usr/bin/env python3
"""Build a wide-schema test graph by copying public graphs into ONE database.

Each source graph is copied ``--replicas`` times with namespaced labels and
relationship types (``Account`` in FinBench replica A becomes ``FinA_Account``;
``TRANSFER_TO`` becomes ``FINA_TRANSFER_TO``), so the merged database has many
times the labels of any single source while every label holds real data. It is
a stand-in for a large multi-domain tenant schema (reviewer concern: schemas
with 100+ labels). Properties are copied unchanged. A temporary ``_cp``
property (source element id) links relationships and is removed at the end.

Writes only to ``--target`` (refuses the source URIs). Read-only on sources.

Example:
  python scripts/build_wide_schema_graph.py --target bolt://127.0.0.1:17720 --replicas 4 \
      --source fin=bolt://127.0.0.1:17687 --source snb=bolt://127.0.0.1:17688 \
      --source rec=bolt://127.0.0.1:17701 --source nw=bolt://127.0.0.1:17702 --source fc=bolt://127.0.0.1:17703
"""

from __future__ import annotations

import argparse
import string
import time
from collections import defaultdict

from neo4j import GraphDatabase

BATCH = 2000


def _ident(name: str) -> str:
    return "`" + name.replace("`", "") + "`"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", required=True)
    ap.add_argument("--source", action="append", required=True, help="namespace=bolt://host:port")
    ap.add_argument("--replicas", type=int, default=4)
    ap.add_argument("--user", default="neo4j")
    ap.add_argument("--password", default="password")
    ap.add_argument("--wipe", action="store_true", help="Delete everything in the target first")
    args = ap.parse_args()

    sources = [s.split("=", 1) for s in args.source]
    if any(uri == args.target for _, uri in sources):
        raise SystemExit("target equals a source; refusing to write")
    letters = string.ascii_uppercase[: args.replicas]
    auth = (args.user, args.password)
    tgt = GraphDatabase.driver(args.target, auth=auth)
    with tgt.session() as s:
        n = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        if n and not args.wipe:
            raise SystemExit(f"target holds {n} nodes; pass --wipe to clear it")
        if n:
            s.run("MATCH (n) CALL { WITH n DETACH DELETE n } IN TRANSACTIONS OF 5000 ROWS").consume()
    t0 = time.time()
    created_labels: set[str] = set()
    for ns, uri in sources:
        src = GraphDatabase.driver(uri, auth=auth)
        with src.session() as s:
            nodes = [(r["id"], r["labels"], r["props"]) for r in s.run("MATCH (n) RETURN elementId(n) AS id, labels(n) AS labels, properties(n) AS props")]
            primary = {nid: (labels[0] if labels else "Node") for nid, labels, _ in nodes}
            rels = [(r["s"], r["t"], r["type"], r["props"]) for r in s.run(
                "MATCH (a)-[r]->(b) RETURN elementId(a) AS s, elementId(b) AS t, type(r) AS type, properties(r) AS props")]
        src.close()
        print(f"{ns}: {len(nodes)} nodes, {len(rels)} relationships", flush=True)
        for letter in letters:
            prefix = f"{ns.capitalize()}{letter}_"
            rprefix = f"{ns.upper()}{letter}_"
            by_labels: dict[tuple, list] = defaultdict(list)
            for nid, labels, props in nodes:
                by_labels[tuple(labels or ["Node"])].append({"cp": nid, "props": props})
            with tgt.session() as s:
                for labels in by_labels:
                    for lab in labels:
                        if prefix + lab not in created_labels:
                            s.run(f"CREATE INDEX IF NOT EXISTS FOR (n:{_ident(prefix + lab)}) ON (n._cp)").consume()
                            created_labels.add(prefix + lab)
                s.run("CALL db.awaitIndexes(300)").consume()
                for labels, rows in by_labels.items():
                    lab_str = ":".join(_ident(prefix + lab) for lab in labels)
                    for i in range(0, len(rows), BATCH):
                        s.run(f"UNWIND $rows AS row CREATE (n:{lab_str}) SET n = row.props, n._cp = row.cp",
                              rows=rows[i:i + BATCH]).consume()
                by_type: dict[tuple, list] = defaultdict(list)
                for sid, tid, rtype, props in rels:
                    by_type[(rtype, primary[sid], primary[tid])].append({"s": sid, "t": tid, "props": props})
                for (rtype, sl, tl), rows in by_type.items():
                    q = (f"UNWIND $rows AS row MATCH (a:{_ident(prefix + sl)} {{_cp: row.s}}) "
                         f"MATCH (b:{_ident(prefix + tl)} {{_cp: row.t}}) "
                         f"CREATE (a)-[r:{_ident(rprefix + rtype)}]->(b) SET r = row.props")
                    for i in range(0, len(rows), BATCH):
                        s.run(q, rows=rows[i:i + BATCH]).consume()
            print(f"  replica {letter} done ({time.time() - t0:.0f}s)", flush=True)
    with tgt.session() as s:
        s.run("MATCH (n) WHERE n._cp IS NOT NULL CALL { WITH n REMOVE n._cp } IN TRANSACTIONS OF 10000 ROWS").consume()
        for rec in s.run("SHOW INDEXES YIELD name, properties WHERE properties = ['_cp'] RETURN name").data():
            s.run(f"DROP INDEX {_ident(rec['name'])}").consume()
        stats = {
            "nodes": s.run("MATCH (n) RETURN count(n) AS c").single()["c"],
            "relationships": s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"],
            "labels": len(s.run("CALL db.labels() YIELD label RETURN label").data()),
            "relationship_types": len(s.run("CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType").data()),
        }
    tgt.close()
    print(f"done in {time.time() - t0:.0f}s: {stats}")


if __name__ == "__main__":
    main()
