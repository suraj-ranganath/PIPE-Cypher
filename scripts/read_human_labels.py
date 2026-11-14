#!/usr/bin/env python3
"""Read human labels back from the labeling page and compute agreement and error rates.

Input is a dump of the page's `labels` db collection: the directory written by
an ArtifactData `query`/`list` on collection `labels` with `out_dir` (one JSON
file per document), or a JSON file of rows, or the JSON file an annotator
downloaded from the page. Several --labels files may
be given; the newest row per (set, annotator, item) wins.

Writes, under --output-dir:
  labels.jsonl   normalized labels (PRIVATE: notes may quote values)
  summary.json   inter-annotator kappa on shared items, weighted reference error
                 rate (wrong; wrong + minor issue) and ambiguity rate with
                 stratified bootstrap CIs, slice rates, judge-human agreement.

Example:
  python scripts/read_human_labels.py \
      --labels artifacts/human_validation_v3/v3/labels_dump.json \
      --key artifacts/human_validation_v3/v3/key.jsonl \
      --verdicts gpt6_luna=artifacts/judges/naacl_v3/audit_gpt6_luna.jsonl \
      --output-dir artifacts/human_validation_v3/v3/results
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipecypher.human_validation import (  # noqa: E402
    load_verdicts,
    parse_label_dump,
    read_jsonl,
    summarize_labels,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--labels", action="append", required=True, help="Label dump: a JSON file (db rows or page download) or an ArtifactData out_dir directory")
    parser.add_argument("--key", required=True, help="key.jsonl written by sample_human_validation.py")
    parser.add_argument("--verdicts", action="append", default=[], help="Judge verdicts as NAME=PATH (JSONL); default: verdicts stored in the key")
    parser.add_argument("--adjudication", default=None, help="JSON {item_id: {reference, clarity}} overriding annotator labels")
    parser.add_argument("--set-id", default=None, help="Only use labels of this set (default: the key's set id)")
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    payloads = []
    for value in args.labels:
        path = Path(value)
        # A directory is an ArtifactData `out_dir` dump: one JSON file per document.
        files = sorted(path.rglob("*.json")) if path.is_dir() else [path]
        payloads.extend(json.loads(file.read_text(encoding="utf-8")) for file in files)
    labels = parse_label_dump(payloads)
    key_rows = read_jsonl(args.key)
    set_id = args.set_id or (key_rows[0].get("set_id") if key_rows else None)
    if args.verdicts:
        specs = {}
        for value in args.verdicts:
            name, path = value.split("=", 1)
            specs[name] = path
        verdicts = load_verdicts(specs)
    else:
        verdicts = {row["item_id"]: dict(row.get("verdicts") or {}) for row in key_rows}
        for row in key_rows:
            # Per-judge verdicts stored by build_checklist_review_data.py (panel members and auditor).
            for name, member in (row.get("judge_checklists") or {}).items():
                verdicts[row["item_id"]][f"judge:{name}"] = bool(member.get("passed"))
        verdicts = {item: v for item, v in verdicts.items() if v}
    adjudication = json.loads(Path(args.adjudication).read_text(encoding="utf-8")) if args.adjudication else None
    summary = summarize_labels(
        labels,
        key_rows,
        verdicts=verdicts,
        adjudication=adjudication,
        set_id=set_id,
        n_boot=args.bootstrap,
        seed=args.seed,
    )
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "labels.jsonl").open("w", encoding="utf-8") as handle:
        for label in labels:
            if set_id is None or label["set_id"] == set_id:
                handle.write(json.dumps(label, sort_keys=True) + "\n")
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    brief = {
        "labels": summary["labels"],
        "items_labeled": summary["items_labeled"],
        "progress": summary["progress"],
        "reference_error_rate": summary["reference_error_rate"],
        "reference_error_or_minor_rate": summary["reference_error_or_minor_rate"],
        "question_ambiguity_rate": summary["question_ambiguity_rate"],
        "verdict_fail_rate": summary["verdict_fail_rate"],
        "inter_annotator_kappa": {
            pair: block["reference_3way"]["cohen_kappa"] for pair, block in summary["inter_annotator"].items()
        },
        "inter_annotator_verdict": {pair: block["verdict_pass"] for pair, block in summary["inter_annotator"].items()},
    }
    print(json.dumps(brief, indent=2, default=str))


if __name__ == "__main__":
    main()
