#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.provenance import file_manifest


DEFAULT_INCLUDE = [
    "README.md",
    "pyproject.toml",
    "pipecypher",
    "scripts",
    "configs",
    "tests",
    "paper_emnlp2026_industry",
    "paper_emnlp2026_industry/reproducibility_README.md",
    "experiments/snapshots/20260604_review_remediation",
    "experiments/snapshots/20260604_diversity_governed_target50_reviewfix",
    "experiments/snapshots/20260604_clean_downstream_model_transfer",
    "knowledge_base/review_response_matrix.md",
    "knowledge_base/citation_verification.md",
    "knowledge_base/literature_review.md",
    "knowledge_base/enterprise_deployment_guide.md",
]
DEFAULT_EXCLUDE_PARTS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
}
DEFAULT_EXCLUDE_SUFFIXES = {
    ".aux",
    ".blg",
    ".fdb_latexmk",
    ".fls",
    ".log",
    ".out",
    ".pyc",
}
DEFAULT_EXCLUDE_FILENAMES = {
    "build_arxiv_paper.py",
    "main.pdf",
    "main.tex",
    "paper.md",
    "prepare_hf_dataset.py",
    "test_submission_bundle.py",
}
PRIVATE_TEXT_MARKERS = (
    "ds-serv6",
    "ds_serv6",
    "suraj@",
    "/Users/suraj",
    "/home/suraj",
    "Qwen/Qwen3.5-35B",
    "Qwen3.5-35B",
    "35B-A3B",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an anonymous PIPE-Cypher submission bundle.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--include", action="append", default=[])
    args = parser.parse_args()

    output = Path(args.output_dir)
    manifest = build_bundle(output, include_paths=args.include or DEFAULT_INCLUDE)
    print(json.dumps(manifest, indent=2, sort_keys=True))


def build_bundle(output_dir: Path, *, include_paths: list[str]) -> dict[str, object]:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    copied: list[Path] = []
    for rel in include_paths:
        source = PROJECT_ROOT / rel
        if not source.exists():
            continue
        target = output_dir / rel
        if source.is_dir():
            for path in source.rglob("*"):
                if _excluded(path):
                    continue
                relative = path.relative_to(PROJECT_ROOT)
                if path.is_dir():
                    (output_dir / relative).mkdir(parents=True, exist_ok=True)
                elif path.is_file():
                    if _contains_private_marker(path):
                        continue
                    (output_dir / relative).parent.mkdir(parents=True, exist_ok=True)
                    _copy_bundle_file(path, output_dir / relative)
                    copied.append(output_dir / relative)
        else:
            if _contains_private_marker(source):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            _copy_bundle_file(source, target)
            copied.append(target)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_root": "ANONYMIZED_SOURCE_ROOT",
        "output_dir": "SUBMISSION_BUNDLE_ROOT",
        "files": file_manifest(copied, root=output_dir),
        "notes": [
            "Anonymous bundle excludes git metadata, caches, and LaTeX build intermediates.",
            "Raw private benchmark artifacts should be shared separately only after redaction review.",
        ],
    }
    manifest_path = output_dir / "SUBMISSION_BUNDLE_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def _excluded(path: Path) -> bool:
    try:
        path_text = path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        path_text = path.name
    if any(marker in path_text for marker in PRIVATE_TEXT_MARKERS):
        return True
    if any(part in DEFAULT_EXCLUDE_PARTS for part in path.parts):
        return True
    if path.name in DEFAULT_EXCLUDE_FILENAMES:
        return True
    return path.suffix in DEFAULT_EXCLUDE_SUFFIXES


def _contains_private_marker(path: Path) -> bool:
    if path.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg"}:
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False
    return any(marker in text for marker in PRIVATE_TEXT_MARKERS)


def _copy_bundle_file(source: Path, target: Path) -> None:
    if source.name == "pyproject.toml":
        text = source.read_text(encoding="utf-8")
        text = _anonymize_pyproject(text)
        target.write_text(text, encoding="utf-8")
    else:
        shutil.copy2(source, target)


def _anonymize_pyproject(text: str) -> str:
    start = text.find("authors = [")
    if start == -1:
        return text
    cursor = start + len("authors = [")
    depth = 1
    while cursor < len(text):
        char = text[cursor]
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return (
                    text[:start]
                    + 'authors = [{name = "Anonymous Authors"}]'
                    + text[cursor + 1 :]
                )
        cursor += 1
    return text


if __name__ == "__main__":
    main()
