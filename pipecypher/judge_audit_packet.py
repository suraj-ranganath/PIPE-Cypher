from __future__ import annotations

import csv
import hashlib
import html
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .calibration import analyze_audit_csv, summarize_audit_csv


def load_audit_rows(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def audit_packet_snapshot(path: str | Path, *, html_path: str | Path | None = None) -> dict[str, Any]:
    audit_path = Path(path)
    coverage = summarize_audit_csv(audit_path)
    metrics = analyze_audit_csv(audit_path)
    if coverage.total_rows == 0:
        label_status = "empty"
    elif coverage.labeled_rows == 0:
        label_status = "unlabeled"
    elif coverage.unlabeled_rows == 0:
        label_status = "complete"
    else:
        label_status = "partial"
    snapshot = {
        "audit_csv": str(audit_path),
        "audit_sha256": _sha256(audit_path),
        "html_packet": str(html_path) if html_path else "",
        "coverage": asdict(coverage),
        "metrics": asdict(metrics),
        "ready_for_calibration": coverage.total_rows > 0 and coverage.unlabeled_rows == 0,
        "label_status": label_status,
        "partial_labels_present": metrics.total_labeled > 0 and coverage.unlabeled_rows > 0,
        "label_completion_rate": (
            coverage.labeled_rows / coverage.total_rows if coverage.total_rows else 0.0
        ),
    }
    return snapshot


def render_audit_html(path: str | Path, *, title: str = "PIPE-Cypher Judge Audit") -> str:
    rows = load_audit_rows(path)
    snapshot = audit_packet_snapshot(path)
    cards = "\n".join(_render_row(row) for row in rows)
    rows_json = json.dumps(
        [
            {
                "id": row.get("id", ""),
                "dom_id": _dom_id(row.get("id", "")),
                "graph_profile": row.get("graph_profile", ""),
                "judge_accept": row.get("judge_accept", ""),
                "category": row.get("category", ""),
                "difficulty": row.get("difficulty", ""),
                "primary_strategy": row.get("primary_strategy", ""),
            }
            for row in rows
        ],
        ensure_ascii=False,
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{_e(title)}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 24px; color: #111827; }}
    header {{ max-width: 980px; margin-bottom: 24px; }}
    .summary {{ display: grid; grid-template-columns: repeat(4, minmax(120px, 1fr)); gap: 10px; max-width: 980px; }}
    .metric {{ border: 1px solid #d1d5db; border-radius: 6px; padding: 10px; background: #f9fafb; }}
    .metric strong {{ display: block; font-size: 20px; }}
    .card {{ max-width: 980px; border: 1px solid #d1d5db; border-radius: 6px; padding: 14px; margin: 14px 0; }}
    .meta {{ color: #4b5563; font-size: 13px; margin-bottom: 8px; }}
    pre {{ white-space: pre-wrap; word-break: break-word; background: #f3f4f6; padding: 10px; border-radius: 4px; }}
    label {{ margin-right: 18px; }}
    textarea {{ width: 100%; min-height: 52px; margin-top: 8px; }}
    button {{ padding: 8px 12px; border: 1px solid #1f2937; border-radius: 4px; background: #1f2937; color: white; cursor: pointer; }}
    .warning {{ color: #92400e; background: #fffbeb; border: 1px solid #f59e0b; padding: 10px; border-radius: 4px; max-width: 980px; }}
  </style>
</head>
<body>
  <header>
    <h1>{_e(title)}</h1>
    <p>This packet calibrates the LLM judge after generation. Human labels are not a generation gate.</p>
    <p class="warning">Fill every row, then use the download button. Copy the downloaded <code>human_accept</code> and <code>human_notes</code> columns back into the audit CSV before running <code>scripts/analyze_judge_audit.py --require-complete-labels</code>.</p>
    <div class="summary">
      <div class="metric"><span>Total rows</span><strong>{snapshot["coverage"]["total_rows"]}</strong></div>
      <div class="metric"><span>Judge accepts</span><strong>{snapshot["coverage"]["judge_accepts"]}</strong></div>
      <div class="metric"><span>Judge rejects</span><strong>{snapshot["coverage"]["judge_rejects"]}</strong></div>
      <div class="metric"><span>Labeled rows</span><strong>{snapshot["coverage"]["labeled_rows"]}</strong></div>
    </div>
    <p><button type="button" onclick="downloadLabels()">Download labels CSV</button></p>
  </header>
  <main>
{cards}
  </main>
  <script>
    const auditRows = {rows_json};
    function csvEscape(value) {{
      const text = String(value ?? "");
      if (/[",\\n]/.test(text)) return '"' + text.replaceAll('"', '""') + '"';
      return text;
    }}
    function downloadLabels() {{
      const lines = [["id","human_accept","human_notes"].join(",")];
      for (const row of auditRows) {{
        const domId = String(row.dom_id);
        const selected = document.querySelector(`input[name="human_accept_${{CSS.escape(domId)}}"]:checked`);
        const notes = document.querySelector(`#human_notes_${{CSS.escape(domId)}}`);
        lines.push([row.id, selected ? selected.value : "", notes ? notes.value : ""].map(csvEscape).join(","));
      }}
      const blob = new Blob([lines.join("\\n") + "\\n"], {{ type: "text/csv" }});
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "judge_audit_labels.csv";
      a.click();
      URL.revokeObjectURL(url);
    }}
  </script>
</body>
</html>
"""


def _render_row(row: dict[str, str]) -> str:
    row_id = row.get("id", "")
    dom_id = _dom_id(row_id)
    checked_true = " checked" if row.get("human_accept", "").strip().lower() == "true" else ""
    checked_false = " checked" if row.get("human_accept", "").strip().lower() == "false" else ""
    return f"""    <section class="card">
      <div class="meta">#{_e(row_id)} | graph={_e(row.get("graph_profile", ""))} | category={_e(row.get("category", ""))} | difficulty={_e(row.get("difficulty", ""))} | strategy={_e(row.get("primary_strategy", ""))} | judge_accept={_e(row.get("judge_accept", ""))}</div>
      <h2>Question</h2>
      <p>{_e(row.get("question", ""))}</p>
      <h2>Cypher</h2>
      <pre>{_e(row.get("cypher", ""))}</pre>
      <h2>Judge Failure Reason</h2>
      <p>{_e(row.get("judge_failure_reason", "")) or "&nbsp;"}</p>
      <h2>Human Label</h2>
      <label><input type="radio" name="human_accept_{_e(dom_id)}" value="true"{checked_true}> Accept</label>
      <label><input type="radio" name="human_accept_{_e(dom_id)}" value="false"{checked_false}> Reject</label>
      <textarea id="human_notes_{_e(dom_id)}" placeholder="human_notes">{_e(row.get("human_notes", ""))}</textarea>
    </section>"""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _dom_id(value: Any) -> str:
    text = str(value)
    if re.fullmatch(r"[A-Za-z0-9_-]+", text):
        return text
    return "row_" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
