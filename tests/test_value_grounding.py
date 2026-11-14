from pipecypher.models import SchemaSummary
from pipecypher.value_grounding import (
    ValueEntry,
    ValueGrounder,
    normalize_value_text,
    schema_categorical_entries,
    slot_hint_entries,
)


def test_normalize_value_text_handles_cypher_example_reference_surface_variants():
    assert normalize_value_text("Engineering - Platform") == "engineering platform"
    assert normalize_value_text("Risk & Compliance") == "risk and compliance"
    assert normalize_value_text("Pranit's") == "pranit"


def test_value_grounder_handles_typos_and_name_partials():
    grounder = ValueGrounder(
        [
            ValueEntry(
                label="Person",
                property="personName",
                value="Pranit Malhotra",
            )
        ]
    )

    typo_mentions = grounder.ground("Show accounts owned by Pranti Malhotra.")
    partial_mentions = grounder.ground("Show accounts owned by Malhotra.")

    assert typo_mentions[0].canonical_value == "Pranit Malhotra"
    assert typo_mentions[0].match_type == "fuzzy"
    assert partial_mentions[0].canonical_value == "Pranit Malhotra"
    assert partial_mentions[0].match_type == "partial"


def test_value_grounder_annotates_schema_path_and_canonical_value():
    grounder = ValueGrounder(
        [
            ValueEntry(
                label="Application",
                property="name",
                value="Amazon Web Services",
            )
        ],
        synonym_map={"AWS": "Amazon Web Services"},
    )

    mentions = grounder.ground("Which resources belong to AWS?")

    assert mentions[0].canonical_value == "Amazon Web Services"
    assert mentions[0].match_type == "synonym"
    assert (
        grounder.annotate_text("Which resources belong to AWS?", mentions)
        == "Which resources belong to (Application.name: Amazon Web Services)?"
    )


def test_schema_and_slot_hints_create_grounding_entries():
    schema = SchemaSummary(
        categorical_properties={"Account.accountType": ["checking", "savings"]}
    )
    hints = {"person": "Alice Zhang | Person.personName"}

    categorical = schema_categorical_entries(schema)
    slots = slot_hint_entries(hints)

    assert categorical == [
        ValueEntry(label="Account", property="accountType", value="checking"),
        ValueEntry(label="Account", property="accountType", value="savings"),
    ]
    assert slots == [ValueEntry(label="Person", property="personName", value="Alice Zhang")]

    grounder = ValueGrounder.from_schema_and_hints(schema, hints)
    mentions = grounder.ground("Which checking accounts are owned by Alice Zhang?")
    values = {mention.canonical_value for mention in mentions}

    assert values == {"checking", "Alice Zhang"}
