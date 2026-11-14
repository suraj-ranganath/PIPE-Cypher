// PIPE-Cypher refresh experiment M4 (schema migration: dropped relationship type).
// Delete every GUARANTEE relationship (Person->Person and Company->Company).
// Apply ONLY to a disposable copy via scripts/apply_graph_migration.py.
MATCH ()-[g:GUARANTEE]->()
CALL {
  WITH g
  DELETE g
} IN TRANSACTIONS OF 5000 ROWS;
