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
from scripts.build_acl_supplement import BENCHMARK_FILES, DEFAULT_BENCHMARK_EXPORTS


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a Hugging Face dataset folder.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--repo-id",
        default="suraj-ranganath/PIPE-Cypher-benchmarks",
        help="Intended Hugging Face dataset repo id for the dataset card.",
    )
    args = parser.parse_args()
    manifest = prepare_hf_dataset(Path(args.output_dir), repo_id=args.repo_id)
    print(json.dumps(manifest, indent=2, sort_keys=True))


def prepare_hf_dataset(output_dir: Path, *, repo_id: str) -> dict[str, object]:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    copied: list[Path] = []
    summaries: dict[str, dict[str, object]] = {}
    for name, rel_source in DEFAULT_BENCHMARK_EXPORTS.items():
        source = PROJECT_ROOT / rel_source
        if not source.exists():
            raise FileNotFoundError(f"benchmark export not found: {rel_source}")
        target = output_dir / name
        target.mkdir(parents=True, exist_ok=True)
        for filename in BENCHMARK_FILES:
            src = source / filename
            if not src.exists():
                raise FileNotFoundError(f"missing benchmark file: {src}")
            dst = target / filename
            shutil.copy2(src, dst)
            copied.append(dst)
        stats = json.loads((target / "stats.json").read_text(encoding="utf-8"))
        manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        summaries[name] = {
            "total_examples": manifest.get("total_examples", stats.get("total")),
            "split_counts": manifest.get("split_counts", stats.get("by_split")),
            "by_graph": stats.get("by_graph", {}),
            "sha256": manifest.get("sha256"),
        }

    readme = output_dir / "README.md"
    readme.write_text(_dataset_card(repo_id=repo_id, summaries=summaries), encoding="utf-8")
    copied.append(readme)

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "repo_id": repo_id,
        "benchmark_exports": summaries,
        "files": file_manifest(copied, root=output_dir),
        "upload_command": f"huggingface-cli upload --repo-type dataset {repo_id} {output_dir}",
    }
    manifest_path = output_dir / "PIPE_CYPHER_HF_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def _dataset_card(*, repo_id: str, summaries: dict[str, dict[str, object]]) -> str:
    rows = [
        "---",
        "license: mit",
        "task_categories:",
        "- text-generation",
        "language:",
        "- en",
        "pretty_name: PIPE-Cypher Benchmarks",
        "tags:",
        "- text2cypher",
        "- cypher",
        "- property-graphs",
        "- benchmark",
        "---",
        "",
        "# PIPE-Cypher Benchmarks",
        "",
        "This dataset release contains the public-proxy benchmark exports used by",
        "PIPE-Cypher: Automatic Enterprise Benchmark Generation for Text-to-Cypher",
        "Systems.",
        "",
        "Repository: https://github.com/suraj-ranganath/PIPE-Cypher",
        f"Dataset repo: https://huggingface.co/datasets/{repo_id}",
        "",
        "## Exports",
        "",
    ]
    for name, summary in summaries.items():
        rows.extend(
            [
                f"### `{name}`",
                "",
                f"- Total examples: {summary.get('total_examples')}",
                f"- Split counts: `{json.dumps(summary.get('split_counts', {}), sort_keys=True)}`",
                f"- Graph counts: `{json.dumps(summary.get('by_graph', {}), sort_keys=True)}`",
                f"- Export checksum: `{summary.get('sha256')}`",
                "",
            ]
        )
    rows.extend(
        [
            "Each export contains `all.jsonl`, `train.jsonl`, `dev.jsonl`,",
            "`test.jsonl`, `stats.json`, and `manifest.json`.",
            "",
            "The FinBench/SNB export is the 3,000-example main benchmark. The",
            "ICIJ Offshore Leaks export is the third-graph onboarding benchmark.",
            "",
            "## Intended Use",
            "",
            "Use these files to inspect PIPE-Cypher benchmark examples, reproduce",
            "reported public-proxy evaluation splits, or evaluate Text2Cypher systems",
            "against the same graph snapshots described in the paper.",
            "",
            "## Limitations",
            "",
            "These are public proxy graphs, not proprietary enterprise graphs. The",
            "benchmark should be regenerated for a company's own graph, value policy,",
            "schema version, and user workloads before being used for deployment",
            "qualification.",
            "",
        ]
    )
    return "\n".join(rows)


if __name__ == "__main__":
    main()
