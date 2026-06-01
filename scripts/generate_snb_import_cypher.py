#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def csv_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path}_0_0.csv"


def load_node(label_clause: str, file_path: str, id_key: str, set_body: str, *, where: str = "") -> str:
    where_clause = f"\nWITH row WHERE {where}" if where else ""
    return f"""LOAD CSV WITH HEADERS FROM '{{base}}/{file_path}_0_0.csv' AS row FIELDTERMINATOR '|'{where_clause}
MERGE (n:{label_clause} {{id: toInteger(row["{id_key}"])}})
SET {set_body};
"""


def col(name: str, value_type: str) -> str:
    return f'row["{name}:{value_type}"]'


def to_int(name: str, value_type: str = "LONG") -> str:
    return f"toInteger({col(name, value_type)})"


def rel_load(
    rel_type: str,
    file_path: str,
    start_label: str,
    start_group: str,
    end_label: str,
    end_group: str,
    set_body: str = "",
) -> str:
    set_clause = f"\nSET {set_body}" if set_body else ""
    return f"""LOAD CSV WITH HEADERS FROM '{{base}}/{file_path}_0_0.csv' AS row FIELDTERMINATOR '|'
MATCH (src:{start_label} {{id: toInteger(row[":START_ID({start_group})"])}})
MATCH (dst:{end_label} {{id: toInteger(row[":END_ID({end_group})"])}})
CREATE (src)-[r:{rel_type}]->(dst){set_clause};
"""


def build_script(base_url: str) -> str:
    node_blocks = [
        load_node(
            "Place:City",
            "static/place",
            "id:ID(Place)",
            f"n.name = {col('name', 'STRING')}, n.url = {col('url', 'STRING')}",
            where='row[":LABEL"] = "City"',
        ),
        load_node(
            "Place:Country",
            "static/place",
            "id:ID(Place)",
            f"n.name = {col('name', 'STRING')}, n.url = {col('url', 'STRING')}",
            where='row[":LABEL"] = "Country"',
        ),
        load_node(
            "Place:Continent",
            "static/place",
            "id:ID(Place)",
            f"n.name = {col('name', 'STRING')}, n.url = {col('url', 'STRING')}",
            where='row[":LABEL"] = "Continent"',
        ),
        load_node(
            "Organisation:Company",
            "static/organisation",
            "id:ID(Organisation)",
            f"n.name = {col('name', 'STRING')}, n.url = {col('url', 'STRING')}",
            where='row[":LABEL"] = "Company"',
        ),
        load_node(
            "Organisation:University",
            "static/organisation",
            "id:ID(Organisation)",
            f"n.name = {col('name', 'STRING')}, n.url = {col('url', 'STRING')}",
            where='row[":LABEL"] = "University"',
        ),
        load_node(
            "TagClass",
            "static/tagclass",
            "id:ID(TagClass)",
            f"n.name = {col('name', 'STRING')}, n.url = {col('url', 'STRING')}",
        ),
        load_node(
            "Tag",
            "static/tag",
            "id:ID(Tag)",
            f"n.name = {col('name', 'STRING')}, n.url = {col('url', 'STRING')}",
        ),
        load_node(
            "Person",
            "dynamic/person",
            "id:ID(Person)",
            (
                f"n.firstName = {col('firstName', 'STRING')}, "
                f"n.lastName = {col('lastName', 'STRING')}, "
                f"n.gender = {col('gender', 'STRING')}, "
                f"n.birthday = {to_int('birthday')}, "
                f"n.creationDate = {to_int('creationDate')}, "
                f"n.locationIP = {col('locationIP', 'STRING')}, "
                f"n.browserUsed = {col('browserUsed', 'STRING')}, "
                f"n.speaks = CASE {col('speaks', 'STRING[]')} WHEN '' THEN [] ELSE split({col('speaks', 'STRING[]')}, ';') END, "
                f"n.email = CASE {col('email', 'STRING[]')} WHEN '' THEN [] ELSE split({col('email', 'STRING[]')}, ';') END"
            ),
        ),
        load_node(
            "Forum",
            "dynamic/forum",
            "id:ID(Forum)",
            f"n.title = {col('title', 'STRING')}, n.creationDate = {to_int('creationDate')}",
        ),
        load_node(
            "Message:Post",
            "dynamic/post",
            "id:ID(Post)",
            (
                f"n.imageFile = {col('imageFile', 'STRING')}, "
                f"n.creationDate = {to_int('creationDate')}, "
                f"n.locationIP = {col('locationIP', 'STRING')}, "
                f"n.browserUsed = {col('browserUsed', 'STRING')}, "
                f"n.language = {col('language', 'STRING')}, "
                f"n.content = {col('content', 'STRING')}, "
                f"n.length = {to_int('length', 'INT')}"
            ),
        ),
        load_node(
            "Message:Comment",
            "dynamic/comment",
            "id:ID(Comment)",
            (
                f"n.creationDate = {to_int('creationDate')}, "
                f"n.locationIP = {col('locationIP', 'STRING')}, "
                f"n.browserUsed = {col('browserUsed', 'STRING')}, "
                f"n.content = {col('content', 'STRING')}, "
                f"n.length = {to_int('length', 'INT')}"
            ),
        ),
    ]
    rel_blocks = [
        rel_load("IS_PART_OF", "static/place_isPartOf_place", "Place", "Place", "Place", "Place"),
        rel_load("IS_SUBCLASS_OF", "static/tagclass_isSubclassOf_tagclass", "TagClass", "TagClass", "TagClass", "TagClass"),
        rel_load("IS_LOCATED_IN", "static/organisation_isLocatedIn_place", "Organisation", "Organisation", "Place", "Place"),
        rel_load("HAS_TYPE", "static/tag_hasType_tagclass", "Tag", "Tag", "TagClass", "TagClass"),
        rel_load("HAS_CREATOR", "dynamic/comment_hasCreator_person", "Comment", "Comment", "Person", "Person"),
        rel_load("IS_LOCATED_IN", "dynamic/comment_isLocatedIn_place", "Comment", "Comment", "Place", "Place"),
        rel_load("REPLY_OF", "dynamic/comment_replyOf_comment", "Comment", "Comment", "Comment", "Comment"),
        rel_load("REPLY_OF", "dynamic/comment_replyOf_post", "Comment", "Comment", "Post", "Post"),
        rel_load("CONTAINER_OF", "dynamic/forum_containerOf_post", "Forum", "Forum", "Post", "Post"),
        rel_load("HAS_MEMBER", "dynamic/forum_hasMember_person", "Forum", "Forum", "Person", "Person", f"r.joinDate = {to_int('joinDate')}"),
        rel_load("HAS_MODERATOR", "dynamic/forum_hasModerator_person", "Forum", "Forum", "Person", "Person"),
        rel_load("HAS_TAG", "dynamic/forum_hasTag_tag", "Forum", "Forum", "Tag", "Tag"),
        rel_load("HAS_INTEREST", "dynamic/person_hasInterest_tag", "Person", "Person", "Tag", "Tag"),
        rel_load("IS_LOCATED_IN", "dynamic/person_isLocatedIn_place", "Person", "Person", "Place", "Place"),
        rel_load("KNOWS", "dynamic/person_knows_person", "Person", "Person", "Person", "Person", f"r.creationDate = {to_int('creationDate')}"),
        rel_load("LIKES", "dynamic/person_likes_comment", "Person", "Person", "Comment", "Comment", f"r.creationDate = {to_int('creationDate')}"),
        rel_load("LIKES", "dynamic/person_likes_post", "Person", "Person", "Post", "Post", f"r.creationDate = {to_int('creationDate')}"),
        rel_load("STUDY_AT", "dynamic/person_studyAt_organisation", "Person", "Person", "Organisation", "Organisation", f"r.classYear = {to_int('classYear', 'INT')}"),
        rel_load("WORK_AT", "dynamic/person_workAt_organisation", "Person", "Person", "Organisation", "Organisation", f"r.workFrom = {to_int('workFrom', 'INT')}"),
        rel_load("HAS_CREATOR", "dynamic/post_hasCreator_person", "Post", "Post", "Person", "Person"),
        rel_load("HAS_TAG", "dynamic/comment_hasTag_tag", "Comment", "Comment", "Tag", "Tag"),
        rel_load("HAS_TAG", "dynamic/post_hasTag_tag", "Post", "Post", "Tag", "Tag"),
        rel_load("IS_LOCATED_IN", "dynamic/post_isLocatedIn_place", "Post", "Post", "Place", "Place"),
    ]
    constraints = """
CREATE CONSTRAINT person_id IF NOT EXISTS FOR (n:Person) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT forum_id IF NOT EXISTS FOR (n:Forum) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT post_id IF NOT EXISTS FOR (n:Post) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT comment_id IF NOT EXISTS FOR (n:Comment) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT tag_id IF NOT EXISTS FOR (n:Tag) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT tagclass_id IF NOT EXISTS FOR (n:TagClass) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT place_id IF NOT EXISTS FOR (n:Place) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT organisation_id IF NOT EXISTS FOR (n:Organisation) REQUIRE n.id IS UNIQUE;
"""
    body = "\n".join(node_blocks + rel_blocks)
    return (constraints + "\n" + body).replace("{base}", base_url.rstrip("/"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a Neo4j LOAD CSV script for LDBC SNB converted CSVs.")
    parser.add_argument("--csv-base-url", default="file:///snb/converted")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_script(args.csv_base_url), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
