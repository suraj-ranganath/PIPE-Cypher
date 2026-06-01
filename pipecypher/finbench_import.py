from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class NodeCsvSpec:
    label: str
    file_stem: str
    id_property: str
    properties: tuple[str, ...]


@dataclass(frozen=True)
class RelationshipCsvSpec:
    rel_type: str
    file_stem: str
    start_label: str
    start_id_property: str
    start_csv_property: str
    end_label: str
    end_id_property: str
    end_csv_property: str
    properties: tuple[str, ...]


NODE_SPECS: tuple[NodeCsvSpec, ...] = (
    NodeCsvSpec(
        "Person",
        "Person",
        "personId",
        ("personId", "personName", "isBlocked", "createTime", "gender", "birthday", "country", "city"),
    ),
    NodeCsvSpec(
        "Company",
        "Company",
        "companyId",
        (
            "companyId",
            "companyName",
            "isBlocked",
            "createTime",
            "country",
            "city",
            "business",
            "description",
            "url",
        ),
    ),
    NodeCsvSpec(
        "Account",
        "Account",
        "accountId",
        (
            "accountId",
            "createTime",
            "isBlocked",
            "accountType",
            "nickname",
            "phonenum",
            "email",
            "freqLoginType",
            "lastLoginTime",
            "accountLevel",
        ),
    ),
    NodeCsvSpec(
        "Loan",
        "Loan",
        "loanId",
        ("loanId", "loanAmount", "balance", "createTime", "loanUsage", "interestRate"),
    ),
    NodeCsvSpec(
        "Medium",
        "Medium",
        "mediumId",
        ("mediumId", "mediumType", "isBlocked", "createTime", "lastLoginTime", "riskLevel"),
    ),
)

RELATIONSHIP_SPECS: tuple[RelationshipCsvSpec, ...] = (
    RelationshipCsvSpec(
        "TRANSFER_TO",
        "AccountTransferAccount",
        "Account",
        "accountId",
        "fromId",
        "Account",
        "accountId",
        "toId",
        ("amount", "createTime", "orderNum", "comment", "payType", "goodsType"),
    ),
    RelationshipCsvSpec(
        "WITHDRAW_TO",
        "AccountWithdrawAccount",
        "Account",
        "accountId",
        "fromId",
        "Account",
        "accountId",
        "toId",
        ("fromType", "toType", "amount", "createTime", "comment"),
    ),
    RelationshipCsvSpec(
        "REPAY",
        "AccountRepayLoan",
        "Account",
        "accountId",
        "accountId",
        "Loan",
        "loanId",
        "loanId",
        ("amount", "createTime", "comment"),
    ),
    RelationshipCsvSpec(
        "DEPOSIT",
        "LoanDepositAccount",
        "Loan",
        "loanId",
        "loanId",
        "Account",
        "accountId",
        "accountId",
        ("amount", "createTime", "comment"),
    ),
    RelationshipCsvSpec(
        "SIGN_IN",
        "MediumSignInAccount",
        "Medium",
        "mediumId",
        "mediumId",
        "Account",
        "accountId",
        "accountId",
        ("createTime", "location", "comment"),
    ),
    RelationshipCsvSpec(
        "INVEST",
        "PersonInvestCompany",
        "Person",
        "personId",
        "investorId",
        "Company",
        "companyId",
        "companyId",
        ("ratio", "createTime", "comment"),
    ),
    RelationshipCsvSpec(
        "INVEST",
        "CompanyInvestCompany",
        "Company",
        "companyId",
        "investorId",
        "Company",
        "companyId",
        "companyId",
        ("ratio", "createTime", "comment"),
    ),
    RelationshipCsvSpec(
        "APPLY_LOAN",
        "PersonApplyLoan",
        "Person",
        "personId",
        "personId",
        "Loan",
        "loanId",
        "loanId",
        ("loanAmount", "createTime", "org", "comment"),
    ),
    RelationshipCsvSpec(
        "APPLY_LOAN",
        "CompanyApplyLoan",
        "Company",
        "companyId",
        "companyId",
        "Loan",
        "loanId",
        "loanId",
        ("loanAmount", "createTime", "org", "comment"),
    ),
    RelationshipCsvSpec(
        "GUARANTEE",
        "PersonGuaranteePerson",
        "Person",
        "personId",
        "fromId",
        "Person",
        "personId",
        "toId",
        ("createTime", "relation", "comment"),
    ),
    RelationshipCsvSpec(
        "GUARANTEE",
        "CompanyGuaranteeCompany",
        "Company",
        "companyId",
        "fromId",
        "Company",
        "companyId",
        "toId",
        ("createTime", "relation", "comment"),
    ),
    RelationshipCsvSpec(
        "OWN_ACCOUNT",
        "PersonOwnAccount",
        "Person",
        "personId",
        "personId",
        "Account",
        "accountId",
        "accountId",
        ("createTime", "comment"),
    ),
    RelationshipCsvSpec(
        "OWN_ACCOUNT",
        "CompanyOwnAccount",
        "Company",
        "companyId",
        "companyId",
        "Account",
        "accountId",
        "accountId",
        ("createTime", "comment"),
    ),
)

FLOAT_PROPERTIES = {"amount", "loanAmount", "balance", "interestRate", "ratio"}
INTEGER_PROPERTIES = {"accountLevel", "riskLevel"}
BOOLEAN_PROPERTIES = {"isBlocked"}
DATETIME_PROPERTIES = {"createTime", "lastLoginTime"}
DATE_PROPERTIES = {"birthday"}
NODE_PROPERTY_TYPES = {
    prop: (
        "FLOAT"
        if prop in FLOAT_PROPERTIES
        else "INTEGER"
        if prop in INTEGER_PROPERTIES
        else "BOOLEAN"
        if prop in BOOLEAN_PROPERTIES
        else "DATETIME"
        if prop in DATETIME_PROPERTIES
        else "DATE"
        if prop in DATE_PROPERTIES
        else "STRING"
    )
    for spec in NODE_SPECS
    for prop in spec.properties
}
RELATIONSHIP_PROPERTY_TYPES = {
    prop: (
        "FLOAT"
        if prop in FLOAT_PROPERTIES
        else "INTEGER"
        if prop in INTEGER_PROPERTIES
        else "BOOLEAN"
        if prop in BOOLEAN_PROPERTIES
        else "DATETIME"
        if prop in DATETIME_PROPERTIES
        else "DATE"
        if prop in DATE_PROPERTIES
        else "STRING"
    )
    for spec in RELATIONSHIP_SPECS
    for prop in spec.properties
}


def cypher_value(prop: str) -> str:
    row = f"row.{prop}"
    if prop in FLOAT_PROPERTIES:
        return f"CASE row.{prop} WHEN '' THEN null ELSE toFloat({row}) END"
    if prop in INTEGER_PROPERTIES:
        return f"CASE row.{prop} WHEN '' THEN null ELSE toInteger({row}) END"
    if prop in BOOLEAN_PROPERTIES:
        return f"CASE row.{prop} WHEN '' THEN null ELSE toBoolean({row}) END"
    if prop in DATETIME_PROPERTIES:
        return f"CASE row.{prop} WHEN '' THEN null ELSE datetime(replace({row}, ' ', 'T')) END"
    if prop in DATE_PROPERTIES:
        return f"CASE row.{prop} WHEN '' THEN null ELSE date({row}) END"
    return row


def property_map(properties: tuple[str, ...], indent: str = "  ") -> str:
    rows = [f"{indent}{prop}: {cypher_value(prop)}" for prop in properties]
    return "{\n" + ",\n".join(rows) + "\n}"


def generate_import_cypher(csv_base_url: str = "file:///finbench/snapshot", extension: str = "csv") -> str:
    statements: list[str] = []
    statements.append(
        "// Generated by PIPE-Cypher. Place FinBench snapshot CSVs under Neo4j "
        "import/finbench/snapshot. Clear the target database before re-running this script."
    )
    for spec in NODE_SPECS:
        statements.append(
            f"CREATE CONSTRAINT {spec.label.lower()}_{spec.id_property}_unique IF NOT EXISTS "
            f"FOR (n:{spec.label}) REQUIRE n.{spec.id_property} IS UNIQUE;"
        )
    for spec in NODE_SPECS:
        url = f"{csv_base_url}/{spec.file_stem}.{extension}"
        statements.append(
            f"LOAD CSV WITH HEADERS FROM '{url}' AS row FIELDTERMINATOR '|'\n"
            f"MERGE (n:{spec.label} {{{spec.id_property}: row.{spec.id_property}}})\n"
            f"SET n += {property_map(spec.properties)};"
        )
    for spec in RELATIONSHIP_SPECS:
        url = f"{csv_base_url}/{spec.file_stem}.{extension}"
        statements.append(
            f"LOAD CSV WITH HEADERS FROM '{url}' AS row FIELDTERMINATOR '|'\n"
            f"MATCH (src:{spec.start_label} {{{spec.start_id_property}: row.{spec.start_csv_property}}})\n"
            f"MATCH (dst:{spec.end_label} {{{spec.end_id_property}: row.{spec.end_csv_property}}})\n"
            f"CREATE (src)-[r:{spec.rel_type}]->(dst)\n"
            f"SET r += {property_map(spec.properties)};"
        )
    return "\n\n".join(statements) + "\n"


def write_import_cypher(path: str | Path, csv_base_url: str = "file:///finbench/snapshot", extension: str = "csv") -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(generate_import_cypher(csv_base_url, extension), encoding="utf-8")
