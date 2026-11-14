from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .conventions import CONVENTION_SHEET, CONVENTION_SHEET_VERSION, convention_sheet
from .llm import OpenAICompatibleLLM
from .models import (
    ExecutionResult,
    JudgeResult,
    NodeProperty,
    RelationshipPattern,
    RelationshipProperty,
    SchemaSummary,
    ValidationResult,
)
from .prompts import JUDGE_PROMPT, JUDGE_V3_PROMPT, JUDGE_V3_SYSTEM, SYSTEM_JSON_ENGINEER


class DeterministicJudge:
    """Conservative non-LLM judge used for offline smoke runs."""

    def __init__(
        self,
        *,
        min_semantic_alignment: float = 0.75,
        min_schema_use: float = 0.8,
        max_ambiguity: float = 0.35,
    ) -> None:
        self.min_semantic_alignment = min_semantic_alignment
        self.min_schema_use = min_schema_use
        self.max_ambiguity = max_ambiguity

    def judge(
        self,
        *,
        question: str,
        cypher: str,
        schema: SchemaSummary,
        validation: ValidationResult,
        execution: ExecutionResult,
    ) -> JudgeResult:
        ambiguity = 0.2
        semantic = 0.85
        schema_use = 1.0 if validation.schema_valid else 0.0
        reason = ""
        if not validation.ok:
            reason = "deterministic validation failed"
            semantic = 0.0
        elif execution.success and not execution.rows:
            reason = "execution returned no rows"
            semantic = 0.65
        passed = (
            not reason
            and ambiguity <= self.max_ambiguity
            and semantic >= self.min_semantic_alignment
            and schema_use >= self.min_schema_use
        )
        return JudgeResult(
            passed=passed,
            ambiguity_score=ambiguity,
            semantic_alignment_score=semantic,
            schema_use_score=schema_use,
            difficulty=validation.structural_features.get("difficulty", "unknown"),
            failure_reason="" if passed else reason or "below judge threshold",
        )


class LLMJudge:
    def __init__(
        self,
        llm: OpenAICompatibleLLM,
        fallback: DeterministicJudge,
        *,
        temperature: float = 0.0,
        max_tokens: int = 512,
        fail_closed: bool = False,
    ) -> None:
        self.llm = llm
        self.fallback = fallback
        self.temperature = temperature
        self.max_tokens = max_tokens
        # fail_closed: an LLM judge error rejects the candidate instead of
        # deferring to the rule-based judge (v1 accepted 43 items that way).
        self.fail_closed = fail_closed

    def judge(
        self,
        *,
        question: str,
        cypher: str,
        schema: SchemaSummary,
        validation: ValidationResult,
        execution: ExecutionResult,
    ) -> JudgeResult:
        prompt = JUDGE_PROMPT.format(
            schema=schema_slice_for_cypher(schema, cypher).to_prompt(max_items=80),
            question=question,
            cypher=cypher,
            rows=json.dumps(execution.rows[:5], default=str),
            validation=json.dumps(
                {
                    "ok": validation.ok,
                    "issues": [issue.__dict__ for issue in validation.issues],
                    "features": validation.structural_features,
                },
                default=str,
            ),
        )
        try:
            data: dict[str, Any] = self.llm.chat_json(
                system=SYSTEM_JSON_ENGINEER,
                user=prompt,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                response_format={"type": "json_object"},
            )
            result = JudgeResult(
                passed=bool(data.get("pass", False)),
                ambiguity_score=float(data.get("ambiguity_score", 1.0)),
                semantic_alignment_score=float(data.get("semantic_alignment_score", 0.0)),
                schema_use_score=float(data.get("schema_use_score", 0.0)),
                difficulty=str(
                    data.get(
                        "difficulty",
                        validation.structural_features.get("difficulty", "unknown"),
                    )
                ),
                failure_reason=str(data.get("failure_reason", "")),
                raw=data,
            )
            return override_categorical_result_value_rejection(
                result,
                cypher=cypher,
                validation=validation,
                execution=execution,
            )
        except Exception as exc:
            if self.fail_closed:
                result = JudgeResult.failed(f"llm judge error (fail-closed): {str(exc)[:200]}")
                result.raw = {"judge_error": str(exc)[:500], "fail_closed": True}
                return result
            result = self.fallback.judge(
                question=question,
                cypher=cypher,
                schema=schema,
                validation=validation,
                execution=execution,
            )
            result.raw = {"fallback_after_error": str(exc)}
            return result


def override_categorical_result_value_rejection(
    result: JudgeResult,
    *,
    cypher: str,
    validation: ValidationResult,
    execution: ExecutionResult,
) -> JudgeResult:
    """Correct a narrow LLM-judge failure mode around sampled categorical values.

    Categorical lists constrain literals written in the Cypher query. They do
    not constrain values observed in result rows, especially when an enterprise
    value-sampling policy redacts, hashes, or bounds categorical metadata.
    """

    if result.passed or not _is_categorical_result_value_false_rejection(
        result,
        cypher=cypher,
        validation=validation,
        execution=execution,
    ):
        return result

    raw = dict(result.raw)
    raw["original_judge"] = {
        "pass": result.passed,
        "ambiguity_score": result.ambiguity_score,
        "semantic_alignment_score": result.semantic_alignment_score,
        "schema_use_score": result.schema_use_score,
        "difficulty": result.difficulty,
        "failure_reason": result.failure_reason,
    }
    raw["override"] = "categorical_result_value_guard"
    return JudgeResult(
        passed=True,
        ambiguity_score=min(result.ambiguity_score, 0.2),
        semantic_alignment_score=max(result.semantic_alignment_score, 0.85),
        schema_use_score=max(result.schema_use_score, 1.0),
        difficulty=result.difficulty,
        failure_reason="",
        raw=raw,
    )


def _is_categorical_result_value_false_rejection(
    result: JudgeResult,
    *,
    cypher: str,
    validation: ValidationResult,
    execution: ExecutionResult,
) -> bool:
    if not validation.ok or not execution.success or not execution.rows:
        return False
    if any(issue.code == "invalid_categorical_value" for issue in validation.issues):
        return False

    reason = result.failure_reason.strip().lower()
    if not reason:
        return False
    categorical_terms = (
        "categorical",
        "valid value",
        "valid values",
        "allowed value",
        "allowed values",
        "schema defines",
        "schema-defined",
    )
    if not any(term in reason for term in categorical_terms):
        return False

    cypher_lower = cypher.lower()
    for value in _execution_string_values(execution):
        normalized = value.lower()
        if normalized in reason and normalized not in cypher_lower:
            return True
    return any(
        term in reason
        for term in ("execution sample", "result row", "result rows", "returns a value")
    )


def _execution_string_values(execution: ExecutionResult) -> set[str]:
    values: set[str] = set()
    for row in execution.rows[:5]:
        for value in row.values():
            if isinstance(value, str):
                text = value.strip()
                if 2 <= len(text) <= 100:
                    values.add(text)
    return values


def schema_slice_for_cypher(schema: SchemaSummary, cypher: str) -> SchemaSummary:
    labels = set(re.findall(r"\([^)]+:([A-Za-z_][A-Za-z0-9_]*)", cypher))
    rel_types = set(re.findall(r"\[[^\]]*:([A-Za-z_][A-Za-z0-9_]*)", cypher))
    prop_refs = set(re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b", cypher))
    variable_labels = {
        var: label
        for var, label in re.findall(r"\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([A-Za-z_][A-Za-z0-9_]*)", cypher)
    }
    prop_names_by_label: dict[str, set[str]] = {}
    for var, prop in prop_refs:
        label = variable_labels.get(var)
        if label:
            prop_names_by_label.setdefault(label, set()).add(prop)

    if rel_types:
        relationships = [rel for rel in schema.relationships if rel.type in rel_types]
    else:
        relationships = [
            rel
            for rel in schema.relationships
            if rel.start_label in labels or rel.end_label in labels
        ]
    for rel in relationships:
        labels.add(rel.start_label)
        labels.add(rel.end_label)
        rel_types.add(rel.type)

    node_properties = [
        prop
        for prop in schema.node_properties
        if prop.label in labels
        and (
            not prop_names_by_label.get(prop.label)
            or prop.property in prop_names_by_label[prop.label]
            or prop.property in {"id", "name", "title", "firstName", "lastName"}
        )
    ]
    relationship_properties = [
        prop for prop in schema.relationship_properties if prop.type in rel_types
    ]
    if not relationships and not node_properties:
        return schema
    return SchemaSummary(
        node_properties=_dedupe_node_properties(node_properties),
        relationship_properties=_dedupe_relationship_properties(relationship_properties),
        relationships=_dedupe_relationships(relationships),
        categorical_properties={
            key: values
            for key, values in schema.categorical_properties.items()
            if key.split(".", 1)[0] in labels
        },
        graph_name=schema.graph_name,
        # Keep the symmetric-type declaration: without it judges see only the
        # stored direction and penalize correct undirected KNOWS patterns.
        symmetric_relationships=[
            rel for rel in (getattr(schema, "symmetric_relationships", None) or []) if rel in rel_types
        ],
        source=f"{schema.source}:judge_slice",
    )


def _dedupe_node_properties(properties: list[NodeProperty]) -> list[NodeProperty]:
    seen: set[tuple[str, str, str]] = set()
    out: list[NodeProperty] = []
    for prop in properties:
        key = (prop.label, prop.property, prop.type)
        if key in seen:
            continue
        seen.add(key)
        out.append(prop)
    return out


def _dedupe_relationship_properties(properties: list[RelationshipProperty]) -> list[RelationshipProperty]:
    seen: set[tuple[str, str, str]] = set()
    out: list[RelationshipProperty] = []
    for prop in properties:
        key = (prop.type, prop.property, prop.value_type)
        if key in seen:
            continue
        seen.add(key)
        out.append(prop)
    return out


def _dedupe_relationships(relationships: list[RelationshipPattern]) -> list[RelationshipPattern]:
    seen: set[tuple[str, str, str]] = set()
    out: list[RelationshipPattern] = []
    for rel in relationships:
        key = (rel.start_label, rel.type, rel.end_label)
        if key in seen:
            continue
        seen.add(key)
        out.append(rel)
    return out


# ---------------------------------------------------------------------------
# Judge v3 (NAACL 2027 rebuild): convention sheet + checklist + panel gate.
# ---------------------------------------------------------------------------

CHECKLIST_CRITERIA: tuple[str, ...] = (
    "values",
    "relationships",
    "aggregation",
    "grouping",
    "comparisons",
    "ranking",
    "columns",
    "no_extra_constraints",
    "unambiguous",
)
# "na" is a valid answer everywhere except "unambiguous", where it fails closed.
CHECKLIST_NA_FAILS: frozenset[str] = frozenset({"unambiguous"})
_ANSWER_ALIASES = {
    "yes": "yes",
    "y": "yes",
    "true": "yes",
    "pass": "yes",
    "no": "no",
    "n": "no",
    "false": "no",
    "fail": "no",
    "na": "na",
    "n/a": "na",
    "n.a.": "na",
    "not applicable": "na",
    "none": "na",
}
# Frozen-contract hash: system text + prompt template + convention sheet.
JUDGE_V3_PROMPT_SHA256 = hashlib.sha256(
    (JUDGE_V3_SYSTEM + "\n" + JUDGE_V3_PROMPT + "\n" + CONVENTION_SHEET).encode("utf-8")
).hexdigest()
JUDGE_V3_EXECUTION_ROW_CAP = 25  # pipeline executes candidates with limit_rows=25


def _normalize_answer(value: Any) -> str | None:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if value is None:
        return None
    text = str(value).strip().lower().strip(".")
    if text in _ANSWER_ALIASES:
        return _ANSWER_ALIASES[text]
    text = text.replace("_", " ")
    return _ANSWER_ALIASES.get(text)


def parse_checklist(data: Any) -> dict[str, dict[str, str]]:
    """Normalize a checklist judge response to ``{criterion: {answer, evidence}}``.

    Accepts the criteria at the top level or under ``criteria``/``checklist``;
    a criterion may be an object (``answer``/``verdict`` + ``evidence``) or a
    bare yes/no/na value. Unknown answers are recorded as ``invalid``.
    """

    if not isinstance(data, dict):
        return {}
    source = data
    for key in ("criteria", "checklist"):
        if isinstance(data.get(key), dict):
            source = data[key]
            break
    parsed: dict[str, dict[str, str]] = {}
    for name in CHECKLIST_CRITERIA:
        item = source.get(name)
        if item is None:
            continue
        if isinstance(item, dict):
            raw_answer = item.get("answer", item.get("verdict", item.get("value")))
            evidence = item.get("evidence", item.get("reason", ""))
        else:
            raw_answer, evidence = item, ""
        answer = _normalize_answer(raw_answer)
        parsed[name] = {
            "answer": answer or "invalid",
            "evidence": str(evidence or "")[:600],
        }
    return parsed


def compute_checklist_verdict(checklist: dict[str, dict[str, str]]) -> tuple[bool, list[str], list[str]]:
    """Return ``(passed, failing_criteria, missing_criteria)``.

    The verdict is computed by code: an item passes only when every criterion
    is present, none is answered "no" (or an invalid value), and
    "unambiguous" is answered "yes".
    """

    missing = [name for name in CHECKLIST_CRITERIA if name not in checklist]
    failing: list[str] = []
    for name in CHECKLIST_CRITERIA:
        entry = checklist.get(name)
        if entry is None:
            continue
        answer = entry.get("answer")
        if answer == "no" or answer == "invalid" or (answer == "na" and name in CHECKLIST_NA_FAILS):
            failing.append(name)
    return (not missing and not failing), failing, missing


def _row_summary(execution: ExecutionResult, row_count: int | None) -> str:
    if not execution.success:
        return f"execution failed ({(execution.error or '')[:120]})"
    n = row_count if row_count is not None else len(execution.rows)
    if row_count is None and n >= JUDGE_V3_EXECUTION_ROW_CAP:
        return f"at least {n} rows (execution was capped at {JUDGE_V3_EXECUTION_ROW_CAP}); first 5 shown"
    shown = min(5, len(execution.rows))
    return f"{n} row{'s' if n != 1 else ''} returned; first {shown} shown"


def render_judge_v3_prompt(
    *,
    question: str,
    cypher: str,
    schema: SchemaSummary,
    validation: ValidationResult,
    execution: ExecutionResult,
    schema_mode: str = "full",
    row_count: int | None = None,
) -> str:
    """Render the v3 checklist prompt. ``schema_mode`` is "full" (cacheable) or "slice" (v2)."""

    if schema_mode == "slice":
        schema_text = schema_slice_for_cypher(schema, cypher).to_prompt(max_items=80)
    elif schema_mode == "full":
        schema_text = schema.to_prompt()
    else:
        raise ValueError("schema_mode must be 'full' or 'slice'")
    notes = [issue.message for issue in validation.issues if issue.level != "error"]
    # Deterministic findings the validator does not report (schema triples
    # inside subqueries, variables dropped by WITH); defined later in this module.
    notes.extend(deterministic_judge_notes(cypher, schema))
    return JUDGE_V3_PROMPT.format(
        conventions=convention_sheet(schema),
        schema=schema_text,
        question=question,
        cypher=cypher,
        row_summary=_row_summary(execution, row_count),
        rows=json.dumps(execution.rows[:5], default=str),
        features=json.dumps(validation.structural_features, default=str, sort_keys=True),
        notes=json.dumps(notes) if notes else "none",
    )


class ChecklistJudge:
    """v3 judge: convention sheet + per-criterion checklist; code decides the verdict."""

    judge_mode = "checklist"

    def __init__(
        self,
        llm: OpenAICompatibleLLM,
        *,
        label: str = "",
        temperature: float = 0.0,
        max_tokens: int = 2048,
        schema_mode: str = "full",
        fail_closed: bool = True,
        parse_retries: int = 1,
        fallback: DeterministicJudge | None = None,
    ) -> None:
        if schema_mode not in {"full", "slice"}:
            raise ValueError("schema_mode must be 'full' or 'slice'")
        self.llm = llm
        self.label = label or str(getattr(llm, "model", "judge"))
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.schema_mode = schema_mode
        self.fail_closed = fail_closed
        self.parse_retries = max(0, parse_retries)
        self.fallback = fallback

    @property
    def model(self) -> str:
        return str(getattr(self.llm, "model", ""))

    def judge(
        self,
        *,
        question: str,
        cypher: str,
        schema: SchemaSummary,
        validation: ValidationResult,
        execution: ExecutionResult,
        row_count: int | None = None,
    ) -> JudgeResult:
        prompt = render_judge_v3_prompt(
            question=question,
            cypher=cypher,
            schema=schema,
            validation=validation,
            execution=execution,
            schema_mode=self.schema_mode,
            row_count=row_count,
        )
        last_error: Exception | None = None
        data: Any = None
        for _ in range(self.parse_retries + 1):
            try:
                data = self.llm.chat_json(
                    system=JUDGE_V3_SYSTEM,
                    user=prompt,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    response_format={"type": "json_object"},
                )
                if isinstance(data, dict):
                    last_error = None
                    break
                last_error = ValueError("judge returned non-object JSON")
            except Exception as exc:  # network, budget, or JSON errors
                last_error = exc
                if type(exc).__name__ in {"BudgetExceededError", "FatalLLMError"}:
                    break
        if last_error is not None or not isinstance(data, dict):
            reason = str(last_error)[:200] if last_error else "no judge output"
            if not self.fail_closed and self.fallback is not None:
                result = self.fallback.judge(
                    question=question, cypher=cypher, schema=schema, validation=validation, execution=execution
                )
                result.raw = {"fallback_after_error": reason, "judge_mode": self.judge_mode}
                return result
            result = JudgeResult.failed(f"llm judge error (fail-closed): {reason}")
            result.raw = {
                "judge_error": reason,
                "fail_closed": True,
                "judge_mode": self.judge_mode,
                "judge_label": self.label,
                "model": self.model,
            }
            return result

        checklist = parse_checklist(data)
        passed, failing, missing = compute_checklist_verdict(checklist)
        applicable = [entry for entry in checklist.values() if entry["answer"] in {"yes", "no"}]
        semantic = (
            sum(1 for entry in applicable if entry["answer"] == "yes") / len(applicable) if applicable else 0.0
        )
        unambiguous = checklist.get("unambiguous", {}).get("answer") == "yes"
        reasons = []
        if missing:
            reasons.append("checklist incomplete: missing " + ", ".join(missing))
        for name in failing:
            evidence = checklist[name].get("evidence", "")
            reasons.append(f"{name}={checklist[name]['answer']}: {evidence}"[:300])
        difficulty = str(data.get("difficulty") or validation.structural_features.get("difficulty", "unknown"))
        result = JudgeResult(
            passed=passed,
            ambiguity_score=0.0 if unambiguous else 1.0,
            semantic_alignment_score=round(semantic, 4),
            schema_use_score=1.0 if validation.schema_valid else 0.0,
            difficulty=difficulty if difficulty in {"easy", "medium", "hard"} else "unknown",
            failure_reason="" if passed else "; ".join(reasons)[:900],
            raw={
                "judge_mode": self.judge_mode,
                "judge_label": self.label,
                "model": self.model,
                "checklist": checklist,
                "failing": failing,
                "missing": missing,
                "query_reading": str(data.get("query_reading") or "")[:600],
                "clarified_question": str(data.get("clarified_question") or "")[:500],
                "judge_difficulty": str(data.get("difficulty") or ""),
                "prompt_sha256": JUDGE_V3_PROMPT_SHA256,
                "convention_sheet_version": CONVENTION_SHEET_VERSION,
                "schema_mode": self.schema_mode,
            },
        )
        return override_categorical_result_value_rejection(
            result,
            cypher=cypher,
            validation=validation,
            execution=execution,
        )


class JudgePanel:
    """Gate that accepts an item only when every member judge accepts it.

    Members are any objects with the ``judge(question=, cypher=, schema=,
    validation=, execution=)`` interface (``LLMJudge`` or ``ChecklistJudge``).
    Every member always runs (no short-circuit), so judge-judge agreement can
    be reported on every gated item; members run in parallel threads.
    """

    judge_mode = "panel"

    def __init__(self, members: list[tuple[str, Any]], *, parallel: bool = True) -> None:
        if len(members) < 2:
            raise ValueError("a judge panel needs at least two members")
        labels = [label for label, _ in members]
        if len(set(labels)) != len(labels):
            raise ValueError(f"judge panel labels must be unique: {labels}")
        self.members = list(members)
        self.parallel = parallel

    @property
    def llm(self) -> Any:
        """First member's LLM, for code that records the primary judge model."""
        return getattr(self.members[0][1], "llm", None)

    @property
    def models(self) -> dict[str, str]:
        return {
            label: str(getattr(getattr(member, "llm", None), "model", "") or getattr(member, "model", ""))
            for label, member in self.members
        }

    def judge(
        self,
        *,
        question: str,
        cypher: str,
        schema: SchemaSummary,
        validation: ValidationResult,
        execution: ExecutionResult,
        **kwargs: Any,
    ) -> JudgeResult:
        def run(member: Any) -> JudgeResult:
            extra = kwargs if isinstance(member, ChecklistJudge) else {}
            return member.judge(
                question=question,
                cypher=cypher,
                schema=schema,
                validation=validation,
                execution=execution,
                **extra,
            )

        if self.parallel:
            with ThreadPoolExecutor(max_workers=len(self.members)) as pool:
                results = list(pool.map(lambda item: run(item[1]), self.members))
        else:
            results = [run(member) for _, member in self.members]
        return combine_panel_results(list(zip([label for label, _ in self.members], results)), self.models)


def combine_panel_results(
    labelled: list[tuple[str, JudgeResult]],
    models: dict[str, str] | None = None,
) -> JudgeResult:
    """Unanimous-accept rule over member results; records every member verdict."""

    models = models or {}
    passed = all(result.passed for _, result in labelled)
    reasons = [f"[{label}] {result.failure_reason}" for label, result in labelled if not result.passed]
    members = [
        {
            "label": label,
            "model": models.get(label, ""),
            "passed": result.passed,
            "failure_reason": result.failure_reason,
            "ambiguity_score": result.ambiguity_score,
            "semantic_alignment_score": result.semantic_alignment_score,
            "raw": result.raw,
        }
        for label, result in labelled
    ]
    first = labelled[0][1]
    return JudgeResult(
        passed=passed,
        ambiguity_score=max(result.ambiguity_score for _, result in labelled),
        semantic_alignment_score=min(result.semantic_alignment_score for _, result in labelled),
        schema_use_score=min(result.schema_use_score for _, result in labelled),
        difficulty=first.difficulty,
        failure_reason="" if passed else " | ".join(reasons)[:1500],
        raw={
            "judge_mode": "panel",
            "panel_rule": "all_accept",
            "panel_unanimous": len({result.passed for _, result in labelled}) == 1,
            "panel": members,
        },
    )


PANEL_SPEC_KEYS = frozenset(
    {
        "label",
        "model",
        "provider",
        "base_url",
        "provider_routing",
        "reasoning_effort",
        "max_tokens",
        "temperature",
        "send_temperature",
        "system_message_mode",
        "seed",
    }
)


def validate_panel_spec(panel: list[dict[str, Any]]) -> list[str]:
    """Return config errors for ``judge.panel`` entries (unknown keys, missing model/label)."""

    errors: list[str] = []
    if not isinstance(panel, list):
        return ["judge.panel must be a list of judge specs"]
    labels: list[str] = []
    for index, spec in enumerate(panel):
        if not isinstance(spec, dict):
            errors.append(f"judge.panel[{index}] must be a mapping")
            continue
        unknown = sorted(set(spec) - PANEL_SPEC_KEYS)
        if unknown:
            errors.append(f"judge.panel[{index}] has unknown keys: {', '.join(unknown)}")
        for key in ("label", "model"):
            if not str(spec.get(key) or "").strip():
                errors.append(f"judge.panel[{index}].{key} is required")
        labels.append(str(spec.get("label") or ""))
    if len(set(labels)) != len(labels):
        errors.append("judge.panel labels must be unique")
    if "primary" in labels:
        errors.append("judge.panel label 'primary' is reserved for models.judge_model")
    return errors


def _seed_kwargs(seed: Any) -> dict[str, Any]:
    if seed is None:
        return {}
    import inspect

    if "seed" not in inspect.signature(OpenAICompatibleLLM.__init__).parameters:
        return {}
    return {"seed": int(seed)}


def build_judge(cfg: Any, *, label_for: Any = None, usage_ledger: str | None = None) -> Any:
    """Construct the configured judge gate from a ``RunConfig``.

    * ``judge.mode == "v2"`` and no panel: identical to the v2 construction in
      ``scripts/run_pipeline.py`` (``LLMJudge``, original prompt).
    * ``judge.mode == "checklist"``: ``ChecklistJudge`` with the convention sheet.
    * ``judge.panel`` non-empty: ``JudgePanel`` of the primary judge
      (``models.judge_model``, label "primary") plus every panel member, all in
      the configured mode; an item passes only if every member passes.
    """

    label_for = label_for or (lambda role: role)
    judge_cfg = cfg.judge
    models = cfg.models
    mode = str(getattr(judge_cfg, "mode", "v2") or "v2")
    if mode not in {"v2", "checklist"}:
        raise ValueError("judge.mode must be 'v2' or 'checklist'")
    panel = list(getattr(judge_cfg, "panel", None) or [])
    errors = validate_panel_spec(panel)
    if errors:
        raise ValueError("; ".join(errors))
    fallback = DeterministicJudge(
        min_semantic_alignment=judge_cfg.min_semantic_alignment,
        min_schema_use=judge_cfg.min_schema_use,
        max_ambiguity=judge_cfg.max_ambiguity,
    )
    fail_closed = not judge_cfg.deterministic_fallback
    schema_mode = str(getattr(judge_cfg, "schema_mode", "full") or "full")

    primary_provider = models.judge_provider or models.provider
    primary_llm = OpenAICompatibleLLM(
        models.judge_base_url or models.llm_base_url,
        models.judge_model,
        timeout_sec=models.request_timeout_sec,
        reasoning_effort=models.reasoning_effort,
        include_reasoning=models.include_reasoning,
        enable_thinking=models.enable_thinking,
        strip_reasoning=models.strip_reasoning,
        provider=primary_provider,
        send_temperature=models.send_temperature if primary_provider == models.provider else True,
        provider_routing=models.provider_routing if primary_provider == "openrouter" else None,
        usage_ledger=usage_ledger,
        call_label=label_for("judge"),
        **_seed_kwargs(getattr(models, "request_seed", None)),
    )
    primary_max_tokens = 512 if primary_provider == "vllm" else max(512, models.max_tokens)

    def make(llm: OpenAICompatibleLLM, label: str, max_tokens: int, temperature: float = 0.0) -> Any:
        if mode == "checklist":
            return ChecklistJudge(
                llm,
                label=label,
                temperature=temperature,
                max_tokens=max(max_tokens, 1024),
                schema_mode=schema_mode,
                fail_closed=fail_closed,
                fallback=fallback,
            )
        return LLMJudge(llm, fallback, temperature=temperature, max_tokens=max_tokens, fail_closed=fail_closed)

    primary = make(primary_llm, "primary", primary_max_tokens)
    if not panel:
        return primary
    members: list[tuple[str, Any]] = [("primary", primary)]
    for spec in panel:
        provider = str(spec.get("provider") or "openrouter")
        llm = OpenAICompatibleLLM(
            str(spec.get("base_url") or models.llm_base_url),
            str(spec["model"]),
            timeout_sec=models.request_timeout_sec,
            reasoning_effort=spec.get("reasoning_effort", models.reasoning_effort),
            include_reasoning=models.include_reasoning,
            enable_thinking=models.enable_thinking,
            strip_reasoning=models.strip_reasoning,
            provider=provider,
            send_temperature=bool(spec.get("send_temperature", True)),
            provider_routing=spec.get("provider_routing") if provider == "openrouter" else None,
            system_message_mode=str(spec.get("system_message_mode") or "separate"),
            usage_ledger=usage_ledger,
            call_label=label_for(f"judge_{spec['label']}"),
            # Only members whose provider supports `seed` should set it.
            **_seed_kwargs(spec.get("seed")),
        )
        members.append(
            (
                str(spec["label"]),
                make(llm, str(spec["label"]), int(spec.get("max_tokens") or 2048), float(spec.get("temperature", 0.0))),
            )
        )
    return JudgePanel(members)


# ---------------------------------------------------------------------------
# Deterministic schema-triple check (v3). The validator checks labels,
# properties, and simple MATCH directions, but v2 accepted references whose
# patterns use a (start label, type, end label) triple the schema never lists,
# e.g. inside NOT EXISTS subqueries: (Person)-[:HAS_CREATOR]->(Comment), or
# (Person)-[:IS_LOCATED_IN]->(Country) on SNB. Such patterns never match, so the
# reference silently returns 0 / an ineffective exclusion. The check is
# conservative: it only reports triples whose two end labels are known.
# ---------------------------------------------------------------------------

_NODE_RE = re.compile(
    r"\(\s*(?P<var>[A-Za-z_][A-Za-z0-9_]*)?\s*(?P<labels>(?::\s*`?[A-Za-z_][A-Za-z0-9_]*`?\s*)*)(?:\{[^{}]*\})?\s*\)"
)
_REL_RE = re.compile(
    r"\s*(?P<left><)?-\s*(?:\[\s*(?P<var>[A-Za-z_][A-Za-z0-9_]*)?\s*(?::\s*(?P<types>[A-Za-z_][A-Za-z0-9_]*(?:\s*\|\s*:?\s*[A-Za-z_][A-Za-z0-9_]*)*))?"
    r"\s*(?P<hops>\*[0-9.\s]*)?\s*(?:\{[^{}]*\})?\s*\])?\s*-(?P<right>>)?\s*"
)


def _mask_literals(query: str) -> str:
    out: list[str] = []
    quote: str | None = None
    escaped = False
    for char in query:
        if quote:
            if escaped:
                escaped = False
                out.append("_")
            elif char == "\\":
                escaped = True
                out.append("_")
            elif char == quote:
                quote = None
                out.append(char)
            else:
                out.append("_")
            continue
        if char in {"'", '"'}:
            quote = char
        out.append(char)
    return "".join(out)


def _labels_of(text: str) -> list[str]:
    return [label.strip("` ") for label in re.findall(r":\s*(`?[A-Za-z_][A-Za-z0-9_]*`?)", text or "")]


def relationship_pattern_triples(cypher: str) -> list[tuple[str | None, str, str | None, str]]:
    """Return ``(start_label, type, end_label, direction)`` for every relationship hop.

    ``direction`` is "out" (stored start -> end as written left-to-right),
    "in", or "both". Labels come from the node itself or from the variable's
    label anywhere else in the query; unknown labels are ``None``.
    """

    masked = _mask_literals(cypher)
    var_labels: dict[str, str] = {}
    for match in _NODE_RE.finditer(masked):
        labels = _labels_of(match.group("labels"))
        if match.group("var") and labels:
            var_labels.setdefault(match.group("var"), labels[0])
    triples: list[tuple[str | None, str, str | None, str]] = []
    pos = 0
    while True:
        node = _NODE_RE.search(masked, pos)
        if not node:
            break
        current = node
        while True:
            rel = _REL_RE.match(masked, current.end())
            if not rel or rel.end() == current.end():
                break
            nxt = _NODE_RE.match(masked, rel.end())
            if not nxt:
                break
            types = [t.strip(" :") for t in (rel.group("types") or "").split("|") if t.strip(" :")]
            left = (_labels_of(current.group("labels")) or [var_labels.get(current.group("var") or "")])[0]
            right = (_labels_of(nxt.group("labels")) or [var_labels.get(nxt.group("var") or "")])[0]
            if rel.group("left") and not rel.group("right"):
                direction = "in"
            elif rel.group("right") and not rel.group("left"):
                direction = "out"
            else:
                direction = "both"
            for rel_type in types:
                triples.append((left or None, rel_type, right or None, direction))
            current = nxt
        pos = current.end()
    return triples


def unlisted_relationship_patterns(cypher: str, schema: SchemaSummary) -> list[str]:
    """Patterns whose (start, type, end) triple, in the written direction, is not in the schema.

    Symmetric relationship types may be written in either direction. Hops with
    an unknown end label are skipped (no false alarms on untyped nodes).
    """

    listed = {(rel.start_label, rel.type, rel.end_label) for rel in schema.relationships}
    known_types = {rel.type for rel in schema.relationships}
    symmetric = set(getattr(schema, "symmetric_relationships", None) or [])
    issues: list[str] = []
    for left, rel_type, right, direction in relationship_pattern_triples(cypher):
        if not left or not right or rel_type not in known_types:
            continue
        forward = (left, rel_type, right) in listed
        backward = (right, rel_type, left) in listed
        if direction == "out":
            ok = forward or (rel_type in symmetric and backward)
            shown = f"({left})-[:{rel_type}]->({right})"
        elif direction == "in":
            ok = backward or (rel_type in symmetric and forward)
            shown = f"({left})<-[:{rel_type}]-({right})"
        else:
            ok = forward or backward
            shown = f"({left})-[:{rel_type}]-({right})"
        if not ok and shown not in issues:
            issues.append(shown)
    return issues


_CLAUSE_SPLIT_RE = re.compile(
    r"\b(OPTIONAL\s+MATCH|MATCH|WITH|UNWIND|WHERE|RETURN|ORDER\s+BY|SKIP|LIMIT|CALL|UNION)\b", re.I
)


def dropped_with_variables(cypher: str) -> list[str]:
    """Variables bound before a WITH, not carried by it, and used again in a later pattern.

    Cypher then binds the name afresh, so ``MATCH (p:Person {id: 1}) ... WITH
    collect(x) AS xs MATCH (p)<-[:HAS_CREATOR]-(m)`` silently matches every
    node as ``p``. Returns readable notes; skips queries with CALL or UNION.
    """

    masked = _mask_literals(cypher)
    if re.search(r"\b(CALL|UNION)\b", masked, re.I):
        return []
    depth_at: list[int] = []
    depth = 0
    for char in masked:
        depth_at.append(depth)
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
    # Clause keywords at bracket depth 0 only (not inside EXISTS {...}, CASE, lists).
    matches = [m for m in _CLAUSE_SPLIT_RE.finditer(masked) if depth_at[m.start()] == 0]
    parts: list[tuple[str, str, int]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(masked)
        parts.append((re.sub(r"\s+", " ", match.group(1).upper()), masked[match.end():end], end))
    bound: set[str] = set()
    notes: list[str] = []
    for keyword, body, body_end in parts:
        if keyword == "WITH":
            projection = body.strip()
            if projection.upper().startswith("DISTINCT"):
                projection = projection[8:]
            if projection.strip().startswith("*"):
                continue
            carried: set[str] = set()
            depth = 0
            item = ""
            items: list[str] = []
            for char in projection:
                if char in "([{":
                    depth += 1
                elif char in ")]}":
                    depth -= 1
                if char == "," and depth == 0:
                    items.append(item)
                    item = ""
                else:
                    item += char
            items.append(item)
            for raw in items:
                raw = raw.strip()
                alias = re.search(r"\bAS\s+([A-Za-z_][A-Za-z0-9_]*)\s*$", raw, re.I)
                if alias:
                    carried.add(alias.group(1))
                elif re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", raw):
                    carried.add(raw)
            dropped = bound - carried
            bound = set(carried)
            # look ahead: later patterns that reuse a dropped name
            later = masked[body_end:]
            for name in sorted(dropped):
                if re.search(r"\(\s*" + re.escape(name) + r"\s*[:)\s{]", later) or re.search(
                    r"\[\s*" + re.escape(name) + r"\s*[:\]]", later
                ):
                    note = f"variable `{name}` is not carried through WITH and is re-bound to any node later"
                    if note not in notes:
                        notes.append(note)
            continue
        if keyword in {"MATCH", "OPTIONAL MATCH", "UNWIND"}:
            for node in _NODE_RE.finditer(body):
                if node.group("var"):
                    bound.add(node.group("var"))
            for rel in re.finditer(r"\[\s*([A-Za-z_][A-Za-z0-9_]*)", body):
                bound.add(rel.group(1))
            if keyword == "UNWIND":
                alias = re.search(r"\bAS\s+([A-Za-z_][A-Za-z0-9_]*)", body, re.I)
                if alias:
                    bound.add(alias.group(1))
    return notes


def deterministic_judge_notes(cypher: str, schema: SchemaSummary) -> list[str]:
    """Deterministic findings shown to the v3 judge (and usable as gates)."""

    notes = [
        f"pattern {pattern} is not listed in the schema, so it never matches"
        for pattern in unlisted_relationship_patterns(cypher, schema)
    ]
    notes.extend(dropped_with_variables(cypher))
    return notes
