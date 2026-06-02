from __future__ import annotations

from .finbench_import import (
    NODE_PROPERTY_TYPES,
    NODE_SPECS,
    RELATIONSHIP_PROPERTY_TYPES,
    RELATIONSHIP_SPECS,
)
from .models import NodeProperty, RelationshipPattern, RelationshipProperty, SchemaSummary, TemplateCandidate


def _finbench_node_properties() -> list[NodeProperty]:
    seen: set[tuple[str, str]] = set()
    properties: list[NodeProperty] = []
    for spec in NODE_SPECS:
        for prop in spec.properties:
            key = (spec.label, prop)
            if key in seen:
                continue
            seen.add(key)
            properties.append(NodeProperty(spec.label, prop, NODE_PROPERTY_TYPES.get(prop, "ANY")))
    return properties


def _finbench_relationship_properties() -> list[RelationshipProperty]:
    seen: set[tuple[str, str]] = set()
    properties: list[RelationshipProperty] = []
    for spec in RELATIONSHIP_SPECS:
        for prop in spec.properties:
            key = (spec.rel_type, prop)
            if key in seen:
                continue
            seen.add(key)
            properties.append(
                RelationshipProperty(
                    spec.rel_type,
                    prop,
                    RELATIONSHIP_PROPERTY_TYPES.get(prop, "ANY"),
                )
            )
    return properties


def finbench_reference_schema() -> SchemaSummary:
    """LDBC FinBench snapshot schema for offline smoke tests and prompts.

    This profile is grounded in the public FinBench datagen `snapshot.sql` export.
    Live runs should still introspect the loaded graph to catch backend-specific
    import changes and observed relationship counts.
    """

    node_properties = _finbench_node_properties()
    relationship_properties = _finbench_relationship_properties()
    relationships = [
        RelationshipPattern(spec.start_label, spec.rel_type, spec.end_label)
        for spec in RELATIONSHIP_SPECS
    ]
    return SchemaSummary(
        node_properties=node_properties,
        relationship_properties=relationship_properties,
        relationships=relationships,
        categorical_properties={
            "Account.accountType": ["debit", "credit", "checking", "savings"],
            "Medium.mediumType": ["email", "phone", "device", "ip"],
            "Company.business": ["finance", "retail", "technology", "services"],
        },
        graph_name="finbench_reference",
        source="built_in_reference",
    )


def snb_reference_schema() -> SchemaSummary:
    node_properties = [
        NodeProperty("Person", "id", "INTEGER"),
        NodeProperty("Person", "firstName", "STRING"),
        NodeProperty("Person", "lastName", "STRING"),
        NodeProperty("Person", "gender", "STRING"),
        NodeProperty("Person", "birthday", "INTEGER"),
        NodeProperty("Person", "creationDate", "INTEGER"),
        NodeProperty("Person", "locationIP", "STRING"),
        NodeProperty("Person", "browserUsed", "STRING"),
        NodeProperty("Person", "speaks", "STRING[]"),
        NodeProperty("Person", "email", "STRING[]"),
        NodeProperty("Forum", "id", "INTEGER"),
        NodeProperty("Forum", "title", "STRING"),
        NodeProperty("Forum", "creationDate", "INTEGER"),
        NodeProperty("Message", "id", "INTEGER"),
        NodeProperty("Message", "creationDate", "INTEGER"),
        NodeProperty("Message", "locationIP", "STRING"),
        NodeProperty("Message", "browserUsed", "STRING"),
        NodeProperty("Message", "content", "STRING"),
        NodeProperty("Message", "length", "INTEGER"),
        NodeProperty("Post", "id", "INTEGER"),
        NodeProperty("Post", "imageFile", "STRING"),
        NodeProperty("Post", "creationDate", "INTEGER"),
        NodeProperty("Post", "language", "STRING"),
        NodeProperty("Post", "content", "STRING"),
        NodeProperty("Comment", "id", "INTEGER"),
        NodeProperty("Comment", "creationDate", "INTEGER"),
        NodeProperty("Comment", "content", "STRING"),
        NodeProperty("Comment", "length", "INTEGER"),
        NodeProperty("Tag", "id", "INTEGER"),
        NodeProperty("Tag", "name", "STRING"),
        NodeProperty("TagClass", "id", "INTEGER"),
        NodeProperty("TagClass", "name", "STRING"),
        NodeProperty("City", "id", "INTEGER"),
        NodeProperty("City", "name", "STRING"),
        NodeProperty("Country", "id", "INTEGER"),
        NodeProperty("Country", "name", "STRING"),
        NodeProperty("Company", "id", "INTEGER"),
        NodeProperty("Company", "name", "STRING"),
        NodeProperty("University", "id", "INTEGER"),
        NodeProperty("University", "name", "STRING"),
    ]
    relationship_properties = [
        RelationshipProperty("KNOWS", "creationDate", "INTEGER"),
        RelationshipProperty("LIKES", "creationDate", "INTEGER"),
        RelationshipProperty("HAS_MEMBER", "joinDate", "INTEGER"),
        RelationshipProperty("STUDY_AT", "classYear", "INTEGER"),
        RelationshipProperty("WORK_AT", "workFrom", "INTEGER"),
    ]
    relationships = [
        RelationshipPattern("Person", "KNOWS", "Person"),
        RelationshipPattern("Person", "LIKES", "Comment"),
        RelationshipPattern("Person", "LIKES", "Post"),
        RelationshipPattern("Person", "HAS_INTEREST", "Tag"),
        RelationshipPattern("Person", "IS_LOCATED_IN", "City"),
        RelationshipPattern("Person", "STUDY_AT", "University"),
        RelationshipPattern("Person", "WORK_AT", "Company"),
        RelationshipPattern("Forum", "HAS_MEMBER", "Person"),
        RelationshipPattern("Forum", "HAS_MODERATOR", "Person"),
        RelationshipPattern("Forum", "CONTAINER_OF", "Post"),
        RelationshipPattern("Forum", "HAS_TAG", "Tag"),
        RelationshipPattern("Post", "HAS_CREATOR", "Person"),
        RelationshipPattern("Comment", "HAS_CREATOR", "Person"),
        RelationshipPattern("Post", "HAS_TAG", "Tag"),
        RelationshipPattern("Comment", "HAS_TAG", "Tag"),
        RelationshipPattern("Comment", "REPLY_OF", "Post"),
        RelationshipPattern("Comment", "REPLY_OF", "Comment"),
        RelationshipPattern("Post", "IS_LOCATED_IN", "Country"),
        RelationshipPattern("Comment", "IS_LOCATED_IN", "Country"),
        RelationshipPattern("Company", "IS_LOCATED_IN", "Country"),
        RelationshipPattern("University", "IS_LOCATED_IN", "City"),
        RelationshipPattern("City", "IS_PART_OF", "Country"),
        RelationshipPattern("Tag", "HAS_TYPE", "TagClass"),
        RelationshipPattern("TagClass", "IS_SUBCLASS_OF", "TagClass"),
    ]
    return SchemaSummary(
        node_properties=node_properties,
        relationship_properties=relationship_properties,
        relationships=relationships,
        graph_name="snb_reference",
        source="built_in_reference_cypher_headers",
    )


ICIJ_REL_TYPES = [
    "officer_of",
    "registered_address",
    "intermediary_of",
    "same_name_as",
    "similar",
    "same_company_as",
    "connected_to",
    "same_as",
    "same_id_as",
    "underlying",
    "similar_company_as",
    "probably_same_officer_as",
    "same_address_as",
    "same_intermediary_as",
]


def icij_offshoreleaks_reference_schema() -> SchemaSummary:
    """ICIJ Offshore Leaks public property-graph schema for onboarding studies.

    The profile is derived from the March 31, 2025 CSV package headers and
    relationship type counts. Live runs should still introspect the loaded dump
    because ICIJ periodically refreshes the package.
    """

    node_properties = [
        *[
            NodeProperty("Entity", prop, "STRING")
            for prop in [
                "node_id",
                "name",
                "original_name",
                "former_name",
                "jurisdiction",
                "jurisdiction_description",
                "company_type",
                "address",
                "internal_id",
                "incorporation_date",
                "inactivation_date",
                "struck_off_date",
                "dorm_date",
                "status",
                "service_provider",
                "ibcRUC",
                "country_codes",
                "countries",
                "sourceID",
                "valid_until",
                "note",
            ]
        ],
        *[
            NodeProperty("Officer", prop, "STRING")
            for prop in [
                "node_id",
                "name",
                "countries",
                "country_codes",
                "sourceID",
                "valid_until",
                "note",
            ]
        ],
        *[
            NodeProperty("Intermediary", prop, "STRING")
            for prop in [
                "node_id",
                "name",
                "status",
                "internal_id",
                "address",
                "countries",
                "country_codes",
                "sourceID",
                "valid_until",
                "note",
            ]
        ],
        *[
            NodeProperty("Address", prop, "STRING")
            for prop in [
                "node_id",
                "address",
                "name",
                "countries",
                "country_codes",
                "sourceID",
                "valid_until",
                "note",
            ]
        ],
        *[
            NodeProperty("Other", prop, "STRING")
            for prop in [
                "node_id",
                "name",
                "type",
                "incorporation_date",
                "struck_off_date",
                "closed_date",
                "jurisdiction",
                "jurisdiction_description",
                "countries",
                "country_codes",
                "sourceID",
                "valid_until",
                "note",
            ]
        ],
    ]
    relationship_properties = [
        RelationshipProperty(rel_type, prop, "STRING")
        for rel_type in ICIJ_REL_TYPES
        for prop in ["link", "status", "start_date", "end_date", "sourceID"]
    ]
    relationships = [
        RelationshipPattern("Officer", "officer_of", "Entity", 1711446),
        RelationshipPattern("Intermediary", "officer_of", "Entity", 7183),
        RelationshipPattern("Officer", "officer_of", "Other", 1718),
        RelationshipPattern("Officer", "officer_of", "Officer", 6),
        RelationshipPattern("Entity", "officer_of", "Entity", 3),
        RelationshipPattern("Officer", "registered_address", "Address", 484957),
        RelationshipPattern("Entity", "registered_address", "Address", 336951),
        RelationshipPattern("Intermediary", "registered_address", "Address", 9303),
        RelationshipPattern("Other", "registered_address", "Address", 888),
        RelationshipPattern("Entity", "registered_address", "Entity", 622),
        RelationshipPattern("Intermediary", "intermediary_of", "Entity", 590096),
        RelationshipPattern("Officer", "intermediary_of", "Entity", 8450),
        RelationshipPattern("Officer", "same_name_as", "Officer", 97774),
        RelationshipPattern("Entity", "same_name_as", "Entity", 4121),
        RelationshipPattern("Entity", "same_name_as", "Officer", 631),
        RelationshipPattern("Entity", "same_name_as", "Other", 552),
        RelationshipPattern("Intermediary", "same_name_as", "Officer", 494),
        RelationshipPattern("Officer", "similar", "Officer", 46398),
        RelationshipPattern("Officer", "similar", "Intermediary", 304),
        RelationshipPattern("Intermediary", "similar", "Officer", 43),
        RelationshipPattern("Intermediary", "similar", "Intermediary", 16),
        RelationshipPattern("Entity", "same_company_as", "Entity", 15523),
        RelationshipPattern("Other", "connected_to", "Entity", 10822),
        RelationshipPattern("Officer", "connected_to", "Entity", 1099),
        RelationshipPattern("Intermediary", "connected_to", "Entity", 224),
        RelationshipPattern("Entity", "same_as", "Entity", 3146),
        RelationshipPattern("Address", "same_as", "Address", 960),
        RelationshipPattern("Intermediary", "same_as", "Officer", 166),
        RelationshipPattern("Officer", "same_id_as", "Officer", 3120),
        RelationshipPattern("Officer", "underlying", "Officer", 1238),
        RelationshipPattern("Other", "underlying", "Entity", 70),
        RelationshipPattern("Entity", "similar_company_as", "Entity", 203),
        RelationshipPattern("Officer", "probably_same_officer_as", "Officer", 132),
        RelationshipPattern("Address", "same_address_as", "Address", 5),
        RelationshipPattern("Intermediary", "same_intermediary_as", "Intermediary", 4),
    ]
    return SchemaSummary(
        node_properties=node_properties,
        relationship_properties=relationship_properties,
        relationships=relationships,
        categorical_properties={
            "Entity.sourceID": [
                "Offshore Leaks",
                "Panama Papers",
                "Bahamas Leaks",
                "Paradise Papers",
                "Pandora Papers",
            ],
            "Entity.jurisdiction": ["BVI", "PAN", "SAM", "BAH", "SEY"],
            "Intermediary.status": ["ACTIVE", "SUSPENDED", "INACTIVE"],
        },
        graph_name="icij_offshoreleaks_reference",
        source="icij_csv_20250331_headers_and_relationship_counts",
    )


def _is_icij_profile(profile: str) -> bool:
    return profile.lower() in {
        "icij",
        "icij_offshoreleaks",
        "offshoreleaks",
        "offshore_leaks",
        "icij_offshore_leaks",
    }


def reference_schema(profile: str) -> SchemaSummary:
    if _is_icij_profile(profile):
        return icij_offshoreleaks_reference_schema()
    if profile.lower() in {"snb", "ldbc_snb"}:
        return snb_reference_schema()
    return finbench_reference_schema()


def default_templates(profile: str) -> list[TemplateCandidate]:
    if _is_icij_profile(profile):
        return [
            TemplateCandidate(
                category="simple_retrieval",
                template="Which offshore entities is officer '{officerName}' connected to?",
                slots={"officerName": "Officer.name"},
                rationale="Basic KYC-style lookup from a named officer to offshore entities.",
            ),
            TemplateCandidate(
                category="complex_retrieval",
                template="Which officers share a registered address with offshore entity '{entityName}'?",
                slots={"entityName": "Entity.name"},
                rationale="Multi-hop address-sharing lookup for investigative graph review.",
            ),
            TemplateCandidate(
                category="simple_aggregation",
                template="How many offshore entities are connected to officer '{officerName}'?",
                slots={"officerName": "Officer.name"},
                rationale="Count of distinct entities linked to a named officer.",
            ),
            TemplateCandidate(
                category="complex_aggregation",
                template="How many distinct officers are connected to entities in jurisdiction '{jurisdiction}'?",
                slots={"jurisdiction": "Entity.jurisdiction"},
                rationale="Jurisdiction-scoped aggregation across officer-entity links.",
            ),
            TemplateCandidate(
                category="boolean_existence",
                template="Does offshore entity '{entityName}' have a registered address?",
                slots={"entityName": "Entity.name"},
                rationale="Boolean due-diligence check for address evidence.",
            ),
            TemplateCandidate(
                category="negation_difference",
                template="Which offshore entities in jurisdiction '{jurisdiction}' do not have a registered address?",
                slots={"jurisdiction": "Entity.jurisdiction"},
                rationale="Anti-join over entity registration-address coverage.",
            ),
            TemplateCandidate(
                category="path_temporal",
                template="Which officers share offshore entities with officer '{officerName}', and when did each connection start?",
                slots={"officerName": "Officer.name"},
                rationale="Two-hop officer-entity-officer pattern with relationship dates.",
            ),
            TemplateCandidate(
                category="ranking_topk",
                template="Which jurisdictions have the most offshore entities?",
                slots={},
                rationale="Top-k jurisdiction concentration query.",
            ),
            TemplateCandidate(
                category="ranking_topk",
                template="Which officers are connected to the most offshore entities?",
                slots={},
                rationale="Top-k officer-entity linkage query.",
            ),
        ]
    if profile.lower() in {"snb", "ldbc_snb"}:
        return [
            TemplateCandidate(
                category="simple_retrieval",
                template="Which post IDs did person with id {personId} like?",
                slots={"personId": "Person.id"},
                rationale="Basic lookup over a person-post relation.",
            ),
            TemplateCandidate(
                category="complex_retrieval",
                template="Which people are members of forums containing posts tagged '{tagName}'?",
                slots={"tagName": "Tag.name"},
                rationale="Multi-hop membership and content-tag traversal.",
            ),
            TemplateCandidate(
                category="simple_aggregation",
                template="How many posts are tagged '{tagName}'?",
                slots={"tagName": "Tag.name"},
                rationale="Simple count by content tag.",
            ),
            TemplateCandidate(
                category="complex_aggregation",
                template="How many distinct posts are in forums joined by person with id {personId}?",
                slots={"personId": "Person.id"},
                rationale="Aggregation over a person-forum membership neighborhood and forum content.",
            ),
            TemplateCandidate(
                category="boolean_existence",
                template="Does person with id {personId} like any post?",
                slots={"personId": "Person.id"},
                rationale="Boolean engagement check over person-to-post likes.",
            ),
            TemplateCandidate(
                category="negation_difference",
                template="Which people are forum members but have not liked any post?",
                slots={},
                rationale="Anti-join over membership and post-like behavior.",
            ),
            TemplateCandidate(
                category="negation_difference",
                template="Which members of forum '{forumTitle}' have not liked any post?",
                slots={"forumTitle": "Forum.title"},
                rationale="Forum-scoped anti-join over membership and post-like behavior.",
            ),
            TemplateCandidate(
                category="negation_difference",
                template="Which people who know person with id {personId} have not liked any post?",
                slots={"personId": "Person.id"},
                rationale="Person-neighborhood anti-join over social links and post-like behavior.",
            ),
            TemplateCandidate(
                category="negation_difference",
                template="Which members of forums tagged '{tagName}' have not liked any post?",
                slots={"tagName": "Tag.name"},
                rationale="Tag-scoped forum membership anti-join over post-like behavior.",
            ),
            TemplateCandidate(
                category="path_temporal",
                template="Which people are within two knows hops of person with id {personId}?",
                slots={"personId": "Person.id"},
                rationale="Social-neighborhood path query.",
            ),
            TemplateCandidate(
                category="ranking_topk",
                template="Which forum has the most members?",
                slots={},
                rationale="Ranking over forum membership counts.",
            ),
            TemplateCandidate(
                category="ranking_topk",
                template="Which person liked the most posts?",
                slots={},
                rationale="Ranking over person-to-post engagement counts.",
            ),
            TemplateCandidate(
                category="ranking_topk",
                template="Among forums tagged '{tagName}', which forum has the most members?",
                slots={"tagName": "Tag.name"},
                rationale="Tag-scoped ranking over forum membership counts.",
            ),
        ]
    return [
        TemplateCandidate(
            category="simple_retrieval",
            template="Which accounts are owned by person '{personName}'?",
            slots={"personName": "Person.personName"},
            rationale="Basic account ownership lookup.",
        ),
        TemplateCandidate(
            category="complex_retrieval",
            template="Which accounts received transfers from accounts owned by person '{personName}'?",
            slots={"personName": "Person.personName"},
            rationale="Two-hop transaction neighborhood lookup.",
        ),
        TemplateCandidate(
            category="simple_aggregation",
            template="How many accounts are owned by person '{personName}'?",
            slots={"personName": "Person.personName"},
            rationale="Simple aggregation over account ownership.",
        ),
        TemplateCandidate(
            category="complex_aggregation",
            template="What is the total transferred amount from accounts owned by person '{personName}'?",
            slots={"personName": "Person.personName"},
            rationale="Aggregation over transaction amounts.",
        ),
        TemplateCandidate(
            category="boolean_existence",
            template="Does person '{personName}' own any account that transferred money to another account?",
            slots={"personName": "Person.personName"},
            rationale="Boolean fraud-screening style existence query.",
        ),
        TemplateCandidate(
            category="boolean_existence",
            template="Does account '{accountId}' have any outgoing transfer?",
            slots={"accountId": "Account.accountId"},
            rationale="Boolean transaction-activity check for a specific account.",
        ),
        TemplateCandidate(
            category="negation_difference",
            template="Which people own accounts but have not applied for a loan?",
            slots={},
            rationale="Difference query over account ownership and loan applications.",
        ),
        TemplateCandidate(
            category="negation_difference",
            template="Which companies own accounts but have not applied for a loan?",
            slots={},
            rationale="Corporate counterpart of the ownership-minus-loan anti-join.",
        ),
        TemplateCandidate(
            category="negation_difference",
            template="Which accounts owned by person '{personName}' have not sent any transfers?",
            slots={"personName": "Person.personName"},
            rationale="Entity-scoped anti-join over account ownership and transfer activity.",
        ),
        TemplateCandidate(
            category="negation_difference",
            template="Which accounts owned by company '{companyName}' have not sent any transfers?",
            slots={"companyName": "Company.companyName"},
            rationale="Company-scoped anti-join over account ownership and transfer activity.",
        ),
        TemplateCandidate(
            category="negation_difference",
            template="Which people who own account '{accountId}' have not applied for a loan?",
            slots={"accountId": "Account.accountId"},
            rationale="Account-grounded anti-join over person ownership and loan applications.",
        ),
        TemplateCandidate(
            category="negation_difference",
            template="Which companies that own account '{accountId}' have not applied for a loan?",
            slots={"accountId": "Account.accountId"},
            rationale="Account-grounded anti-join over company ownership and loan applications.",
        ),
        TemplateCandidate(
            category="path_temporal",
            template="Which accounts are within two transfer hops of account '{accountId}'?",
            slots={"accountId": "Account.accountId"},
            rationale="Transaction path-neighborhood query.",
        ),
        TemplateCandidate(
            category="ranking_topk",
            template="Which account sent the highest total transfer amount?",
            slots={},
            rationale="Top-k transaction-risk query.",
        ),
        TemplateCandidate(
            category="ranking_topk",
            template="Which account received the highest total withdrawal amount?",
            slots={},
            rationale="Top-k account exposure query over withdrawal relationships.",
        ),
        TemplateCandidate(
            category="ranking_topk",
            template="For accounts owned by person '{personName}', which account sent the highest total transfer amount?",
            slots={"personName": "Person.personName"},
            rationale="Entity-scoped top-k transaction-risk query.",
        ),
        TemplateCandidate(
            category="ranking_topk",
            template="For accounts owned by company '{companyName}', which account sent the highest total transfer amount?",
            slots={"companyName": "Company.companyName"},
            rationale="Company-scoped top-k transaction-risk query.",
        ),
        TemplateCandidate(
            category="ranking_topk",
            template="For accounts owned by person '{personName}', which account received the highest total withdrawal amount?",
            slots={"personName": "Person.personName"},
            rationale="Entity-scoped top-k withdrawal exposure query.",
        ),
        TemplateCandidate(
            category="ranking_topk",
            template="Among accounts of type '{accountType}', which account sent the highest total transfer amount?",
            slots={"accountType": "Account.accountType"},
            rationale="Categorical top-k transaction-risk query.",
        ),
        TemplateCandidate(
            category="path_temporal",
            template="Which accounts can receive money within two transfer hops from accounts owned by person '{personName}'?",
            slots={"personName": "Person.personName"},
            rationale="Entity-grounded transaction path-neighborhood query.",
        ),
    ]


def _cypher_literal(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    escaped = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def _binding(bindings: dict[str, object] | None, slot: str, fallback: str) -> str:
    if bindings and bindings.get(slot) is not None:
        return _cypher_literal(bindings[slot])
    return _cypher_literal(fallback)


def default_reverse_cypher_for_template(template: TemplateCandidate, limit: int = 50) -> str | None:
    text = template.template
    if not template.slots:
        return None
    if "accounts are owned by person" in text:
        return (
            "MATCH (p:Person)-[:OWN_ACCOUNT]->(:Account) "
            f"RETURN DISTINCT p.personName AS personName LIMIT {limit}"
        )
    if "received transfers from accounts owned by person" in text:
        return (
            "MATCH (p:Person)-[:OWN_ACCOUNT]->(:Account)-[:TRANSFER_TO]->(:Account) "
            f"RETURN DISTINCT p.personName AS personName LIMIT {limit}"
        )
    if "How many accounts are owned by person" in text:
        return (
            "MATCH (p:Person)-[:OWN_ACCOUNT]->(:Account) "
            f"RETURN DISTINCT p.personName AS personName LIMIT {limit}"
        )
    if "total transferred amount" in text:
        return (
            "MATCH (p:Person)-[:OWN_ACCOUNT]->(:Account)-[:TRANSFER_TO]->(:Account) "
            f"RETURN DISTINCT p.personName AS personName LIMIT {limit}"
        )
    if "Does person with id" in text and "like any post" in text:
        return (
            "MATCH (p:Person)-[:LIKES]->(:Post) "
            f"RETURN DISTINCT p.id AS personId LIMIT {limit}"
        )
    if "Does person" in text:
        return (
            "MATCH (p:Person)-[:OWN_ACCOUNT]->(:Account)-[:TRANSFER_TO]->(:Account) "
            f"RETURN DISTINCT p.personName AS personName LIMIT {limit}"
        )
    if "Does account" in text and "outgoing transfer" in text:
        return (
            "MATCH (src:Account)-[:TRANSFER_TO]->(:Account) "
            f"RETURN DISTINCT src.accountId AS accountId LIMIT {limit}"
        )
    if "accounts owned by person" in text and "have not sent any transfers" in text:
        return (
            "MATCH (p:Person)-[:OWN_ACCOUNT]->(a:Account) "
            "WHERE NOT (a)-[:TRANSFER_TO]->(:Account) "
            f"RETURN DISTINCT p.personName AS personName LIMIT {limit}"
        )
    if "accounts owned by company" in text and "have not sent any transfers" in text:
        return (
            "MATCH (c:Company)-[:OWN_ACCOUNT]->(a:Account) "
            "WHERE NOT (a)-[:TRANSFER_TO]->(:Account) "
            f"RETURN DISTINCT c.companyName AS companyName LIMIT {limit}"
        )
    if "people who own account" in text and "have not applied for a loan" in text:
        return (
            "MATCH (p:Person)-[:OWN_ACCOUNT]->(a:Account) "
            "WHERE NOT (p)-[:APPLY_LOAN]->(:Loan) "
            f"RETURN DISTINCT a.accountId AS accountId LIMIT {limit}"
        )
    if "companies that own account" in text and "have not applied for a loan" in text:
        return (
            "MATCH (c:Company)-[:OWN_ACCOUNT]->(a:Account) "
            "WHERE NOT (c)-[:APPLY_LOAN]->(:Loan) "
            f"RETURN DISTINCT a.accountId AS accountId LIMIT {limit}"
        )
    if "within two transfer hops from accounts owned by person" in text:
        return (
            "MATCH (p:Person)-[:OWN_ACCOUNT]->(:Account)-[:TRANSFER_TO]->(:Account) "
            f"RETURN DISTINCT p.personName AS personName LIMIT {limit}"
        )
    if "For accounts owned by person" in text and "highest total transfer amount" in text:
        return (
            "MATCH (p:Person)-[:OWN_ACCOUNT]->(:Account)-[:TRANSFER_TO]->(:Account) "
            f"RETURN DISTINCT p.personName AS personName LIMIT {limit}"
        )
    if "For accounts owned by company" in text and "highest total transfer amount" in text:
        return (
            "MATCH (c:Company)-[:OWN_ACCOUNT]->(:Account)-[:TRANSFER_TO]->(:Account) "
            f"RETURN DISTINCT c.companyName AS companyName LIMIT {limit}"
        )
    if "For accounts owned by person" in text and "highest total withdrawal amount" in text:
        return (
            "MATCH (p:Person)-[:OWN_ACCOUNT]->(:Account)<-[:WITHDRAW_TO]-(:Account) "
            f"RETURN DISTINCT p.personName AS personName LIMIT {limit}"
        )
    if "accounts of type" in text and "highest total transfer amount" in text:
        return (
            "MATCH (src:Account)-[:TRANSFER_TO]->(:Account) "
            "WHERE src.accountType IS NOT NULL "
            f"RETURN DISTINCT src.accountType AS accountType LIMIT {limit}"
        )
    if "within two transfer hops" in text:
        return (
            "MATCH (src:Account)-[:TRANSFER_TO]->(:Account) "
            f"RETURN DISTINCT src.accountId AS accountId LIMIT {limit}"
        )
    if "posts did" in text or "post IDs did" in text:
        return (
            "MATCH (p:Person)-[:LIKES]->(:Post) "
            f"RETURN DISTINCT p.id AS personId LIMIT {limit}"
        )
    if "distinct posts are in forums joined by person" in text:
        return (
            "MATCH (:Forum)-[:HAS_MEMBER]->(p:Person) "
            f"RETURN DISTINCT p.id AS personId LIMIT {limit}"
        )
    if "within two knows hops" in text:
        return (
            "MATCH (p:Person)-[:KNOWS]->(:Person) "
            f"RETURN DISTINCT p.id AS personId LIMIT {limit}"
        )
    if "people who know person" in text and "have not liked any post" in text:
        return (
            "MATCH (src:Person)-[:KNOWS]->(p:Person) "
            "WHERE NOT (p)-[:LIKES]->(:Post) "
            f"RETURN DISTINCT src.id AS personId LIMIT {limit}"
        )
    if "members of forums tagged" in text and "have not liked any post" in text:
        return (
            "MATCH (forum:Forum)-[:HAS_TAG]->(tag:Tag) "
            "MATCH (forum)-[:HAS_MEMBER]->(p:Person) "
            "WHERE NOT (p)-[:LIKES]->(:Post) "
            f"RETURN DISTINCT tag.name AS tagName LIMIT {limit}"
        )
    if "members of forum" in text and "have not liked any post" in text:
        return (
            "MATCH (forum:Forum)-[:HAS_MEMBER]->(p:Person) "
            "WHERE NOT (p)-[:LIKES]->(:Post) "
            f"RETURN DISTINCT forum.title AS forumTitle LIMIT {limit}"
        )
    if "forums tagged" in text and "forum has the most members" in text:
        return (
            "MATCH (:Forum)-[:HAS_TAG]->(tag:Tag) "
            f"RETURN DISTINCT tag.name AS tagName LIMIT {limit}"
        )
    if "members of forums" in text or "How many posts" in text:
        return (
            "MATCH (:Post)-[:HAS_TAG]->(tag:Tag) "
            f"RETURN DISTINCT tag.name AS tagName LIMIT {limit}"
        )
    if "offshore entities is officer" in text:
        return (
            "MATCH (o:Officer)-[:officer_of]->(:Entity) "
            f"RETURN DISTINCT o.name AS officerName LIMIT {limit}"
        )
    if "share a registered address with offshore entity" in text:
        return (
            "MATCH (:Officer)-[:registered_address]->(addr:Address)<-[:registered_address]-(e:Entity) "
            f"RETURN DISTINCT e.name AS entityName LIMIT {limit}"
        )
    if "How many offshore entities are connected to officer" in text:
        return (
            "MATCH (o:Officer)-[:officer_of]->(:Entity) "
            f"RETURN DISTINCT o.name AS officerName LIMIT {limit}"
        )
    if "distinct officers are connected to entities in jurisdiction" in text:
        return (
            "MATCH (:Officer)-[:officer_of]->(e:Entity) "
            "WHERE e.jurisdiction IS NOT NULL "
            f"RETURN DISTINCT e.jurisdiction AS jurisdiction LIMIT {limit}"
        )
    if "Does offshore entity" in text and "registered address" in text:
        return (
            "MATCH (e:Entity)-[:registered_address]->(:Address) "
            f"RETURN DISTINCT e.name AS entityName LIMIT {limit}"
        )
    if "do not have a registered address" in text:
        return (
            "MATCH (e:Entity) "
            "WHERE e.jurisdiction IS NOT NULL AND NOT (e)-[:registered_address]->(:Address) "
            f"RETURN DISTINCT e.jurisdiction AS jurisdiction LIMIT {limit}"
        )
    if "share offshore entities with officer" in text:
        return (
            "MATCH (src:Officer)-[:officer_of]->(:Entity)<-[:officer_of]-(dst:Officer) "
            "WHERE src.name IS NOT NULL AND dst <> src "
            f"RETURN DISTINCT src.name AS officerName LIMIT {limit}"
        )
    return None


def default_cypher_for_template(
    template: TemplateCandidate,
    limit: int = 50,
    bindings: dict[str, object] | None = None,
) -> str:
    text = template.template
    if "How many accounts are owned by person" in text:
        person_name = _binding(bindings, "personName", "personName")
        return (
            f"MATCH (p:Person {{personName: {person_name}}})-[:OWN_ACCOUNT]->(a:Account) "
            "RETURN DISTINCT COUNT(DISTINCT a) AS AccountCount"
        )
    if "total transferred amount" in text:
        person_name = _binding(bindings, "personName", "personName")
        return (
            f"MATCH (p:Person {{personName: {person_name}}})-[:OWN_ACCOUNT]->(src:Account)-[t:TRANSFER_TO]->(:Account) "
            "RETURN DISTINCT SUM(t.amount) AS TotalTransferredAmount"
        )
    if "Does person with id" in text and "like any post" in text:
        person_id = _binding(bindings, "personId", "personId")
        return (
            f"MATCH (p:Person {{id: {person_id}}}) "
            "OPTIONAL MATCH (p)-[:LIKES]->(post:Post) "
            "RETURN DISTINCT COUNT(post) > 0 AS LikesAnyPost"
        )
    if "Does person" in text:
        person_name = _binding(bindings, "personName", "personName")
        return (
            f"MATCH (p:Person {{personName: {person_name}}}) "
            "OPTIONAL MATCH (p)-[:OWN_ACCOUNT]->(src:Account)-[:TRANSFER_TO]->(dst:Account) "
            "RETURN DISTINCT COUNT(src) > 0 AS Exists"
        )
    if "Does account" in text and "outgoing transfer" in text:
        account_id = _binding(bindings, "accountId", "accountId")
        return (
            f"MATCH (src:Account {{accountId: {account_id}}}) "
            "OPTIONAL MATCH (src)-[:TRANSFER_TO]->(dst:Account) "
            "RETURN DISTINCT COUNT(dst) > 0 AS HasOutgoingTransfer"
        )
    if "have not applied for a loan" in text:
        if "people who own account" in text:
            account_id = _binding(bindings, "accountId", "accountId")
            return (
                f"MATCH (p:Person)-[:OWN_ACCOUNT]->(a:Account {{accountId: {account_id}}}) "
                "WHERE NOT (p)-[:APPLY_LOAN]->(:Loan) "
                "RETURN DISTINCT p.personId AS PersonId, p.personName AS PersonName, "
                f"a.accountId AS AccountId LIMIT {limit}"
            )
        if "companies that own account" in text:
            account_id = _binding(bindings, "accountId", "accountId")
            return (
                f"MATCH (c:Company)-[:OWN_ACCOUNT]->(a:Account {{accountId: {account_id}}}) "
                "WHERE NOT (c)-[:APPLY_LOAN]->(:Loan) "
                "RETURN DISTINCT c.companyId AS CompanyId, c.companyName AS CompanyName, "
                f"a.accountId AS AccountId LIMIT {limit}"
            )
        if "companies" in text:
            return (
                "MATCH (c:Company)-[:OWN_ACCOUNT]->(:Account) "
                "WHERE NOT (c)-[:APPLY_LOAN]->(:Loan) "
                "RETURN DISTINCT c.companyId AS CompanyId, c.companyName AS CompanyName, "
                f"c.business AS Business LIMIT {limit}"
            )
        return (
            "MATCH (p:Person)-[:OWN_ACCOUNT]->(:Account) "
            "WHERE NOT (p)-[:APPLY_LOAN]->(:Loan) "
            f"RETURN DISTINCT p.personId AS PersonId, p.personName AS PersonName LIMIT {limit}"
        )
    if "accounts owned by person" in text and "have not sent any transfers" in text:
        person_name = _binding(bindings, "personName", "personName")
        return (
            f"MATCH (p:Person {{personName: {person_name}}})-[:OWN_ACCOUNT]->(a:Account) "
            "WHERE NOT (a)-[:TRANSFER_TO]->(:Account) "
            "RETURN DISTINCT a.accountId AS AccountId, a.accountType AS AccountType, "
            f"a.isBlocked AS IsBlocked LIMIT {limit}"
        )
    if "accounts owned by company" in text and "have not sent any transfers" in text:
        company_name = _binding(bindings, "companyName", "companyName")
        return (
            f"MATCH (c:Company {{companyName: {company_name}}})-[:OWN_ACCOUNT]->(a:Account) "
            "WHERE NOT (a)-[:TRANSFER_TO]->(:Account) "
            "RETURN DISTINCT a.accountId AS AccountId, a.accountType AS AccountType, "
            f"a.isBlocked AS IsBlocked LIMIT {limit}"
        )
    if "within two transfer hops from accounts owned by person" in text:
        person_name = _binding(bindings, "personName", "personName")
        return (
            f"MATCH (p:Person {{personName: {person_name}}})-[:OWN_ACCOUNT]->(src:Account)-[:TRANSFER_TO*1..2]->(dst:Account) "
            "RETURN DISTINCT dst.accountId AS AccountId, dst.accountType AS AccountType, "
            f"dst.isBlocked AS IsBlocked LIMIT {limit}"
        )
    if "within two transfer hops" in text:
        account_id = _binding(bindings, "accountId", "accountId")
        return (
            f"MATCH (src:Account {{accountId: {account_id}}})-[:TRANSFER_TO*1..2]->(dst:Account) "
            "RETURN DISTINCT dst.accountId AS AccountId, dst.accountType AS AccountType, "
            f"dst.isBlocked AS IsBlocked LIMIT {limit}"
        )
    if "For accounts owned by person" in text and "highest total transfer amount" in text:
        person_name = _binding(bindings, "personName", "personName")
        return (
            f"MATCH (p:Person {{personName: {person_name}}})-[:OWN_ACCOUNT]->(src:Account)-[t:TRANSFER_TO]->(:Account) "
            "WITH src, SUM(t.amount) AS totalAmount "
            "RETURN DISTINCT src.accountId AS AccountId, src.accountType AS AccountType, "
            "src.isBlocked AS IsBlocked, totalAmount "
            "ORDER BY totalAmount DESC LIMIT 1"
        )
    if "For accounts owned by company" in text and "highest total transfer amount" in text:
        company_name = _binding(bindings, "companyName", "companyName")
        return (
            f"MATCH (c:Company {{companyName: {company_name}}})-[:OWN_ACCOUNT]->(src:Account)-[t:TRANSFER_TO]->(:Account) "
            "WITH src, SUM(t.amount) AS totalAmount "
            "RETURN DISTINCT src.accountId AS AccountId, src.accountType AS AccountType, "
            "src.isBlocked AS IsBlocked, totalAmount "
            "ORDER BY totalAmount DESC LIMIT 1"
        )
    if "For accounts owned by person" in text and "highest total withdrawal amount" in text:
        person_name = _binding(bindings, "personName", "personName")
        return (
            f"MATCH (p:Person {{personName: {person_name}}})-[:OWN_ACCOUNT]->(dst:Account)<-[w:WITHDRAW_TO]-(:Account) "
            "WITH dst, SUM(w.amount) AS totalWithdrawn "
            "RETURN DISTINCT dst.accountId AS AccountId, dst.accountType AS AccountType, "
            "dst.isBlocked AS IsBlocked, totalWithdrawn "
            "ORDER BY totalWithdrawn DESC LIMIT 1"
        )
    if "accounts of type" in text and "highest total transfer amount" in text:
        account_type = _binding(bindings, "accountType", "accountType")
        return (
            f"MATCH (src:Account {{accountType: {account_type}}})-[t:TRANSFER_TO]->(:Account) "
            "WITH src, SUM(t.amount) AS totalAmount "
            "RETURN DISTINCT src.accountId AS AccountId, src.accountType AS AccountType, "
            "src.isBlocked AS IsBlocked, totalAmount "
            "ORDER BY totalAmount DESC LIMIT 1"
        )
    if "highest total transfer amount" in text:
        return (
            "MATCH (src:Account)-[t:TRANSFER_TO]->(:Account) "
            "WITH src, SUM(t.amount) AS totalAmount "
            "RETURN DISTINCT src.accountId AS AccountId, src.accountType AS AccountType, "
            "src.isBlocked AS IsBlocked, totalAmount "
            "ORDER BY totalAmount DESC LIMIT 1"
        )
    if "highest total withdrawal amount" in text:
        return (
            "MATCH (:Account)-[w:WITHDRAW_TO]->(dst:Account) "
            "WITH dst, SUM(w.amount) AS totalWithdrawn "
            "RETURN DISTINCT dst.accountId AS AccountId, dst.accountType AS AccountType, "
            "dst.isBlocked AS IsBlocked, totalWithdrawn "
            "ORDER BY totalWithdrawn DESC LIMIT 1"
        )
    if "How many posts" in text:
        tag_name = _binding(bindings, "tagName", "tagName")
        return (
            f"MATCH (post:Post)-[:HAS_TAG]->(tag:Tag {{name: {tag_name}}}) "
            "RETURN DISTINCT COUNT(DISTINCT post) AS PostCount"
        )
    if "distinct posts are in forums joined by person" in text:
        person_id = _binding(bindings, "personId", "personId")
        return (
            f"MATCH (forum:Forum)-[:HAS_MEMBER]->(p:Person {{id: {person_id}}}) "
            "MATCH (forum)-[:CONTAINER_OF]->(post:Post) "
            "RETURN DISTINCT COUNT(DISTINCT post) AS JoinedForumPostCount"
        )
    if "forum members but have not liked any post" in text:
        return (
            "MATCH (:Forum)-[:HAS_MEMBER]->(p:Person) "
            "WHERE NOT (p)-[:LIKES]->(:Post) "
            f"RETURN DISTINCT p.id AS PersonId, p.firstName AS FirstName, p.lastName AS LastName LIMIT {limit}"
        )
    if "people who know person" in text and "have not liked any post" in text:
        person_id = _binding(bindings, "personId", "personId")
        return (
            f"MATCH (src:Person {{id: {person_id}}})-[:KNOWS]->(p:Person) "
            "WHERE NOT (p)-[:LIKES]->(:Post) "
            f"RETURN DISTINCT p.id AS PersonId, p.firstName AS FirstName, p.lastName AS LastName LIMIT {limit}"
        )
    if "members of forums tagged" in text and "have not liked any post" in text:
        tag_name = _binding(bindings, "tagName", "tagName")
        return (
            f"MATCH (forum:Forum)-[:HAS_TAG]->(:Tag {{name: {tag_name}}}) "
            "MATCH (forum)-[:HAS_MEMBER]->(p:Person) "
            "WHERE NOT (p)-[:LIKES]->(:Post) "
            f"RETURN DISTINCT p.id AS PersonId, p.firstName AS FirstName, p.lastName AS LastName LIMIT {limit}"
        )
    if "members of forum" in text and "have not liked any post" in text:
        forum_title = _binding(bindings, "forumTitle", "forumTitle")
        return (
            f"MATCH (forum:Forum {{title: {forum_title}}})-[:HAS_MEMBER]->(p:Person) "
            "WHERE NOT (p)-[:LIKES]->(:Post) "
            f"RETURN DISTINCT p.id AS PersonId, p.firstName AS FirstName, p.lastName AS LastName LIMIT {limit}"
        )
    if "within two knows hops" in text:
        person_id = _binding(bindings, "personId", "personId")
        return (
            f"MATCH (src:Person {{id: {person_id}}})-[:KNOWS*1..2]->(dst:Person) "
            f"RETURN DISTINCT dst.id AS PersonId, dst.firstName AS FirstName, dst.lastName AS LastName LIMIT {limit}"
        )
    if "forum has the most members" in text:
        if "forums tagged" in text:
            tag_name = _binding(bindings, "tagName", "tagName")
            return (
                f"MATCH (forum:Forum)-[:HAS_TAG]->(tag:Tag {{name: {tag_name}}}) "
                "MATCH (forum)-[:HAS_MEMBER]->(person:Person) "
                "WITH forum, COUNT(DISTINCT person) AS memberCount "
                "RETURN DISTINCT forum.title AS ForumTitle, memberCount "
                "ORDER BY memberCount DESC LIMIT 1"
            )
        return (
            "MATCH (forum:Forum)-[:HAS_MEMBER]->(person:Person) "
            "WITH forum, COUNT(DISTINCT person) AS memberCount "
            "RETURN DISTINCT forum.title AS ForumTitle, memberCount "
            "ORDER BY memberCount DESC LIMIT 1"
        )
    if "person liked the most posts" in text:
        return (
            "MATCH (person:Person)-[:LIKES]->(post:Post) "
            "WITH person, COUNT(DISTINCT post) AS likedPostCount "
            "RETURN DISTINCT person.id AS PersonId, person.firstName AS FirstName, "
            "person.lastName AS LastName, likedPostCount "
            "ORDER BY likedPostCount DESC LIMIT 1"
        )
    if "accounts are owned by person" in text:
        person_name = _binding(bindings, "personName", "personName")
        return (
            f"MATCH (p:Person {{personName: {person_name}}})-[:OWN_ACCOUNT]->(a:Account) "
            "RETURN DISTINCT a.accountId AS AccountId, a.accountType AS AccountType, "
            f"a.isBlocked AS IsBlocked LIMIT {limit}"
        )
    if "received transfers from accounts owned by person" in text:
        person_name = _binding(bindings, "personName", "personName")
        return (
            f"MATCH (p:Person {{personName: {person_name}}})-[:OWN_ACCOUNT]->(src:Account)-[:TRANSFER_TO]->(dst:Account) "
            "RETURN DISTINCT dst.accountId AS AccountId, dst.accountType AS AccountType, "
            f"dst.isBlocked AS IsBlocked LIMIT {limit}"
        )
    if "posts did" in text or "post IDs did" in text:
        person_id = _binding(bindings, "personId", "personId")
        return (
            f"MATCH (p:Person {{id: {person_id}}})-[:LIKES]->(post:Post) "
            f"RETURN DISTINCT post.id AS PostId LIMIT {limit}"
        )
    if "members of forums" in text:
        tag_name = _binding(bindings, "tagName", "tagName")
        return (
            "MATCH (forum:Forum)-[:HAS_MEMBER]->(p:Person), "
            f"(forum)-[:CONTAINER_OF]->(post:Post)-[:HAS_TAG]->(tag:Tag {{name: {tag_name}}}) "
            f"RETURN DISTINCT p.id AS PersonId LIMIT {limit}"
        )
    if "Which offshore entities is officer" in text:
        officer_name = _binding(bindings, "officerName", "officerName")
        return (
            f"MATCH (o:Officer {{name: {officer_name}}})-[r:officer_of]->(e:Entity) "
            "RETURN DISTINCT e.node_id AS EntityId, e.name AS EntityName, "
            f"e.jurisdiction AS Jurisdiction, r.link AS Link LIMIT {limit}"
        )
    if "share a registered address with offshore entity" in text:
        entity_name = _binding(bindings, "entityName", "entityName")
        return (
            f"MATCH (e:Entity {{name: {entity_name}}})-[:registered_address]->(addr:Address)<-[:registered_address]-(o:Officer) "
            "RETURN DISTINCT o.node_id AS OfficerId, o.name AS OfficerName, "
            f"addr.address AS RegisteredAddress LIMIT {limit}"
        )
    if "How many offshore entities are connected to officer" in text:
        officer_name = _binding(bindings, "officerName", "officerName")
        return (
            f"MATCH (o:Officer {{name: {officer_name}}})-[:officer_of]->(e:Entity) "
            "RETURN DISTINCT COUNT(DISTINCT e) AS OffshoreEntityCount"
        )
    if "distinct officers are connected to entities in jurisdiction" in text:
        jurisdiction = _binding(bindings, "jurisdiction", "BVI")
        return (
            f"MATCH (o:Officer)-[:officer_of]->(e:Entity {{jurisdiction: {jurisdiction}}}) "
            "RETURN DISTINCT COUNT(DISTINCT o) AS OfficerCount"
        )
    if "Does offshore entity" in text and "registered address" in text:
        entity_name = _binding(bindings, "entityName", "entityName")
        return (
            f"MATCH (e:Entity {{name: {entity_name}}}) "
            "OPTIONAL MATCH (e)-[:registered_address]->(addr:Address) "
            "RETURN DISTINCT COUNT(addr) > 0 AS HasRegisteredAddress"
        )
    if "do not have a registered address" in text:
        jurisdiction = _binding(bindings, "jurisdiction", "BVI")
        return (
            f"MATCH (e:Entity {{jurisdiction: {jurisdiction}}}) "
            "WHERE NOT (e)-[:registered_address]->(:Address) "
            "RETURN DISTINCT e.node_id AS EntityId, e.name AS EntityName, "
            f"e.jurisdiction AS Jurisdiction LIMIT {limit}"
        )
    if "share offshore entities with officer" in text:
        officer_name = _binding(bindings, "officerName", "officerName")
        return (
            f"MATCH (src:Officer {{name: {officer_name}}})-[srcRel:officer_of]->(entity:Entity)<-[dstRel:officer_of]-(dst:Officer) "
            "WHERE dst <> src "
            "RETURN DISTINCT dst.node_id AS OfficerId, dst.name AS OfficerName, "
            "entity.name AS SharedEntityName, dstRel.start_date AS ConnectionStartDate "
            f"LIMIT {limit}"
        )
    if "jurisdictions have the most offshore entities" in text:
        return (
            "MATCH (e:Entity) "
            "WHERE e.jurisdiction IS NOT NULL "
            "WITH e.jurisdiction AS jurisdiction, COUNT(DISTINCT e) AS entityCount "
            "RETURN DISTINCT jurisdiction, entityCount "
            "ORDER BY entityCount DESC LIMIT 10"
        )
    if "officers are connected to the most offshore entities" in text:
        return (
            "MATCH (o:Officer)-[:officer_of]->(e:Entity) "
            "WITH o, COUNT(DISTINCT e) AS entityCount "
            "RETURN DISTINCT o.node_id AS OfficerId, o.name AS OfficerName, entityCount "
            "ORDER BY entityCount DESC LIMIT 10"
        )
    return "MATCH (n) RETURN DISTINCT n LIMIT 1"
