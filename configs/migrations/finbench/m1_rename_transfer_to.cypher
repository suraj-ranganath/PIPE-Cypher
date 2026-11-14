// PIPE-Cypher refresh experiment M1 (schema migration).
// Rename relationship type TRANSFER_TO -> SENDS_FUNDS, copying every property.
// Neo4j cannot retype a relationship in place, so each edge is recreated with
// the same endpoints and properties and the old edge is deleted.
// Apply ONLY to a disposable copy via scripts/apply_graph_migration.py.
MATCH (src)-[old:TRANSFER_TO]->(dst)
CALL {
  WITH src, old, dst
  CREATE (src)-[renamed:SENDS_FUNDS]->(dst)
  SET renamed = properties(old)
  DELETE old
} IN TRANSACTIONS OF 5000 ROWS;
