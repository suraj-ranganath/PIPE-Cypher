#!/usr/bin/env python3
"""Order-aware rescoring of items that ask for a sorted listing without a cutoff.

Projected EX compares row sets. For released items whose reference has ORDER BY and no LIMIT, this
script re-executes the reference and every stored prediction that passed projected EX, and checks
whether the prediction's rows follow the reference's sort keys. No model calls; read-only queries.

Example:
  python scripts/order_aware_rescoring.py --config finbench=<cfg> --config snb=<cfg> \
      --output artifacts/naacl_results/order_aware_rescoring.json
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipecypher.config import load_config  # noqa: E402
from pipecypher.cypher_client import Neo4jCypherClient  # noqa: E402
from pipecypher.evaluation import _expand_entity_columns, analyze_cypher  # noqa: E402
from pipecypher.validator import clean_cypher  # noqa: E402

MODELS = ["gpt6_luna", "glm53_flash", "gemma4_26b_a4b", "gpt_oss_20b", "mistral_small32_24b", "qwen3_coder_30b_a3b",
          "phi4", "qwen35_9b", "llama31_8b", "gemma3_12b", "gemma3_4b"]


def dedup(seq):
    out, prev = [], object()
    for x in seq:
        if x != prev:
            out.append(x)
            prev = x
    return out


def sort_columns(cypher: str) -> list[str] | None:
    a = analyze_cypher(cypher)
    cols = []
    for term in a.order_by_items:
        expr = re.sub(r"\s+(ASC|DESC|ASCENDING|DESCENDING)$", "", term.strip(), flags=re.I)
        hit = None
        for item in a.projection_items:
            name = item.alias or item.expression
            if expr in (item.alias, item.expression):
                hit = name
        if hit is None:
            return None
        cols.append(hit)
    return cols or None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export", default="artifacts/benchmarks/naacl_v3_full/all.jsonl")
    ap.add_argument("--eval-root", default="artifacts/evaluations")
    ap.add_argument("--eval-prefix", default="naacl_v3_all")
    ap.add_argument("--config", action="append", required=True)
    ap.add_argument("--output", default="artifacts/naacl_results/order_aware_rescoring.json")
    args = ap.parse_args()
    clients = {}
    for item in args.config:
        g, path = item.split("=", 1)
        cfg = load_config(path)
        clients[g] = Neo4jCypherClient(cfg.neo4j.uri, cfg.neo4j.user, cfg.neo4j.password, database=cfg.neo4j.database,
                                       timeout_sec=cfg.neo4j.query_timeout_sec, enforce_read_transactions=cfg.neo4j.enforce_read_transactions)
    items = {}
    for line in open(args.export):
        r = json.loads(line)
        if re.search(r"ORDER BY", r["cypher"], re.I) and not re.search(r"\bLIMIT\b", r["cypher"], re.I):
            items[r["id"]] = r
    gold_cache = {}
    result = {"items": len(items), "models": {}}
    for m in MODELS:
        stats = {"projected_correct": 0, "order_consistent": 0, "order_violated": 0, "unchecked": 0}
        n_all = 0
        for line in open(Path(args.eval_root) / f"{args.eval_prefix}_downstream_{m}" / "zero_shot_evaluation.jsonl"):
            r = json.loads(line)
            n_all += 1
            it = items.get(r["id"])
            if it is None or not r.get("projected_execution_accuracy"):
                continue
            stats["projected_correct"] += 1
            client = clients[it["graph_profile"]]
            if it["id"] not in gold_cache:
                gold_cache[it["id"]] = client.run(clean_cypher(it["cypher"]))
            gold = gold_cache[it["id"]]
            pred = client.run(clean_cypher(r["predicted_cypher"]))
            keys = sort_columns(it["cypher"])
            if not (gold.success and pred.success and gold.rows and pred.rows) or keys is None:
                stats["unchecked"] += 1
                continue
            gold_cols = list(gold.rows[0].keys())
            mapping = r.get("projection_mapping")
            pred_rows, _ = _expand_entity_columns(pred.rows)
            if not mapping:
                pred_cols = list(pred_rows[0].keys())
                mapping = dict(zip(gold_cols, pred_cols)) if len(gold_cols) == 1 else {c: c for c in gold_cols}
            if any(k not in mapping or mapping[k] not in pred_rows[0] for k in keys):
                stats["unchecked"] += 1
                continue
            g_seq = dedup([tuple(str(row.get(k)) for k in keys) for row in gold.rows])
            p_seq = dedup([tuple(str(row.get(mapping[k])) for k in keys) for row in pred_rows])
            if g_seq == p_seq:
                stats["order_consistent"] += 1
            else:
                stats["order_violated"] += 1
        stats["n_all"] = n_all
        stats["accuracy_drop_points_all_items"] = round(100 * stats["order_violated"] / n_all, 2)
        result["models"][m] = stats
        print(m, stats, flush=True)
    Path(args.output).write_text(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
