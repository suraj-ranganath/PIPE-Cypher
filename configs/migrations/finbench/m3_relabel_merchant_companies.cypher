// PIPE-Cypher refresh experiment M3 (schema migration: new label + new type).
// Statement 1: relabel a deterministic hash-selected subset of Company nodes as
// Merchant ($rows comes from the selection block in the metadata; the hash is
// over companyId, not internal element ids).
UNWIND $rows AS row
MATCH (c:Company {companyId: row.companyId})
SET c:Merchant
REMOVE c:Company
RETURN count(c) AS affected;

// Statement 2: add a new relationship type from each merchant to the accounts
// it owns, stamped with the ownership time.
MATCH (m:Merchant)-[own:OWN_ACCOUNT]->(a:Account)
MERGE (m)-[s:SETTLES_TO]->(a)
ON CREATE SET s.createTime = own.createTime
RETURN count(s) AS affected;
