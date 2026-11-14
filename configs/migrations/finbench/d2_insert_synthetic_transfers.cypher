// PIPE-Cypher refresh experiment D2 (data drift: insertions).
// Insert deterministic synthetic TRANSFER_TO edges between existing accounts
// ("new transactions arriving" after the latest existing createTime). $rows is
// produced by the synthetic_transfers generator declared in the metadata; each
// edge carries a comment marker so the drift is auditable.
UNWIND $rows AS row
MATCH (src:Account {accountId: row.src})
MATCH (dst:Account {accountId: row.dst})
CREATE (src)-[t:TRANSFER_TO]->(dst)
SET t.amount = row.amount,
    t.createTime = datetime(row.baseTime) + duration({minutes: row.offsetMinutes}),
    t.orderNum = row.orderNum,
    t.comment = row.comment,
    t.payType = row.payType,
    t.goodsType = row.goodsType
RETURN count(t) AS affected;
