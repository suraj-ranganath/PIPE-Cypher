from pathlib import Path

import pytest

from scripts.build_acl_supplement import build_acl_supplement
from scripts.build_arxiv_paper import build_arxiv_paper
from scripts.build_submission_bundle import (
    DEFAULT_INCLUDE,
    _anonymize_pyproject,
    _excluded,
    build_bundle,
)
from scripts.prepare_hf_dataset import prepare_hf_dataset


def test_build_submission_bundle_copies_requested_files_and_manifest(tmp_path: Path):
    out = tmp_path / "bundle"
    manifest = build_bundle(out, include_paths=["pyproject.toml", "pipecypher/privacy.py"])

    assert (out / "pyproject.toml").exists()
    assert (out / "pipecypher" / "privacy.py").exists()
    assert (out / "SUBMISSION_BUNDLE_MANIFEST.json").exists()
    assert manifest["files"]


def test_build_submission_bundle_keeps_model_guard_fixtures(tmp_path: Path):
    out = tmp_path / "bundle"
    manifest = build_bundle(out, include_paths=["tests/test_evidence_manifest.py"])

    assert (out / "tests" / "test_evidence_manifest.py").exists()
    assert any(row["path"] == "tests/test_evidence_manifest.py" for row in manifest["files"])


def test_build_submission_bundle_excludes_noncanonical_paper_mirrors(tmp_path: Path):
    out = tmp_path / "bundle"
    manifest = build_bundle(out, include_paths=["paper_emnlp2026_industry"])

    assert (out / "paper_emnlp2026_industry" / "main_acl.tex").exists()
    assert not (out / "paper_emnlp2026_industry" / "main.tex").exists()
    assert not (out / "paper_emnlp2026_industry" / "paper.md").exists()
    assert all(Path(row["path"]).name not in {"main.tex", "paper.md"} for row in manifest["files"])


def test_submission_bundle_excludes_private_marker_in_relative_path():
    assert _excluded(Path("scripts/run_ds_serv6_downstream_control_queue.sh"))
    assert _excluded(Path("scripts/build_arxiv_paper.py"))
    assert _excluded(Path("tests/test_submission_bundle.py"))
    assert not _excluded(Path("scripts/run_pipeline.py"))


def test_submission_bundle_anonymizes_pyproject_authors(tmp_path: Path):
    out = tmp_path / "bundle"
    build_bundle(out, include_paths=["pyproject.toml"])

    text = (out / "pyproject.toml").read_text(encoding="utf-8")
    assert 'authors = [{name = "Anonymous Authors"}]' in text
    assert "Suraj Ranganath" not in text
    assert "Anish Raghavendra" not in text


def test_anonymize_pyproject_leaves_missing_authors_unchanged():
    text = "[project]\nname = \"demo\"\n"
    assert _anonymize_pyproject(text) == text


def test_default_submission_bundle_includes_clean_evidence_snapshots():
    assert "experiments/snapshots/20260604_review_remediation" in DEFAULT_INCLUDE
    assert "experiments/snapshots/20260604_diversity_governed_target50_reviewfix" in DEFAULT_INCLUDE
    assert "experiments/snapshots/20260604_clean_downstream_model_transfer" in DEFAULT_INCLUDE


def test_build_acl_supplement_requires_benchmark_exports(tmp_path: Path):
    out = tmp_path / "acl_supplement"
    try:
        manifest = build_acl_supplement(out, zip_path=tmp_path / "acl_supplement.zip")
    except FileNotFoundError as exc:
        pytest.skip(f"local benchmark exports not available in this checkout: {exc}")

    assert (out / "README_REVIEWER.md").exists()
    assert (out / "data" / "README.md").exists()
    assert (out / "data" / "benchmarks" / "finbench_snb_full_qwen9b" / "all.jsonl").exists()
    assert (out / "data" / "benchmarks" / "icij_offshoreleaks_target100" / "all.jsonl").exists()
    assert (out / "ACL_SUPPLEMENT_MANIFEST.json").exists()
    assert (tmp_path / "acl_supplement.zip").exists()
    assert "finbench_snb_full_qwen9b" in manifest["benchmark_exports"]
    assert "icij_offshoreleaks_target100" in manifest["benchmark_exports"]


def test_prepare_hf_dataset_writes_dataset_card_when_exports_exist(tmp_path: Path):
    out = tmp_path / "hf_dataset"
    try:
        manifest = prepare_hf_dataset(out, repo_id="owner/pipecypher-test")
    except FileNotFoundError as exc:
        pytest.skip(f"local benchmark exports not available in this checkout: {exc}")

    readme = (out / "README.md").read_text(encoding="utf-8")
    assert "PIPE-Cypher Benchmarks" in readme
    assert "https://huggingface.co/datasets/owner/pipecypher-test" in readme
    assert "finbench_snb_full_qwen9b" in manifest["benchmark_exports"]


def test_build_arxiv_paper_injects_authors_and_artifact_links(tmp_path: Path):
    out = tmp_path / "paper_arxiv"
    build_arxiv_paper(
        output_dir=out,
        github_url="https://github.com/example/pipe-cypher",
        hf_dataset_url="https://huggingface.co/datasets/example/pipe-cypher",
    )

    main = (out / "main_arxiv.tex").read_text(encoding="utf-8")
    assert "\\usepackage{acl}" in main
    assert "Suraj Ranganath" in main
    assert "Anish Raghavendra" in main
    assert "suranganath@ucsd.edu" in main
    assert "https://github.com/example/pipe-cypher" in main
    assert "https://huggingface.co/datasets/example/pipe-cypher" in main
    assert not (out / "main_acl.tex").exists()
