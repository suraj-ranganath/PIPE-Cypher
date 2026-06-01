# LDBC Source Snapshot

Fetch command attempted on June 1, 2026:

```bash
scripts/fetch_ldbc_sources.sh external
```

Fetched successfully:

- `external/ldbc_finbench_docs`: `aebdb298a7496484dad5321211c8d3486295395f`
- `external/ldbc_finbench_datagen`: `e32675a68cbca6fd753458a36c9b4f49cd18f27f`
- `external/ldbc_snb_datagen_spark`: `b3dc986898efac7c1676abba865a30865334922e`
- `external/ldbc_snb_interactive_v1_impls`: `11db98cc2ba14c33492f6c0c34e68c8be7e22e5f`

FinBench snapshot schema facts extracted from `external/ldbc_finbench_datagen/transformation/snapshot.sql`:

- Nodes: `Person`, `Company`, `Account`, `Loan`, and `Medium`.
- Core identifiers and display fields: `Person.personId/personName`, `Company.companyId/companyName`, `Account.accountId`, `Loan.loanId`, `Medium.mediumId/mediumType`.
- Directional relationships: `Account-[:TRANSFER_TO]->Account`, `Account-[:WITHDRAW_TO]->Account`, `Account-[:REPAY]->Loan`, `Loan-[:DEPOSIT]->Account`, `Medium-[:SIGN_IN]->Account`, `Person-[:OWN_ACCOUNT]->Account`, `Company-[:OWN_ACCOUNT]->Account`, `Person-[:APPLY_LOAN]->Loan`, `Company-[:APPLY_LOAN]->Loan`, `Person-[:GUARANTEE]->Person`, `Company-[:GUARANTEE]->Company`, `Person-[:INVEST]->Company`, and `Company-[:INVEST]->Company`.
- Transaction/event relationships carry properties such as `amount`, `createTime`, `orderNum`, `payType`, `goodsType`, `location`, `ratio`, `loanAmount`, `org`, and `relation`.
- PIPE-Cypher's built-in FinBench profile and `scripts/generate_finbench_import_cypher.py` are now grounded in this snapshot export.

SNB schema facts extracted from `external/ldbc_snb_interactive_v1_impls/cypher/scripts/headers.txt` and the Cypher query files:

- Main labels include `Person`, `Forum`, `Message`, `Post`, `Comment`, `Tag`, `TagClass`, `City`, `Country`, `Company`, and `University`.
- Core relationships include `KNOWS`, `LIKES`, `HAS_CREATOR`, `REPLY_OF`, `CONTAINER_OF`, `HAS_MEMBER`, `HAS_MODERATOR`, `HAS_TAG`, `HAS_INTEREST`, `IS_LOCATED_IN`, `STUDY_AT`, `WORK_AT`, `HAS_TYPE`, `IS_SUBCLASS_OF`, and `IS_PART_OF`.
- The Cypher implementation provides ready-made read workloads under `external/ldbc_snb_interactive_v1_impls/cypher/queries/interactive-*.cypher`.

The fetch script remains the reproducible path. Use a shallow clone when full history is not required:

```bash
GIT_DEPTH=1 scripts/fetch_ldbc_sources.sh external
```
