#!/usr/bin/env python3
"""Rescore stored zero-shot predictions against corrected references on the human-audited items.

For the references that the human audit judged wrong on a clear question, CORRECTED holds a query that
applies the fix named in the annotators' notes (nothing else changes). Each model's stored prediction
for those items is re-executed and scored against the released and the corrected reference with the
standard scorer. Items judged wrong on an ambiguous question have no single correct reference and are
reported separately as dropped. No model calls; read-only queries on the public graphs.

Example:
  python scripts/corrected_reference_rescoring.py --config finbench=<cfg> --config snb=<cfg> \
      --output artifacts/naacl_results/corrected_reference_rescoring.json
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from pipecypher.config import load_config  # noqa: E402
from pipecypher.cypher_client import Neo4jCypherClient  # noqa: E402
from pipecypher.evaluation import evaluate_prediction  # noqa: E402
from pipecypher.schema import load_schema  # noqa: E402
from audit_checklist_judge import SCHEMAS, SYMMETRIC  # noqa: E402

MODELS = ["gpt6_luna", "glm53_flash", "gemma4_26b_a4b", "gpt_oss_20b", "mistral_small32_24b", "qwen3_coder_30b_a3b",
          "phi4", "qwen35_9b", "llama31_8b", "gemma3_12b", "gemma3_4b"]

# item id -> (fix named by the annotators, corrected reference)
CORRECTED = {
    "pc_02f90111aabc0853": ("match the two KNOWS conditions separately so they may use the same edge",
        "MATCH (p:Person {id: 6597069766841})-[:KNOWS*1..3]-(other:Person) WHERE other <> p WITH DISTINCT other "
        "MATCH (other)-[:KNOWS]-(mod:Person)<-[:HAS_MODERATOR]-(f:Forum)-[:HAS_MEMBER]->(other) "
        "RETURN DISTINCT other.id AS personId, COUNT(DISTINCT f) AS forumCount ORDER BY forumCount DESC, personId ASC LIMIT 5"),
    "pc_44ed3256cd90c97b": ("count each linked account once, in either direction, and keep accounts with only incoming transfers",
        "MATCH (a:Account)-[:TRANSFER_TO]-(b:Account) WHERE a <> b WITH a, COUNT(DISTINCT b) AS relatedCount "
        "RETURN DISTINCT a.accountId AS accountId, a.accountType AS accountType, a.isBlocked AS isBlocked, relatedCount ORDER BY relatedCount DESC LIMIT 10"),
    "pc_60ae64b5c6412d4c": ("encode June 1, 2011 as epoch milliseconds",
        "MATCH (p:Person {id: 6597069766747}) RETURN DISTINCT EXISTS { MATCH (p)-[:LIKES]->(po:Post) WHERE po.creationDate < 1306886400000 } AS likedPostBeforeJune2011 LIMIT 1"),
    "pc_702315dac5e12517": ("require the three companies to be distinct",
        "MATCH (c1:Company)-[g:GUARANTEE]->(c2:Company)-[i:INVEST]->(c3:Company) WHERE i.createTime > g.createTime AND c1 <> c2 AND c3 <> c1 AND c3 <> c2 "
        "RETURN DISTINCT c1.companyId AS guarantorCompanyId, c2.companyId AS investorCompanyId"),
    "pc_96aadbfd62ae1c48": ("group by the forum itself",
        "MATCH (f:Forum)-[:HAS_MODERATOR]->(mod:Person)-[:IS_LOCATED_IN]->(:City)-[:IS_PART_OF]->(:Country {name: 'China'}) OPTIONAL MATCH (f)-[:HAS_MEMBER]->(m:Person) "
        "WITH f, mod, COUNT(DISTINCT m) AS memberCount RETURN DISTINCT f.title AS forumTitle, mod.firstName + ' ' + mod.lastName AS moderatorName, memberCount"),
    "pc_98b1f679f2515ca9": ("count only repayments from accounts the guaranteed person owns",
        "MATCH (g:Person)-[:GUARANTEE]->(p:Person)-[:APPLY_LOAN]->(l:Loan)<-[r:REPAY]-(a:Account)<-[:OWN_ACCOUNT]-(p) WITH g, p, sum(r.amount) AS sumRepaid WHERE sumRepaid > 5000.0 "
        "RETURN DISTINCT g.personId AS guarantorPersonId, g.personName AS guarantorPersonName, p.personName AS guaranteedPersonName, sumRepaid"),
    "pc_c8ae16a5acf229f4": ("average over accounts with at least one outgoing transfer (convention C12)",
        "MATCH (a:Account)-[t:TRANSFER_TO]->() WITH a.accountType AS accountType, a, count(t) AS outTransfers "
        "RETURN DISTINCT accountType, avg(outTransfers) AS avgOutgoingTransfers ORDER BY accountType"),
}
AMBIGUOUS_WRONG = ["pc_4a34d1dce72de7a6", "pc_f2681804ba04a524", "pc_35bca2c2bee0cbc4", "pc_5cfd55aa49f83ccf", "pc_89ff63100cc28525"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export", default="artifacts/benchmarks/naacl_v3_full/all.jsonl")
    ap.add_argument("--eval-root", default="artifacts/evaluations"); ap.add_argument("--eval-prefix", default="naacl_v3_all")
    ap.add_argument("--config", action="append", required=True)
    ap.add_argument("--output", default="artifacts/naacl_results/corrected_reference_rescoring.json")
    args = ap.parse_args()
    ctx = {}
    for item in args.config:
        g, path = item.split("=", 1); cfg = load_config(path)
        schema = load_schema(SCHEMAS[g]); schema.symmetric_relationships = SYMMETRIC.get(g, [])
        ctx[g] = (schema, Neo4jCypherClient(cfg.neo4j.uri, cfg.neo4j.user, cfg.neo4j.password, database=cfg.neo4j.database,
                                            timeout_sec=cfg.neo4j.query_timeout_sec, enforce_read_transactions=cfg.neo4j.enforce_read_transactions))
    wanted = set(CORRECTED) | set(AMBIGUOUS_WRONG)
    items = {r["id"]: r for r in map(json.loads, open(args.export)) if r["id"] in wanted}
    assert set(items) == wanted, wanted - set(items)
    out = {"items": {}, "models": {}}
    for i, (fix, cy) in CORRECTED.items():
        it = items[i]; schema, client = ctx[it["graph_profile"]]
        old, new = client.run(it["cypher"]), client.run(cy)
        key = lambda rows: sorted(json.dumps(r, sort_keys=True, default=str) for r in rows)
        out["items"][i] = {"graph": it["graph_profile"], "category": it["category"], "tier": it.get("difficulty") or it.get("tier"), "fix": fix,
                           "released": it["cypher"], "corrected": cy, "corrected_ok": new.success, "error": new.error,
                           "rows_released": len(old.rows), "rows_corrected": len(new.rows), "answer_changed": key(old.rows) != key(new.rows)}
        print(i, out["items"][i]["rows_released"], out["items"][i]["rows_corrected"], out["items"][i]["answer_changed"], new.error, flush=True)
    for m in MODELS:
        preds = {r["id"]: r for r in map(json.loads, open(Path(args.eval_root) / f"{args.eval_prefix}_downstream_{m}" / "zero_shot_evaluation.jsonl")) if r["id"] in wanted}
        per = {}
        for i, (_, cy) in CORRECTED.items():
            it = items[i]; schema, client = ctx[it["graph_profile"]]; p = preds[i]
            new = evaluate_prediction(question=it["question"], gold_cypher=cy, predicted_cypher=p.get("predicted_cypher", ""), schema=schema, client=client, include_text_metrics=False)
            per[i] = {"released": bool(p.get("projected_execution_accuracy")), "corrected": bool(new.get("projected_execution_accuracy"))}
        out["models"][m] = {"per_item": per, "released_correct": sum(v["released"] for v in per.values()), "corrected_correct": sum(v["corrected"] for v in per.values()),
                            "ambiguous_wrong_released_correct": sum(bool(preds[i].get("projected_execution_accuracy")) for i in AMBIGUOUS_WRONG)}
        print(m, {k: v for k, v in out["models"][m].items() if k != "per_item"}, flush=True)
    Path(args.output).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
