from pathlib import Path

from scripts.build_submission_bundle import DEFAULT_INCLUDE, build_bundle


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


def test_default_submission_bundle_includes_clean_evidence_snapshots():
    assert "experiments/snapshots/20260604_review_remediation" in DEFAULT_INCLUDE
    assert "experiments/snapshots/20260604_diversity_governed_target50_reviewfix" in DEFAULT_INCLUDE
    assert "experiments/snapshots/20260604_clean_downstream_model_transfer" in DEFAULT_INCLUDE
