#!/usr/bin/env python3
"""Give human annotators the same prompt the v3 checklist judge gets.

Reads a sample built by ``scripts/sample_human_validation.py`` and adds, for
every sampled item, the judge prompt rendered by the judge's own function
(``render_judge_v3_prompt``, full schema, same execution sample and validator
notes the panel saw). The prompt is split into the parts the labeling page
shows: the instructions (task, convention sheet, out-of-scope list, how to
review, the nine-criterion checklist), the graph schema, and the item block
(question, reference Cypher, result summary and rows, parser features,
validator notes). The judge's JSON output instructions are replaced on the page
by the form; nothing else differs.

Also writes, into the PRIVATE key only, the per-criterion answers of each panel
judge (from the generation records) and of the outside auditor, so human and
judge answers can be compared criterion by criterion.

Example:
  python scripts/build_checklist_review_data.py \
      --sample-dir artifacts/human_validation_v3/v3c \
      --export artifacts/benchmarks/naacl_v3_full \
      --records 'artifacts/runs/*naacl_v3_full*/records.jsonl' \
      --audit artifacts/naacl_v3/audit/full_gpt6luna_checklist.jsonl \
      --config finbench=configs/finbench_v3.yaml --config snb=configs/snb_v3.yaml
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from pipecypher.judge import (  # noqa: E402
    CHECKLIST_CRITERIA,
    CHECKLIST_NA_FAILS,
    JUDGE_V3_PROMPT_SHA256,
    parse_checklist,
    render_judge_v3_prompt,
)
from pipecypher.models import ExecutionResult, ValidationIssue, ValidationResult  # noqa: E402
from pipecypher.prompts import JUDGE_V3_SYSTEM  # noqa: E402
from sample_human_validation import _pairs, _schemas  # noqa: E402

OUTPUT_MARKER = "\n\nOutput: "
SCHEMA_MARKER = "\n\nGraph schema:\n"
ITEM_MARKER = "\n\nItem to review\n"
CHECKLIST_MARKER = "\n\nChecklist."


def _validation(row: dict) -> ValidationResult:
    v = row.get("validation") or {}
    return ValidationResult(
        read_only=bool(v.get("read_only")),
        syntax_valid=bool(v.get("syntax_valid")),
        schema_valid=bool(v.get("schema_valid")),
        normalized_cypher=v.get("normalized_cypher") or row.get("cypher", ""),
        issues=[ValidationIssue(i.get("level", "warning"), i.get("code", ""), i.get("message", "")) for i in v.get("issues") or []],
        structural_features=v.get("structural_features") or {},
    )


def _execution(row: dict) -> ExecutionResult:
    e = row.get("execution") or {}
    return ExecutionResult(success=bool(e.get("success")), rows=e.get("rows") or [], error=e.get("error"))


def split_prompt(prompt: str) -> dict[str, str]:
    """Split a rendered judge prompt into instructions, output spec, schema, and item block."""

    head, sep, rest = prompt.partition(SCHEMA_MARKER)
    if not sep:
        raise ValueError("rendered prompt has no 'Graph schema' block")
    instructions, sep, output_spec = head.partition(OUTPUT_MARKER)
    if not sep:
        raise ValueError("rendered prompt has no 'Output:' block")
    schema_text, sep, item_block = rest.partition(ITEM_MARKER)
    if not sep:
        raise ValueError("rendered prompt has no 'Item to review' block")
    return {
        "instructions": instructions.strip(),
        "output_spec": "Output: " + output_spec.strip(),
        "schema": schema_text.strip(),
        "item_block": item_block.strip().removesuffix(FINAL_LINE).strip(),
        "final_line": FINAL_LINE if item_block.strip().endswith(FINAL_LINE) else "",
    }


FINAL_LINE = "Return the JSON object now."


def item_fields(item_block: str) -> dict[str, str]:
    """Result summary, parser features, and validator notes from a rendered item block."""

    fields = {"row_summary": "", "features": "", "notes": ""}
    for line in item_block.splitlines():
        if line.startswith("Result: "):
            fields["row_summary"] = line[len("Result: "):].strip()
        elif line.startswith("Query features (from the parser): "):
            fields["features"] = line.split(": ", 1)[1].strip()
        elif line.startswith("Validator notes: "):
            fields["notes"] = line.split(": ", 1)[1].strip()
    return fields


def criterion_texts(instructions: str) -> dict[str, str]:
    """The checklist lines verbatim, keyed by criterion name."""

    _, _, checklist = instructions.partition(CHECKLIST_MARKER)
    texts: dict[str, str] = {}
    for line in checklist.splitlines():
        line = line.strip()
        for index, name in enumerate(CHECKLIST_CRITERIA, start=1):
            prefix = f"{index}. {name}:"
            if line.startswith(prefix):
                texts[name] = line[len(prefix):].strip()
    missing = [name for name in CHECKLIST_CRITERIA if name not in texts]
    if missing:
        raise ValueError(f"checklist lines not found for {missing}")
    return texts


def _answers(raw: Any) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None
    parsed = parse_checklist(raw.get("checklist") if isinstance(raw.get("checklist"), dict) else raw)
    if not parsed:
        return None
    return {name: parsed[name]["answer"] for name in parsed}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sample-dir", required=True, help="Directory with items.json and key.jsonl from sample_human_validation.py")
    parser.add_argument("--export", required=True)
    parser.add_argument("--records", action="append", required=True, help="Glob of generation records.jsonl files")
    parser.add_argument("--audit", default=None, help="Auditor checklist JSONL (audit_checklist_judge.py output)")
    parser.add_argument("--config", action="append", default=[], help="graph=config.yaml")
    args = parser.parse_args()

    sample_dir = Path(args.sample_dir)
    page = json.loads((sample_dir / "items.json").read_text(encoding="utf-8"))
    key_rows = [json.loads(line) for line in (sample_dir / "key.jsonl").open(encoding="utf-8") if line.strip()]
    wanted = set(page["items"])

    export = {}
    for line in (Path(args.export) / "all.jsonl").open(encoding="utf-8"):
        row = json.loads(line)
        if row["id"] in wanted:
            export[row["id"]] = row
    missing = wanted - set(export)
    if missing:
        raise SystemExit(f"{len(missing)} sampled ids not in the export: {sorted(missing)[:3]}")

    def questions_of(row: dict) -> list[str]:
        out = [row["question"]]
        before = (row.get("question_normalization") or {}).get("before")
        if before:
            out.append(before)
        return out

    targets: dict[tuple[str, str, str], str] = {}
    for item_id, row in export.items():
        for question in questions_of(row):
            targets[(row["graph_profile"], question, row.get("normalized_cypher") or row["cypher"])] = item_id
    records: dict[str, dict] = {}
    paths = sorted({p for pattern in args.records for p in glob.glob(pattern)})
    for path in paths:
        for line in Path(path).open(encoding="utf-8"):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not rec.get("accepted"):
                continue
            norm = (rec.get("validation") or {}).get("normalized_cypher") or rec.get("cypher", "")
            item_id = targets.get((rec.get("graph_profile"), rec.get("question"), norm))
            if item_id and item_id not in records:
                records[item_id] = rec
    unmatched = wanted - set(records)
    if unmatched:
        raise SystemExit(f"{len(unmatched)} sampled items have no generation record: {sorted(unmatched)[:3]}")

    audit: dict[str, dict] = {}
    if args.audit:
        for line in Path(args.audit).open(encoding="utf-8"):
            if line.strip():
                row = json.loads(line)
                audit[row["key"]] = row

    schemas = _schemas(_pairs(args.config, "--config"), {}, {})
    instructions: dict[str, str] = {}
    schema_text: dict[str, str] = {}
    output_spec = None
    criteria_text = None
    judge_items: dict[str, dict] = {}
    key_extra: dict[str, dict] = {}
    for item_id in sorted(wanted):
        row, rec = export[item_id], records[item_id]
        graph = row["graph_profile"]
        validation, execution = _validation(rec), _execution(rec)
        question = row["question"]
        cypher = row.get("normalized_cypher") or rec["validation"]["normalized_cypher"]
        prompt = render_judge_v3_prompt(
            question=question, cypher=cypher, schema=schemas[graph],
            validation=validation, execution=execution, schema_mode="full",
        )
        parts = split_prompt(prompt)
        if instructions.setdefault(graph, parts["instructions"]) != parts["instructions"]:
            raise SystemExit(f"instructions differ between items of graph {graph}")
        if schema_text.setdefault(graph, parts["schema"]) != parts["schema"]:
            raise SystemExit(f"schema text differs between items of graph {graph}")
        output_spec = output_spec or parts["output_spec"]
        texts = criterion_texts(parts["instructions"])
        if criteria_text is None:
            criteria_text = texts
        elif texts != criteria_text:
            raise SystemExit("checklist text differs between graphs")
        judge_items[item_id] = {
            "item_block": parts["item_block"],
            "fields": item_fields(parts["item_block"]),
            "prompt_sha256": hashlib.sha256((JUDGE_V3_SYSTEM + "\n" + prompt).encode("utf-8")).hexdigest(),
        }
        panel = ((rec.get("judge") or {}).get("raw") or {}).get("panel") or []
        members = {}
        for member in panel:
            answers = _answers(member.get("raw"))
            if answers is not None:
                members[str(member.get("label") or member.get("model"))] = {"passed": bool(member.get("passed")), "checklist": answers}
        audit_key = f"{rec.get('graph_profile')}|{rec.get('category')}|{rec.get('question')}|{rec.get('cypher')}"
        audited = audit.get(audit_key)
        if audited is not None:
            answers = _answers(audited.get("auditor_raw"))
            members[str(audited.get("auditor") or "auditor")] = {"passed": bool(audited.get("auditor_passed")), "checklist": answers or {}}
        key_extra[item_id] = {"judge_checklists": members, "judge_prompt_sha256": judge_items[item_id]["prompt_sha256"]}

    for item_id, extra in judge_items.items():
        page["items"][item_id]["judge_item"] = extra["item_block"]
        page["items"][item_id].update(extra["fields"])
    page["judge"] = {
        "system": JUDGE_V3_SYSTEM,
        "template_sha256": JUDGE_V3_PROMPT_SHA256,
        "instructions": instructions,
        "schema": schema_text,
        "output_spec": output_spec,
        "criteria": [
            {"name": name, "text": criteria_text[name], "na_fails": name in CHECKLIST_NA_FAILS}
            for name in CHECKLIST_CRITERIA
        ],
    }
    (sample_dir / "items.json").write_text(json.dumps(page, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    with (sample_dir / "key.jsonl").open("w", encoding="utf-8") as handle:
        for row in key_rows:
            row.update(key_extra.get(row["item_id"], {}))
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    manifest_path = sample_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["judge_view"] = {
        "builder": "scripts/build_checklist_review_data.py",
        "judge_template_sha256": JUDGE_V3_PROMPT_SHA256,
        "records": paths and f"{len(paths)} records files matching {args.records}",
        "audit": args.audit,
    }
    for name in ("items.json", "key.jsonl"):
        manifest.setdefault("files", {})[name] = hashlib.sha256((sample_dir / name).read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with_audit = sum(1 for extra in key_extra.values() if any(k not in ("primary", "secondary") for k in extra["judge_checklists"]))
    print(f"{len(judge_items)} items; graphs {sorted(instructions)}; auditor checklists for {with_audit}; panel labels {sorted({k for e in key_extra.values() for k in e['judge_checklists']})}")


if __name__ == "__main__":
    main()
