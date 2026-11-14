from pipecypher.graph_profiles import (
    default_cypher_for_template,
    default_reverse_cypher_for_template,
    default_templates,
    icij_offshoreleaks_reference_schema,
)


def test_default_reverse_binds_finbench_person_slot():
    template = next(
        item
        for item in default_templates("finbench")
        if item.category == "simple_retrieval"
    )

    reverse = default_reverse_cypher_for_template(template, limit=7)

    assert reverse is not None
    assert "RETURN DISTINCT p.personName AS personName LIMIT 7" in reverse
    assert "$personName" not in reverse


def test_default_cypher_uses_bound_literal():
    template = next(
        item
        for item in default_templates("finbench")
        if item.category == "simple_retrieval"
    )

    cypher = default_cypher_for_template(template, limit=7, bindings={"personName": "Bertrand"})

    assert "{personName: 'Bertrand'}" in cypher
    assert "'personName'" not in cypher
    assert "LIMIT 7" in cypher


def test_default_snb_simple_template_uses_unambiguous_person_id():
    template = next(
        item
        for item in default_templates("snb")
        if item.category == "simple_retrieval"
    )

    reverse = default_reverse_cypher_for_template(template, limit=3)
    cypher = default_cypher_for_template(template, limit=3, bindings={"personId": 42})

    assert "person with id" in template.template
    assert reverse is not None
    assert "p.id AS personId" in reverse
    assert "{id: 42}" in cypher


def test_default_snb_has_two_ranking_templates():
    templates = [item for item in default_templates("snb") if item.category == "ranking_topk"]

    assert len(templates) >= 3
    assert any("person liked the most posts" in item.template for item in templates)
    assert any("forums tagged" in item.template for item in templates)


def test_default_snb_covers_all_planned_categories():
    categories = {item.category for item in default_templates("snb")}

    assert {
        "simple_retrieval",
        "complex_retrieval",
        "simple_aggregation",
        "complex_aggregation",
        "boolean_existence",
        "negation_difference",
        "path_temporal",
        "ranking_topk",
    }.issubset(categories)


def test_default_snb_boolean_template_uses_person_id_not_finbench_name():
    template = next(
        item
        for item in default_templates("snb")
        if item.category == "boolean_existence"
    )

    reverse = default_reverse_cypher_for_template(template, limit=5)
    cypher = default_cypher_for_template(template, limit=5, bindings={"personId": 42})

    assert reverse is not None
    assert "p.id AS personId" in reverse
    assert "{id: 42}" in cypher
    assert "personName" not in cypher
    assert "LikesAnyPost" in cypher
    assert "OPTIONAL MATCH" in cypher
    assert "COUNT(DISTINCT p)" not in cypher


def test_default_snb_path_template_uses_knows_hops():
    template = next(
        item
        for item in default_templates("snb")
        if item.category == "path_temporal"
    )

    reverse = default_reverse_cypher_for_template(template, limit=5)
    cypher = default_cypher_for_template(template, limit=5, bindings={"personId": 42})

    assert reverse is not None
    assert "KNOWS" in reverse
    assert "KNOWS*1..2" in cypher
    assert "{id: 42}" in cypher


def test_default_snb_complex_aggregation_is_unambiguous_count():
    template = next(
        item
        for item in default_templates("snb")
        if item.category == "complex_aggregation"
    )

    reverse = default_reverse_cypher_for_template(template, limit=5)
    cypher = default_cypher_for_template(template, limit=5, bindings={"personId": 42})

    assert "distinct posts" in template.template
    assert reverse is not None
    assert "p.id AS personId" in reverse
    assert "COUNT(DISTINCT post)" in cypher
    assert "AVG" not in cypher


def test_default_snb_slotted_negation_and_ranking_templates():
    negation = next(
        item
        for item in default_templates("snb")
        if item.template.startswith("Which members of forum")
    )
    ranking = next(
        item
        for item in default_templates("snb")
        if item.category == "ranking_topk" and "forums tagged" in item.template
    )

    negation_reverse = default_reverse_cypher_for_template(negation, limit=5)
    negation_cypher = default_cypher_for_template(
        negation,
        limit=5,
        bindings={"forumTitle": "Group for Test"},
    )
    ranking_reverse = default_reverse_cypher_for_template(ranking, limit=5)
    ranking_cypher = default_cypher_for_template(
        ranking,
        limit=5,
        bindings={"tagName": "Billy_Joel"},
    )

    assert negation_reverse is not None
    assert "forum.title AS forumTitle" in negation_reverse
    assert "{title: 'Group for Test'}" in negation_cypher
    assert "WHERE NOT" in negation_cypher
    assert ranking_reverse is not None
    assert "tag.name AS tagName" in ranking_reverse
    assert "{name: 'Billy_Joel'}" in ranking_cypher


def test_default_snb_extra_slotted_negation_templates():
    knows_negation = next(
        item
        for item in default_templates("snb")
        if item.template.startswith("Which people who know person")
    )
    tag_negation = next(
        item
        for item in default_templates("snb")
        if item.template.startswith("Which members of forums tagged")
    )

    knows_reverse = default_reverse_cypher_for_template(knows_negation, limit=5)
    knows_cypher = default_cypher_for_template(
        knows_negation,
        limit=5,
        bindings={"personId": 42},
    )
    tag_reverse = default_reverse_cypher_for_template(tag_negation, limit=5)
    tag_cypher = default_cypher_for_template(
        tag_negation,
        limit=5,
        bindings={"tagName": "Billy_Joel"},
    )

    assert knows_reverse is not None
    assert "src.id AS personId" in knows_reverse
    assert "{id: 42}" in knows_cypher
    assert "KNOWS" in knows_cypher
    assert tag_reverse is not None
    assert "tag.name AS tagName" in tag_reverse
    assert "{name: 'Billy_Joel'}" in tag_cypher
    assert "HAS_TAG" in tag_cypher


def test_default_finbench_has_multiple_ranking_and_path_templates():
    ranking = [item for item in default_templates("finbench") if item.category == "ranking_topk"]
    path = [item for item in default_templates("finbench") if item.category == "path_temporal"]
    boolean = [item for item in default_templates("finbench") if item.category == "boolean_existence"]
    negation = [item for item in default_templates("finbench") if item.category == "negation_difference"]

    assert len(ranking) >= 6
    assert len(path) >= 2
    assert len(boolean) >= 2
    assert len(negation) >= 6
    assert any("withdrawal amount" in item.template for item in ranking)
    assert any("company" in item.template and "highest total transfer" in item.template for item in ranking)
    assert any("accounts of type" in item.template for item in ranking)
    assert any("accounts owned by person" in item.template for item in path)
    assert any("outgoing transfer" in item.template for item in boolean)
    assert any("companies own accounts" in item.template for item in negation)
    assert any("have not sent any transfers" in item.template for item in negation)
    assert any("company" in item.template and "have not sent any transfers" in item.template for item in negation)
    assert any("people who own account" in item.template for item in negation)


def test_default_finbench_person_path_template_uses_person_binding():
    template = next(
        item
        for item in default_templates("finbench")
        if "accounts owned by person" in item.template and item.category == "path_temporal"
    )

    reverse = default_reverse_cypher_for_template(template, limit=5)
    cypher = default_cypher_for_template(template, limit=5, bindings={"personName": "Bertrand"})

    assert reverse is not None
    assert "p.personName AS personName" in reverse
    assert "{personName: 'Bertrand'}" in cypher
    assert "*1..2" in cypher


def test_default_finbench_account_boolean_template_uses_account_binding():
    template = next(
        item
        for item in default_templates("finbench")
        if "outgoing transfer" in item.template
    )

    reverse = default_reverse_cypher_for_template(template, limit=5)
    cypher = default_cypher_for_template(template, limit=5, bindings={"accountId": "acct-1"})

    assert reverse is not None
    assert "src.accountId AS accountId" in reverse
    assert "{accountId: 'acct-1'}" in cypher
    assert "HasOutgoingTransfer" in cypher
    assert "OPTIONAL MATCH" in cypher
    assert "COUNT(DISTINCT src)" not in cypher


def test_default_finbench_person_boolean_uses_clear_optional_match():
    template = next(
        item
        for item in default_templates("finbench")
        if item.template.startswith("Does person")
    )

    cypher = default_cypher_for_template(template, limit=5, bindings={"personName": "Bertrand"})

    assert "{personName: 'Bertrand'}" in cypher
    assert "OPTIONAL MATCH" in cypher
    assert "COUNT(src) > 0 AS Exists" in cypher
    assert "COUNT(DISTINCT p)" not in cypher


def test_default_finbench_company_negation_returns_company_fields_only():
    template = next(
        item
        for item in default_templates("finbench")
        if "companies own accounts" in item.template
    )

    cypher = default_cypher_for_template(template, limit=5)

    assert "CompanyId" in cypher
    assert "CompanyName" in cypher
    assert "Business" in cypher
    assert "AccountId" not in cypher


def test_default_finbench_slotted_negation_and_ranking_templates():
    negation = next(
        item
        for item in default_templates("finbench")
        if "have not sent any transfers" in item.template
    )
    ranking = next(
        item
        for item in default_templates("finbench")
        if item.template.startswith("For accounts owned by person")
    )

    negation_reverse = default_reverse_cypher_for_template(negation, limit=5)
    negation_cypher = default_cypher_for_template(
        negation,
        limit=5,
        bindings={"personName": "Bertrand"},
    )
    ranking_reverse = default_reverse_cypher_for_template(ranking, limit=5)
    ranking_cypher = default_cypher_for_template(
        ranking,
        limit=5,
        bindings={"personName": "Bertrand"},
    )

    assert negation_reverse is not None
    assert "p.personName AS personName" in negation_reverse
    assert "{personName: 'Bertrand'}" in negation_cypher
    assert "WHERE NOT" in negation_cypher
    assert ranking_reverse is not None
    assert "p.personName AS personName" in ranking_reverse
    assert "{personName: 'Bertrand'}" in ranking_cypher
    assert "ORDER BY totalAmount DESC" in ranking_cypher


def test_default_finbench_extra_slotted_negation_templates():
    company_negation = next(
        item
        for item in default_templates("finbench")
        if item.template.startswith("Which accounts owned by company")
    )
    account_person_negation = next(
        item
        for item in default_templates("finbench")
        if item.template.startswith("Which people who own account")
    )

    company_reverse = default_reverse_cypher_for_template(company_negation, limit=5)
    company_cypher = default_cypher_for_template(
        company_negation,
        limit=5,
        bindings={"companyName": "Acme"},
    )
    account_reverse = default_reverse_cypher_for_template(account_person_negation, limit=5)
    account_cypher = default_cypher_for_template(
        account_person_negation,
        limit=5,
        bindings={"accountId": "acct-1"},
    )

    assert company_reverse is not None
    assert "c.companyName AS companyName" in company_reverse
    assert "{companyName: 'Acme'}" in company_cypher
    assert "WHERE NOT" in company_cypher
    assert account_reverse is not None
    assert "a.accountId AS accountId" in account_reverse
    assert "{accountId: 'acct-1'}" in account_cypher
    assert "APPLY_LOAN" in account_cypher


def test_default_finbench_extra_slotted_ranking_templates():
    company_ranking = next(
        item
        for item in default_templates("finbench")
        if item.template.startswith("For accounts owned by company")
    )
    type_ranking = next(
        item
        for item in default_templates("finbench")
        if item.template.startswith("Among accounts of type")
    )

    company_reverse = default_reverse_cypher_for_template(company_ranking, limit=5)
    company_cypher = default_cypher_for_template(
        company_ranking,
        limit=5,
        bindings={"companyName": "Acme"},
    )
    type_reverse = default_reverse_cypher_for_template(type_ranking, limit=5)
    type_cypher = default_cypher_for_template(
        type_ranking,
        limit=5,
        bindings={"accountType": "checking"},
    )

    assert company_reverse is not None
    assert "c.companyName AS companyName" in company_reverse
    assert "{companyName: 'Acme'}" in company_cypher
    assert "ORDER BY totalAmount DESC" in company_cypher
    assert type_reverse is not None
    assert "src.accountType AS accountType" in type_reverse
    assert "{accountType: 'checking'}" in type_cypher
    assert "ORDER BY totalAmount DESC" in type_cypher


def test_icij_reference_schema_exposes_enterprise_compliance_graph_shape():
    schema = icij_offshoreleaks_reference_schema()

    assert {"Entity", "Officer", "Intermediary", "Address", "Other"}.issubset(schema.labels)
    assert {"officer_of", "registered_address", "intermediary_of"}.issubset(
        schema.relationship_types
    )
    assert schema.has_relationship("Officer", "officer_of", "Entity")
    assert schema.has_relationship("Entity", "registered_address", "Address")
    assert "name" in schema.properties_for_label("Officer")
    assert "jurisdiction" in schema.properties_for_label("Entity")
    assert "start_date" in schema.properties_for_relationship("officer_of")


def test_default_icij_covers_all_planned_categories():
    categories = {item.category for item in default_templates("icij_offshoreleaks")}

    assert {
        "simple_retrieval",
        "complex_retrieval",
        "simple_aggregation",
        "complex_aggregation",
        "boolean_existence",
        "negation_difference",
        "path_temporal",
        "ranking_topk",
    }.issubset(categories)


def test_default_icij_slotted_templates_use_exact_literals_and_context_returns():
    simple = next(
        item
        for item in default_templates("icij_offshoreleaks")
        if item.category == "simple_retrieval"
    )
    path = next(
        item
        for item in default_templates("icij_offshoreleaks")
        if item.category == "path_temporal"
    )

    simple_reverse = default_reverse_cypher_for_template(simple, limit=5)
    simple_cypher = default_cypher_for_template(
        simple,
        limit=5,
        bindings={"officerName": "KIM SOO IN"},
    )
    path_reverse = default_reverse_cypher_for_template(path, limit=5)
    path_cypher = default_cypher_for_template(
        path,
        limit=5,
        bindings={"officerName": "KIM SOO IN"},
    )

    assert simple_reverse is not None
    assert "trim(o.name) AS officerName" in simple_reverse
    assert "trim(o.name) = 'KIM SOO IN'" in simple_cypher
    assert "EntityName" in simple_cypher
    assert "Jurisdiction" in simple_cypher
    assert "RETURN DISTINCT" in simple_cypher
    assert path_reverse is not None
    assert "officer_of" in path_reverse
    assert "trim(src.name) AS officerName" in path_reverse
    assert "trim(src.name) = 'KIM SOO IN'" in path_cypher
    assert "ConnectionStartDate" in path_cypher
    assert "dst <> src" in path_cypher


def test_default_icij_jurisdiction_fallback_respects_categorical_values():
    aggregation = next(
        item
        for item in default_templates("icij_offshoreleaks")
        if item.category == "complex_aggregation"
    )
    negation = next(
        item
        for item in default_templates("icij_offshoreleaks")
        if item.category == "negation_difference"
    )

    aggregation_cypher = default_cypher_for_template(aggregation, limit=5, bindings={})
    negation_cypher = default_cypher_for_template(negation, limit=5, bindings={})

    assert "{jurisdiction: 'BVI'}" in aggregation_cypher
    assert "{jurisdiction: 'BVI'}" in negation_cypher
