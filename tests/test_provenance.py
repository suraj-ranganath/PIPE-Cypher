import json
from pathlib import Path

from pipecypher.provenance import (
    missing_html_table_references,
    missing_latex_inputs,
    model_provenance_from_records,
    referenced_html_tables,
    scan_forbidden_text,
)
from scripts.verify_submission_package import _flatten, verify_submission


def test_model_provenance_flags_disallowed_models(tmp_path: Path):
    records = tmp_path / "records.jsonl"
    records.write_text(
        json.dumps({"model": "Qwen/Qwen3.5-9B"}) + "\n"
        + json.dumps({"model": "Qwen/Qwen3.5-35B-A3B"}) + "\n",
        encoding="utf-8",
    )

    report = model_provenance_from_records([records], approved_models={"Qwen/Qwen3.5-9B"})

    assert report["pass"] is False
    assert report["disallowed_model_counts"] == {"Qwen/Qwen3.5-35B-A3B": 1}


def test_latex_reference_and_forbidden_text_checks(tmp_path: Path):
    tex = tmp_path / "main.tex"
    table = tmp_path / "tables_ok.tex"
    tex.write_text(r"\input{tables_ok}\input{missing_table}" + "\n", encoding="utf-8")
    table.write_text("safe", encoding="utf-8")

    missing = missing_latex_inputs(tex)

    assert len(missing) == 1
    forbidden = tmp_path / "paper.md"
    forbidden.write_text("Qwen/Qwen3.5-35B-A3B on ds-serv6", encoding="utf-8")
    hits = scan_forbidden_text([forbidden])
    assert {hit["label"] for hit in hits} >= {
        "remote host leakage",
        "larger generation model leakage",
    }


def test_verify_submission_requires_code_roots_and_clean_models(tmp_path: Path):
    tex = tmp_path / "paper_emnlp2026_industry" / "main_acl.tex"
    tex.parent.mkdir()
    tex.write_text("No inputs", encoding="utf-8")
    records = tmp_path / "records.jsonl"
    records.write_text(json.dumps({"model": "Qwen/Qwen3.5-9B"}) + "\n", encoding="utf-8")

    report = verify_submission(
        paper_tex=tex,
        package_dir=tmp_path,
        records=[records],
        approved_models={"Qwen/Qwen3.5-9B"},
    )

    assert report["pass"] is False
    assert report["missing_roots"]


def test_html_table_reference_guard_is_opt_in(tmp_path: Path):
    source = tmp_path / "paper.md"
    source.write_text("See tbl-results.html and tbl-extra.v1.html.", encoding="utf-8")
    (tmp_path / "tbl-results.html").write_text("<table></table>", encoding="utf-8")

    assert referenced_html_tables([source]) == ["tbl-extra.v1.html", "tbl-results.html"]
    assert missing_html_table_references([source], html_dir=tmp_path) == [
        str(tmp_path / "tbl-extra.v1.html")
    ]
    assert missing_html_table_references([], html_dir=tmp_path) == []


def test_verify_submission_uses_package_local_paper_tex(tmp_path: Path):
    for name in ["pipecypher", "scripts", "configs", "tests", "paper_emnlp2026_industry"]:
        (tmp_path / name).mkdir()
    tex = tmp_path / "paper_emnlp2026_industry" / "main_acl.tex"
    tex.write_text(r"\input{tables_present}" + "\n", encoding="utf-8")
    (tex.parent / "tables_present.tex").write_text("safe", encoding="utf-8")
    records = tmp_path / "records.jsonl"
    records.write_text(json.dumps({"model": "Qwen/Qwen3.5-9B"}) + "\n", encoding="utf-8")

    report = verify_submission(
        paper_tex=Path("paper_emnlp2026_industry/main_acl.tex"),
        package_dir=tmp_path,
        records=[records],
        approved_models={"Qwen/Qwen3.5-9B"},
    )

    assert report["pass"] is True


def test_verify_submission_flattens_repeated_record_arguments():
    assert _flatten([["records-a"], ["records-b", "records-c"]]) == [
        "records-a",
        "records-b",
        "records-c",
    ]
