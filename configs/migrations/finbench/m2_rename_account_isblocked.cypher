// PIPE-Cypher refresh experiment M2 (schema migration).
// Rename node property Account.isBlocked -> Account.blocked.
// isBlocked on Person, Company, and Medium is intentionally left unchanged.
// Apply ONLY to a disposable copy via scripts/apply_graph_migration.py.
MATCH (a:Account)
WHERE a.isBlocked IS NOT NULL
CALL {
  WITH a
  SET a.blocked = a.isBlocked
  REMOVE a.isBlocked
} IN TRANSACTIONS OF 5000 ROWS;
