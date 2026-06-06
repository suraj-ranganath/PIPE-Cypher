#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.provenance import file_manifest, sha256_file
from scripts.build_submission_bundle import DEFAULT_INCLUDE, build_bundle


DEFAULT_BENCHMARK_EXPORTS = {
    "finbench_snb_full_qwen9b": "artifacts/benchmarks/20260604_live_full_qwen9b_reviewfix",
    "icij_offshoreleaks_target100": "artifacts/benchmarks/20260602_icij_offshoreleaks_target100",
}

BENCHMARK_FILES = ("all.jsonl", "train.jsonl", "dev.jsonl", "test.jsonl", "stats.json", "manifest.json")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the anonymous ACL/EMNLP supplementary code and benchmark-data zip."
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--zip-path")
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        help="Additional code/documentation path to include in the anonymous bundle.",
    )
    args = parser.parse_args()

    manifest = build_acl_supplement(
        Path(args.output_dir),
        zip_path=Path(args.zip_path) if args.zip_path else None,
        extra_include=args.include,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


def build_acl_supplement(
    output_dir: Path,
    *,
    zip_path: Path | None = None,
    extra_include: list[str] | None = None,
) -> dict[str, object]:
    include_paths = list(DEFAULT_INCLUDE)
    include_paths.extend(extra_include or [])
    bundle_manifest = build_bundle(output_dir, include_paths=include_paths)

    data_dir = output_dir / "data" / "benchmarks"
    copied_data: list[Path] = []
    benchmark_summaries: dict[str, dict[str, object]] = {}
    for name, rel_source in DEFAULT_BENCHMARK_EXPORTS.items():
        source = PROJECT_ROOT / rel_source
        if not source.exists():
            raise FileNotFoundError(f"benchmark export not found: {rel_source}")
        target = data_dir / name
        target.mkdir(parents=True, exist_ok=True)
        copied_files: list[Path] = []
        for filename in BENCHMARK_FILES:
            src_file = source / filename
            if not src_file.exists():
                raise FileNotFoundError(f"missing benchmark file: {src_file}")
            dst_file = target / filename
            shutil.copy2(src_file, dst_file)
            copied_files.append(dst_file)
            copied_data.append(dst_file)
        benchmark_summaries[name] = _benchmark_summary(target, copied_files)

    data_readme = output_dir / "data" / "README.md"
    data_readme.parent.mkdir(parents=True, exist_ok=True)
    data_readme.write_text(_data_readme(benchmark_summaries), encoding="utf-8")

    reviewer_readme = output_dir / "README_REVIEWER.md"
    reviewer_readme.write_text(_reviewer_readme(), encoding="utf-8")

    all_files = [p for p in output_dir.rglob("*") if p.is_file()]
    supplement_manifest: dict[str, object] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_root": "ANONYMIZED_SOURCE_ROOT",
        "bundle_manifest": bundle_manifest,
        "benchmark_exports": benchmark_summaries,
        "files": file_manifest(all_files, root=output_dir),
    }
    manifest_path = output_dir / "ACL_SUPPLEMENT_MANIFEST.json"
    manifest_path.write_text(
        json.dumps(supplement_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if zip_path is not None:
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        if zip_path.exists():
            zip_path.unlink()
        _zip_dir(output_dir, zip_path)
        supplement_manifest["zip_path"] = str(zip_path)
        supplement_manifest["zip_sha256"] = sha256_file(zip_path)
        manifest_path.write_text(
            json.dumps(supplement_manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return supplement_manifest


def _benchmark_summary(root: Path, copied_files: list[Path]) -> dict[str, object]:
    stats = json.loads((root / "stats.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    return {
        "path": str(root),
        "total_examples": manifest.get("total_examples", stats.get("total")),
        "split_counts": manifest.get("split_counts", stats.get("by_split")),
        "by_graph": stats.get("by_graph", {}),
        "by_category": stats.get("by_category", {}),
        "sha256": manifest.get("sha256"),
        "files": file_manifest(copied_files, root=root),
    }


def _data_readme(benchmark_summaries: dict[str, dict[str, object]]) -> str:
    rows = [
        "# PIPE-Cypher Reviewer Benchmark Data",
        "",
        "This directory contains the benchmark exports used by the anonymous submission.",
        "Each export contains `all.jsonl`, `train.jsonl`, `dev.jsonl`, `test.jsonl`,",
        "`stats.json`, and `manifest.json`.",
        "",
        "The FinBench/SNB export is the 3,000-example main benchmark. The ICIJ",
        "Offshore Leaks export is the third-graph onboarding benchmark reported in",
        "the appendix.",
        "",
        "## Exports",
        "",
    ]
    for name, summary in benchmark_summaries.items():
        rows.extend(
            [
                f"### `{name}`",
                "",
                f"- Total examples: {summary.get('total_examples')}",
                f"- Split counts: `{json.dumps(summary.get('split_counts', {}), sort_keys=True)}`",
                f"- Graph counts: `{json.dumps(summary.get('by_graph', {}), sort_keys=True)}`",
                "",
            ]
        )
    return "\n".join(rows).rstrip() + "\n"


def _reviewer_readme() -> str:
    return """# PIPE-Cypher Anonymous Supplement

This supplementary package contains the anonymous PIPE-Cypher code, tests, paper
source, reproducibility notes, and benchmark exports for reviewer inspection.

## Quick Checks

```bash
python -m pip install -e ".[dev]"
pytest
python scripts/verify_submission_package.py --paper-tex paper_emnlp2026_industry/main_acl.tex
```

## Benchmark Data

Benchmark exports are under `data/benchmarks/`. The main FinBench/SNB benchmark
contains 3,000 accepted NL-to-Cypher examples. The ICIJ Offshore Leaks export
contains the 800-example third-graph onboarding benchmark.

## Privacy And Anonymity

This package excludes git metadata, local runtime caches, private hostnames,
private filesystem paths, and raw value-bearing human-audit rows. The benchmark
graphs are public proxy graphs used for research evaluation.
"""


def _zip_dir(source_dir: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source_dir))


if __name__ == "__main__":
    main()
