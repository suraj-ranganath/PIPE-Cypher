from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .io import read_jsonl


SNAPSHOT_VERSION = "1.0"


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_artifact_snapshot(
    *,
    export_dir: str | Path,
    output_dir: str | Path,
    source_export_dir: str | None = None,
    sample_per_graph_category: int = 1,
) -> dict[str, Any]:
    if sample_per_graph_category < 1:
        raise ValueError("sample_per_graph_category must be >= 1")

    export_path = Path(export_dir)
    if not export_path.exists():
        raise FileNotFoundError(export_path)

    manifest = _read_json(export_path / "manifest.json")
    stats = _read_json(export_path / "stats.json")
    examples = read_jsonl(export_path / "all.jsonl")
    sample_examples = select_sample_examples(
        examples,
        per_graph_category=sample_per_graph_category,
    )

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    sample_path = out / "sample_examples.json"
    sample_path.write_text(
        json.dumps(sample_examples, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    snapshot = {
        "snapshot_version": SNAPSHOT_VERSION,
        "source_export_dir": source_export_dir or str(export_path),
        "source_export_created_at": manifest.get("created_at"),
        "source_manifest_sha256": manifest.get("sha256"),
        "total_examples": manifest.get("total_examples", stats.get("total")),
        "split_counts": manifest.get("split_counts", stats.get("by_split", {})),
        "stats": stats,
        "file_checksums": _export_file_checksums(export_path),
        "sample": {
            "selection": "stable-id order within each graph_profile/category cell",
            "per_graph_category": sample_per_graph_category,
            "count": len(sample_examples),
            "by_graph_category": dict(
                sorted(
                    Counter(
                        f"{row.get('graph_profile')}::{row.get('category')}"
                        for row in sample_examples
                    ).items()
                )
            ),
            "path": "sample_examples.json",
            "sha256": sha256_file(sample_path),
        },
    }
    (out / "manifest.json").write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out / "README.md").write_text(_snapshot_readme(snapshot), encoding="utf-8")
    return snapshot


def select_sample_examples(
    examples: list[dict[str, Any]],
    *,
    per_graph_category: int = 1,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in examples:
        key = (str(row.get("graph_profile")), str(row.get("category")))
        groups.setdefault(key, []).append(row)

    sample: list[dict[str, Any]] = []
    for key in sorted(groups):
        ordered = sorted(groups[key], key=lambda row: str(row.get("id", "")))
        sample.extend(ordered[:per_graph_category])
    return sample


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _export_file_checksums(export_path: Path) -> dict[str, dict[str, Any]]:
    checksums: dict[str, dict[str, Any]] = {}
    export_names = (
        "manifest.json",
        "stats.json",
        "all.jsonl",
        "train.jsonl",
        "dev.jsonl",
        "test.jsonl",
    )
    for name in export_names:
        path = export_path / name
        if path.exists():
            checksums[name] = {
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
    return checksums


def _snapshot_readme(snapshot: dict[str, Any]) -> str:
    total = snapshot.get("total_examples")
    source = snapshot.get("source_export_dir")
    source_sha = snapshot.get("source_manifest_sha256")
    sample = snapshot.get("sample", {})
    return (
        "# Full Qwen3.5-9B Benchmark Snapshot\n\n"
        "This directory is a lightweight, tracked snapshot of an ignored full benchmark export. "
        "The full JSONL files remain under `artifacts/` or private experiment storage; they "
        "are not committed because generated artifacts can grow quickly.\n\n"
        f"- Source export: `{source}`\n"
        f"- Total accepted examples: `{total}`\n"
        f"- Canonical export SHA-256: `{source_sha}`\n"
        f"- Representative sample: `{sample.get('count')}` examples in "
        "`sample_examples.json`, selected by stable ID within each graph/category cell.\n\n"
        "Use `manifest.json` to verify file sizes, split counts, aggregate statistics, and "
        "checksums for the full local export.\n"
    )
