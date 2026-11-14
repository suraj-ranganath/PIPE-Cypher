// PIPE-Cypher refresh experiment D1 (data drift: deletions).
// Delete the deterministic ~10% of TRANSFER_TO edges chosen by a salted SHA-256
// of (src accountId, dst accountId, orderNum, createTime, amount); $rows comes
// from the selection block in the metadata. Duplicated identical edges are all
// removed, and the ledger reports affected vs selected counts.
UNWIND $rows AS row
MATCH (src:Account {accountId: row.src})-[t:TRANSFER_TO]->(dst:Account {accountId: row.dst})
WHERE coalesce(t.orderNum, '') = coalesce(row.orderNum, '')
  AND coalesce(toString(t.createTime), '') = coalesce(row.createTime, '')
  AND coalesce(t.amount, -1.0) = coalesce(row.amount, -1.0)
DELETE t
RETURN count(*) AS affected;
