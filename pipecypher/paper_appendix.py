from __future__ import annotations

import hashlib
import json
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .prompts import (
    CYPHER_GENERATION_PROMPT,
    JUDGE_PROMPT,
    REPAIR_PROMPT,
    REVERSE_CYPHER_PROMPT,
    TEMPLATE_GENERATION_PROMPT,
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
        (
            "PIPE-Cypher treats prompts as versioned implementation artifacts. "
            "The table summarizes the prompt contracts used for generation, repair, "
            "judging, and downstream evaluation; hashes fingerprint the full prompt "
            "constants in the codebase."
        ),
        r"\begin{table*}[t]",
        r"\centering",
        r"\small",
        (
            r"\begin{tabular}{p{0.16\textwidth}p{0.18\textwidth}"
            r"p{0.50\textwidth}p{0.10\textwidth}}"
        ),
        r"\toprule",
        r"Prompt & Pipeline stage & Contract summary & SHA-256 \\",
        r"\midrule",
    ]
    for contract in prompt_contracts():
        rows.append(
            "{name} & {stage} & {constraints} & \\texttt{{{sha}}} \\\\".format(
                name=_escape_latex(contract.name),
                stage=_escape_latex(contract.stage),
                constraints=_escape_latex("; ".join(contract.constraints)),
                sha=contract.sha256[:6],
            )
        )
    rows.extend(
        [
            r"\bottomrule",
            r"\end{tabular}",
            (
                r"\caption{Prompt contracts used by PIPE-Cypher. Hashes fingerprint "
                r"the full prompt constants in the released code; the table summarizes "
                r"the enforceable constraints without depending on generated prose.}"
            ),
            r"\label{tab:prompt_contracts}",
            r"\end{table*}",
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
    cypher = _wrap_code(str(row.get("cypher", "")), width=64)
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
        r"\begin{quote}\scriptsize\ttfamily\raggedright",
        cypher,
        r"\end{quote}",
        (
            "\\textit{{Structure:}} {tags}; relationships: {relationships}; gates: {gates}.\\par "
            "\\textit{{Result sample:}} {result}"
        ).format(
            tags=_escape_latex(tags or "none"),
            relationships=_escape_latex(relationships or "none"),
            gates=_escape_latex(gate_summary or "none"),
            result=result,
        ),
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


def _wrap_code(value: str, *, width: int) -> str:
    lines = textwrap.wrap(
        value,
        width=width,
        break_long_words=True,
        break_on_hyphens=False,
    )
    if not lines:
        return ""
    return "\\\\\n".join(_escape_latex(line) for line in lines)


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
