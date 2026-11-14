#!/usr/bin/env python3
"""Recompute ``predicted_cypher`` from each prediction's stored ``raw_text`` with the
current ``clean_predicted_cypher`` (e.g. after adding end-of-turn marker stripping).

The model is not called again: the raw model output is unchanged, only the
deterministic extraction is re-applied. The original file is kept as
``<file>.before_reclean`` and changed rows get ``recleaned: true``.

Example:
  python scripts/reclean_predictions.py artifacts/evaluations/<run>/zero_shot_predictions.jsonl
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipecypher.text2cypher import clean_predicted_cypher  # noqa: E402


def main() -> None:
    for raw_path in sys.argv[1:]:
        path = Path(raw_path)
        backup = path.with_name(path.name + ".before_reclean")
        if not backup.exists():
            shutil.copy(path, backup)
        rows = [json.loads(line) for line in backup.open(encoding="utf-8") if line.strip()]
        changed = 0
        for row in rows:
            if row.get("raw_text") is None:
                continue
            new = clean_predicted_cypher(row["raw_text"])
            if new != row.get("predicted_cypher"):
                row["predicted_cypher"] = new
                row["recleaned"] = True
                changed += 1
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        print(f"{path}: {changed} of {len(rows)} predictions re-extracted")


if __name__ == "__main__":
    main()
