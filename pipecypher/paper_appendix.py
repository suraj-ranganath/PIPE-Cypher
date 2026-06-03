from __future__ import annotations

import hashlib
import json
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .prompts import (
    CYPHER_GENERATION_PROMPT,
    JUDGE_PROMPT,
    REPAIR_PROMPT,
    REVERSE_CYPHER_PROMPT,
    TEMPLATE_GENERATION_PROMPT,
    SYSTEM_JSON_ENGINEER,
)
from .text2cypher import TEXT2CYPHER_PROMPT, TEXT2CYPHER_SYSTEM


@dataclass(frozen=True)
class PromptContract:
    name: str
    stage: str
    constraints: tuple[str, ...]
    prompt_text: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.prompt_text.encode("utf-8")).hexdigest()


def load_examples(path: str | Path) -> list[dict[str, Any]]:
    text = Path(path).read_text(encoding="utf-8")
    if Path(path).suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError(f"expected a JSON list at {path}")
    return data


def load_claim_evidence(path: str | Path) -> list[dict[str, Any]]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    claims = data.get("claims") if isinstance(data, dict) else None
    if not isinstance(claims, list):
        raise ValueError(f"expected a top-level claims list at {path}")
    for idx, claim in enumerate(claims):
        if not isinstance(claim, dict):
            raise ValueError(f"claim {idx} is not a mapping")
        missing = {"claim", "evidence", "artifacts", "status", "risk"} - set(claim)
        if missing:
            raise ValueError(f"claim {idx} is missing keys: {sorted(missing)}")
    return claims


def prompt_contracts() -> list[PromptContract]:
    return [
        PromptContract(
            name="Template generation",
            stage="Workload proposal",
            constraints=(
                "Schema-only labels, relationships, properties, and categorical values",
                "Realistic enterprise analyst wording",
                "At most two typed slots and JSON-only output",
            ),
            prompt_text=TEMPLATE_GENERATION_PROMPT,
        ),
        PromptContract(
            name="Reverse binding",
            stage="Graph grounding",
            constraints=(
                "Read-only MATCH/WHERE/RETURN DISTINCT/LIMIT only",
                "Slot variables named exactly as requested",
                "Forward relationship directions from the schema",
            ),
            prompt_text=REVERSE_CYPHER_PROMPT,
        ),
        PromptContract(
            name="Cypher generation",
            stage="Candidate query",
            constraints=(
                "Only schema-visible constructs and observed directions",
                "RETURN DISTINCT for set returns and exact equality for quoted values",
                "Context columns, categorical hints, placeholderized retrieval, and no writes",
            ),
            prompt_text=CYPHER_GENERATION_PROMPT,
        ),
        PromptContract(
            name="Repair",
            stage="Validation feedback",
            constraints=(
                "Preserve question intent while fixing validation or execution issues",
                "Keep query read-only and schema-grounded",
                "Return only corrected Cypher",
            ),
            prompt_text=REPAIR_PROMPT,
        ),
        PromptContract(
            name="LLM judge",
            stage="Quality gate",
            constraints=(
                "Inputs include question, Cypher, schema slice, execution rows, "
                "and validation summary",
                "Strict JSON scores for ambiguity, semantic alignment, schema use, and difficulty",
                "Categorical values constrain query literals, not observed result-row values",
                "Pass only useful, unambiguous enterprise benchmark examples",
            ),
            prompt_text=JUDGE_PROMPT,
        ),
        PromptContract(
            name="Downstream Text2Cypher",
            stage="Model evaluation",
            constraints=(
                "Read-only Cypher only",
                "Schema-visible constructs and exact direction preservation",
                "RETURN DISTINCT, count/ranking rules, and no explanations",
            ),
            prompt_text=f"{TEXT2CYPHER_SYSTEM}\n\n{TEXT2CYPHER_PROMPT}",
        ),
    ]


def render_prompt_contracts_tex() -> str:
    rows = [
        r"\section{Prompt Contracts}",
        r"\label{tab:prompt_contracts}",
        (
            "PIPE-Cypher treats prompts as versioned implementation artifacts. "
            "The list summarizes the prompt contracts used for generation, repair, "
            "judging, and downstream evaluation; hashes fingerprint the full prompt "
            "constants in the codebase."
        ),
        r"\begin{enumerate}",
    ]
    for contract in prompt_contracts():
        rows.extend(
            [
                "\\item \\textbf{{{name}.}} Stage: {stage}. SHA-256: \\texttt{{{sha}}}.\\par".format(
                    name=_escape_latex(contract.name),
                    stage=_escape_latex(contract.stage),
                    sha=contract.sha256[:6],
                ),
                "\\textit{{Contract.}} {constraints}".format(
                    constraints=_escape_latex("; ".join(contract.constraints)),
                ),
            ]
        )
    rows.extend(
        [
            r"\end{enumerate}",
            r"\subsection{LLM Judge Prompt Used in Reported Runs}",
            (
                "The local LLM judge receives a JSON-only system instruction and "
                "the following user prompt template after schema slicing, execution "
                "sampling, and deterministic validation. The placeholders are filled "
                "with the candidate question, Cypher, schema slice, execution rows, "
                "and validation summary for each reviewed example."
            ),
            r"\begingroup",
            r"\footnotesize",
            r"\begin{verbatim}",
            "System prompt:",
            *_verbatim_lines(SYSTEM_JSON_ENGINEER),
            "",
            "User prompt template:",
            *_verbatim_lines(JUDGE_PROMPT),
            r"\end{verbatim}",
            r"\endgroup",
        ]
    )
    return "\n".join(rows) + "\n"


def render_claim_evidence_tex(claims: list[dict[str, Any]]) -> str:
    rows = [
        r"\section{Claim--Evidence Map}",
        r"\label{tab:claim_evidence_map}",
        (
            "This section maps the main paper claims to "
            "the strongest current evidence and to the remaining risks. This is "
            "intended as a reviewer-facing audit surface: claims with pending "
            "evidence remain marked as such rather than being folded into the "
            "main results."
        ),
        r"\begin{enumerate}",
    ]
    for index, item in enumerate(claims, start=1):
        rows.extend(
            [
                "\\item \\textbf{{Claim {index}.}} {claim}\\par".format(
                    index=index,
                    claim=_escape_latex(str(item["claim"])),
                ),
                "\\textit{{Evidence.}} {evidence}\\par".format(
                    evidence=_escape_latex(str(item["evidence"])),
                ),
                "\\textit{{Key artifacts.}} {artifacts}\\par".format(
                    artifacts=_escape_latex(_artifact_summary(item.get("artifacts", []))),
                ),
                "\\textit{{Status.}} {status}\\par".format(
                    status=_escape_latex(str(item["status"])),
                ),
                "\\textit{{Risk.}} {risk}".format(
                    risk=_escape_latex(str(item["risk"])),
                ),
            ]
        )
    rows.extend(
        [
            r"\end{enumerate}",
        ]
    )
    return "\n".join(rows) + "\n"


def render_example_cards_tex(
    examples: list[dict[str, Any]],
    *,
    max_examples: int = 16,
) -> str:
    selected = sorted(
        examples,
        key=lambda row: (
            str(row.get("graph_profile", "")),
            str(row.get("category", "")),
            str(row.get("id", "")),
        ),
    )[:max_examples]
    lines = [
        r"\section{Representative Accepted Examples}",
        (
            "The examples below are selected in stable identifier order from the tracked "
            "full-export snapshot, one per graph/category cell when available. They show "
            "the natural-language question, accepted Cypher, structural tags, gate status, "
            "and a bounded execution-result sample."
        ),
        r"\begin{enumerate}",
    ]
    for row in selected:
        lines.extend(_example_item(row))
    lines.append(r"\end{enumerate}")
    return "\n".join(lines) + "\n"


def _example_item(row: dict[str, Any]) -> list[str]:
    graph = _label(str(row.get("graph_profile", "")))
    category = _label(str(row.get("category", "")))
    difficulty = _escape_latex(str(row.get("difficulty", "")))
    question = _escape_latex(str(row.get("question", "")))
    cypher = _wrap_code(str(row.get("cypher", "")), width=40)
    result = _escape_latex(_result_summary(row))
    features = row.get("structural_features", {})
    tags = ", ".join(str(tag) for tag in features.get("strategy_tags", []))
    relationships = ", ".join(str(rel) for rel in features.get("relationship_types", []))
    gates = row.get("gates", {})
    gate_labels = {
        "read_only": "RO",
        "syntax_valid": "Syn",
        "schema_valid": "Schema",
        "execution_success": "Exec",
        "judge_pass": "Judge",
    }
    gate_summary = "/".join(
        gate_labels[name]
        for name in (
            "read_only",
            "syntax_valid",
            "schema_valid",
            "execution_success",
            "judge_pass",
        )
        if gates.get(name)
    )
    return [
        "\\item \\textbf{{{graph} / {category} / {difficulty}.}}".format(
            graph=graph,
            category=category,
            difficulty=difficulty,
        ),
        "\\textit{{Question:}} {question}".format(question=question),
        r"\begin{quote}\scriptsize\ttfamily\raggedright\sloppy",
        cypher,
        r"\end{quote}",
        "\\textit{{Structure:}} {tags}.\\par".format(tags=_escape_latex(tags or "none")),
        "\\textit{{Relationships:}} {relationships}.\\par".format(
            relationships=_escape_latex(relationships or "none")
        ),
        "\\textit{{Gates:}} {gates}.\\par".format(gates=_escape_latex(gate_summary or "none")),
        "\\textit{{Result sample:}} {result}".format(result=result),
    ]


def _escape_latex(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
        "<": r"\textless{}",
        ">": r"\textgreater{}",
    }
    return "".join(replacements.get(char, char) for char in value)


def _artifact_summary(artifacts: Any) -> str:
    if not isinstance(artifacts, list):
        return str(artifacts)
    shortened = []
    for artifact in artifacts[:4]:
        shortened.append(_artifact_label(str(artifact)))
    if len(artifacts) > 4:
        shortened.append(f"+{len(artifacts) - 4} more")
    return "; ".join(shortened)


def _artifact_label(artifact: str) -> str:
    path = Path(artifact)
    name = path.name
    stem = path.stem.replace("_", " ")
    if artifact.startswith("artifacts/benchmarks/"):
        return "benchmark export"
    if artifact.startswith("artifacts/evaluations/"):
        return "downstream summary"
    if artifact.startswith("artifacts/audits/"):
        return "judge-audit packet"
    if artifact.startswith("experiments/snapshots/") and name == "manifest.json":
        return "manifest snapshot"
    if artifact.startswith("experiments/snapshots/") and name.endswith(".json"):
        return f"snapshot: {stem}"
    if artifact.startswith("knowledge_base/"):
        return f"research note: {stem}"
    if artifact.startswith("paper_emnlp2026_industry/tables_"):
        table_name = name.removeprefix("tables_").removesuffix(".tex")
        return f"paper table: {table_name.replace('_', ' ')}"
    if artifact.startswith("paper_emnlp2026_industry/figures/"):
        return f"paper figure: {stem}"
    if artifact.startswith("pipecypher/"):
        return f"code: {name}"
    if artifact.startswith("scripts/"):
        return f"script: {path.stem.replace('_', ' ')}"
    return name or artifact


def _wrap_code(value: str, *, width: int) -> str:
    lines: list[str] = []
    for source_line in _display_cypher(value).splitlines():
        lines.extend(
            textwrap.wrap(
                source_line,
                width=width,
                break_long_words=False,
                break_on_hyphens=False,
            )
            or [""]
        )
    if not lines:
        return ""
    return "\\\\\n".join(_escape_latex(line) for line in lines)


def _verbatim_lines(value: str, *, width: int = 76) -> list[str]:
    lines: list[str] = []
    for source_line in value.strip().splitlines():
        if not source_line.strip():
            lines.append("")
            continue
        lines.extend(
            textwrap.wrap(
                source_line,
                width=width,
                break_long_words=False,
                break_on_hyphens=False,
            )
            or [""]
        )
    return lines


def _display_cypher(value: str) -> str:
    display = re.sub(r"\s+", " ", value).strip()
    display = re.sub(
        r"(?i)\b(OPTIONAL\s+MATCH|ORDER\s+BY|MATCH|WHERE|WITH|RETURN|SKIP|LIMIT)\b",
        lambda match: "\n" + re.sub(r"\s+", " ", match.group(1).upper()),
        display,
    ).strip()
    display = re.sub(r"\)\s*-\s*\[:", ") -[:", display)
    display = re.sub(r"\]\s*-\s*\(", "]- (", display)
    display = re.sub(r"\)\s*<-\s*\[:", ") <-[:", display)
    display = re.sub(r"\]\s*->\s*\(", "]-> (", display)
    display = display.replace("->", "-> ")
    display = display.replace("<-", " <-")
    display = re.sub(r"\s*,\s*", ", ", display)
    return "\n".join(re.sub(r"\s+", " ", line).strip() for line in display.splitlines())


def _result_summary(row: dict[str, Any]) -> str:
    rows = row.get("result_rows_sample") or []
    observed = row.get("result_row_count_observed")
    if not rows:
        return f"empty sample; observed rows: {observed or 0}"
    first = rows[0]
    if isinstance(first, dict):
        parts = []
        for key, value in list(first.items())[:3]:
            text = textwrap.shorten(str(value), width=28, placeholder="...")
            parts.append(f"{key}: {text}")
        summary = "{" + ", ".join(parts) + "}"
    else:
        summary = textwrap.shorten(str(first), width=80, placeholder="...")
    if observed is not None:
        summary = f"{summary}; observed rows: {observed}"
    return summary


def _label(value: str) -> str:
    if value.lower() == "finbench":
        return "FinBench"
    if value.lower() == "snb":
        return "SNB"
    return _escape_latex(value.replace("_", " ").title())
