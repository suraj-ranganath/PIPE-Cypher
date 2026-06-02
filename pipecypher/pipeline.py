from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
import json
from pathlib import Path
from typing import Any

from .config import RunConfig
from .cypher_client import Neo4jCypherClient, NullCypherClient
from .diversity import EntityDiversityTracker, StructuralDiversityTracker
from .empty_result_diagnostics import diagnose_empty_result
from .graph_profiles import default_cypher_for_template, default_reverse_cypher_for_template, default_templates
from .io import append_jsonl
from .judge import DeterministicJudge, LLMJudge
from .llm import NullLLM, OpenAICompatibleLLM
from .models import ExecutionResult, GenerationRecord, JudgeResult, SchemaSummary, TemplateCandidate, ValidationResult
from .prompts import (
    REPAIR_PROMPT,
    REVERSE_CYPHER_PROMPT,
    SYSTEM_CYPHER_ENGINEER,
    SYSTEM_JSON_ENGINEER,
    TEMPLATE_GENERATION_PROMPT,
    render_cypher_generation_prompt,
)
from .question_constraints import apply_question_constraints
from .retrieval import ExampleStore
from .schema_templates import SCHEMA_TEMPLATE_KIND, schema_derived_templates
from .value_grounding import ValueGrounder
from .validator import validate_cypher


def question_key(category: str, question: str) -> tuple[str, str]:
    return category, " ".join(question.lower().split())


@dataclass
class PipelineResult:
    records: list[GenerationRecord]
    output_path: Path


class PipeCypherPipeline:
    def __init__(
        self,
        *,
        config: RunConfig,
        schema: SchemaSummary,
        client: Neo4jCypherClient | NullCypherClient,
        llm: OpenAICompatibleLLM | NullLLM,
        judge: LLMJudge | DeterministicJudge,
        examples: ExampleStore | None = None,
        seen_question_keys: set[tuple[str, str]] | None = None,
    ) -> None:
        self.config = config
        self.schema = schema
        self.client = client
        self.llm = llm
        self.judge = judge
        self.examples = examples or ExampleStore()
        self.entity_diversity = EntityDiversityTracker(config.generation.max_entity_pct)
        self.structural_diversity = StructuralDiversityTracker()
        self.slot_binding_offsets: Counter[str] = Counter()
        self.accepted_question_keys: set[tuple[str, str]] = set(seen_question_keys or set())
        self.exhausted_slot_templates: set[str] = set()
        self.rng = random.Random(config.generation.random_seed)

    def _validate_cypher(self, cypher: str) -> ValidationResult:
        return validate_cypher(
            cypher,
            self.schema,
            normalize=self.config.generation.normalize_cypher,
        )

    def generate_templates(self, category: str) -> list[TemplateCandidate]:
        n = self.config.generation.template_candidates
        seeded = [template for template in default_templates(self.config.generation.graph_profile) if template.category == category]
        derived = schema_derived_templates(self.schema, category, max_templates=max(n * 4, 24))
        source = self.config.generation.template_source.lower()
        if source == "default":
            return self._dedupe_templates([*seeded, *derived])[: max(n, len(seeded), len(derived))]

        prompt = TEMPLATE_GENERATION_PROMPT.format(
            schema=self.schema.to_prompt(),
            n=n,
            category=category,
        )
        try:
            data = self.llm.chat_json(
                system=SYSTEM_JSON_ENGINEER,
                user=prompt,
                temperature=self.config.models.temperature,
                max_tokens=self.config.models.max_tokens,
            )
            generated = [
                TemplateCandidate(
                    template=str(item["template"]),
                    category=category,
                    slots=self._parse_template_slots(item.get("slots", [])),
                    rationale=str(item.get("rationale", "")),
                )
                for item in data
                if isinstance(item, dict) and item.get("template")
            ]
            if source == "mixed":
                return self._dedupe_templates([*seeded, *derived, *generated])[
                    : max(n, len(seeded), len(derived))
                ]
            return generated
        except Exception:
            if not self.config.generation.allow_seed_template_fallback:
                return []
            return self._dedupe_templates([*seeded, *derived])[: max(n, len(seeded), len(derived))]

    @staticmethod
    def _dedupe_templates(templates: list[TemplateCandidate]) -> list[TemplateCandidate]:
        seen: set[str] = set()
        deduped: list[TemplateCandidate] = []
        for template in templates:
            key = template.template.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(template)
        return deduped

    def _parse_template_slots(self, raw_slots: Any) -> dict[str, str]:
        if isinstance(raw_slots, dict):
            return {str(slot): str(label_prop) for slot, label_prop in raw_slots.items()}
        slots: dict[str, str] = {}
        if not isinstance(raw_slots, list):
            return slots
        for item in raw_slots:
            if isinstance(item, str):
                slots[item] = self._infer_label_property(item)
            elif isinstance(item, dict):
                slot = item.get("slot") or item.get("name") or item.get("placeholder")
                label_prop = item.get("label_property") or item.get("property") or item.get("schema_path")
                if slot:
                    slots[str(slot)] = str(label_prop or self._infer_label_property(str(slot)))
        return slots

    def _infer_label_property(self, slot: str, label_prop: str = "") -> str:
        if "." in label_prop:
            return label_prop
        slot_lower = slot.lower()
        for prop in self.schema.node_properties:
            if prop.property.lower() == slot_lower:
                return f"{prop.label}.{prop.property}"
        preferred = {
            "person": "Person.personName",
            "personname": "Person.personName",
            "personid": "Person.id",
            "company": "Company.companyName",
            "companyname": "Company.companyName",
            "account": "Account.accountId",
            "accountid": "Account.accountId",
            "accounttype": "Account.accountType",
            "loan": "Loan.loanId",
            "loanid": "Loan.loanId",
            "loanusage": "Loan.loanUsage",
            "medium": "Medium.mediumId",
            "mediumid": "Medium.mediumId",
            "tag": "Tag.name",
            "tagname": "Tag.name",
        }
        if slot_lower in preferred:
            return preferred[slot_lower]
        return label_prop

    def reverse_query(self, template: TemplateCandidate) -> str:
        default_reverse = default_reverse_cypher_for_template(
            template,
            limit=self.config.generation.generated_query_limit,
        )
        if default_reverse:
            return default_reverse

        prompt = REVERSE_CYPHER_PROMPT.format(
            schema=self.schema.to_prompt(),
            template=template.template,
            slots=", ".join(template.slots) or "None",
            limit=self.config.generation.generated_query_limit,
        )
        try:
            return self.llm.chat(
                system=SYSTEM_CYPHER_ENGINEER,
                user=prompt,
                temperature=0.1,
                max_tokens=512,
            ).text
        except Exception:
            fallback = self._generic_slot_lookup_query(template)
            if fallback:
                return fallback
            if not template.slots:
                return "RETURN DISTINCT 1 AS noSlots LIMIT 1"
            first_slot = next(iter(template.slots))
            label_prop = template.slots.get(first_slot, "")
            label, prop = (label_prop.split(".", 1) + ["name"])[:2] if "." in label_prop else ("Person", "name")
            return f"MATCH ({first_slot}:{label}) RETURN DISTINCT {first_slot}.{prop} AS {first_slot} LIMIT {self.config.generation.generated_query_limit}"

    def fill_template(self, template: TemplateCandidate, bindings: dict[str, Any] | None = None) -> tuple[str, dict[str, str]]:
        question = template.template
        hints = {}
        bindings = bindings or {}
        for slot, label_prop in template.slots.items():
            value = str(bindings.get(slot) or slot)
            question = question.replace("{" + slot + "}", value)
            hints[slot] = f"{value} | {label_prop}"
        return question, hints

    def bind_slots(self, template: TemplateCandidate) -> tuple[dict[str, Any], str | None]:
        if not template.slots:
            return {}, None
        reverse = self.reverse_query(template)
        bindings, used_reverse = self._try_bind_slots(template, reverse)
        if bindings:
            return bindings, used_reverse
        fallback = self._generic_slot_lookup_query(template)
        if (
            fallback
            and fallback != used_reverse
            and self._template_identity(template) not in self.exhausted_slot_templates
            and not template.metadata.get(SCHEMA_TEMPLATE_KIND)
        ):
            return self._try_bind_slots(template, fallback)
        return {}, used_reverse

    def _try_bind_slots(self, template: TemplateCandidate, reverse: str) -> tuple[dict[str, Any], str]:
        validation = self._validate_cypher(reverse)
        if not validation.ok:
            return {}, validation.normalized_cypher
        execution = self.client.run(
            validation.normalized_cypher,
            limit_rows=self.config.generation.generated_query_limit,
        )
        if not execution.success or not execution.rows:
            return {}, validation.normalized_cypher
        rows = [
            row
            for row in execution.rows
            if all(self._is_valid_binding_value(row.get(slot)) for slot in template.slots)
        ]
        if not rows:
            return {}, validation.normalized_cypher
        key = f"{template.category}:{template.template}:{validation.normalized_cypher}"
        offset = self.slot_binding_offsets[key]
        for step in range(len(rows)):
            row = rows[(offset + step) % len(rows)]
            question, _ = self.fill_template(template, row)
            if self._question_key(template.category, question) not in self.accepted_question_keys:
                self.slot_binding_offsets[key] = offset + step + 1
                return row, validation.normalized_cypher
        self.slot_binding_offsets[key] = offset + len(rows)
        self.exhausted_slot_templates.add(self._template_identity(template))
        return {}, validation.normalized_cypher

    @staticmethod
    def _is_valid_binding_value(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            if not value.strip() or len(value) > 160:
                return False
            if value != value.strip():
                return False
            return not any(char in value for char in "\r\n\t")
        if isinstance(value, bool | int | float | date | datetime):
            return True
        return False

    def _generic_slot_lookup_query(self, template: TemplateCandidate) -> str | None:
        if not template.slots:
            return None
        matches: list[str] = []
        predicates: list[str] = []
        returns: list[str] = []
        for idx, (slot, label_prop) in enumerate(template.slots.items()):
            inferred = self._infer_label_property(slot, label_prop)
            if "." not in inferred:
                return None
            label, prop = inferred.split(".", 1)
            variable = f"slot{idx}"
            matches.append(f"MATCH ({variable}:{label})")
            predicates.append(f"{variable}.{prop} IS NOT NULL")
            returns.append(f"{variable}.{prop} AS {slot}")
        where = " WHERE " + " AND ".join(predicates) if predicates else ""
        return (
            " ".join(matches)
            + where
            + " RETURN DISTINCT "
            + ", ".join(returns)
            + f" LIMIT {self.config.generation.generated_query_limit}"
        )

    def generate_cypher(
        self,
        *,
        question: str,
        category: str,
        entity_hints: dict[str, str],
        fallback_template: TemplateCandidate,
        bindings: dict[str, Any] | None = None,
    ) -> tuple[str, list[dict[str, Any]]]:
        retrieved = self.examples.top_k(
            question,
            k=self.config.generation.retrieval_top_k,
            category=category,
        )
        prompt_entity_hints = self._entity_prompt_hints(question, entity_hints)
        prompt = render_cypher_generation_prompt(
            profile_name=self.config.generation.prompt_profile,
            schema=self.schema.to_prompt(),
            question=question,
            examples=self.examples.format_examples(retrieved),
            entity_hints=prompt_entity_hints,
        )
        try:
            cypher = self.llm.chat(
                system=SYSTEM_CYPHER_ENGINEER,
                user=prompt,
                temperature=self.config.models.temperature,
                max_tokens=self.config.models.max_tokens,
            ).text
        except Exception:
            cypher = default_cypher_for_template(
                fallback_template,
                limit=self.config.generation.generated_query_limit,
                bindings=bindings,
                schema=self.schema,
            )
        return cypher, retrieved

    def _entity_prompt_hints(self, question: str, entity_hints: dict[str, str]) -> dict[str, Any]:
        hints: dict[str, Any] = dict(entity_hints)
        grounder = ValueGrounder.from_schema_and_hints(self.schema, entity_hints)
        mentions = grounder.ground(question)
        if mentions:
            hints["_grounded_mentions"] = [mention.to_prompt_dict() for mention in mentions]
            hints["_annotated_question"] = grounder.annotate_text(question, mentions)
        return hints

    def repair_cypher(self, question: str, cypher: str, issue: str) -> str:
        prompt = REPAIR_PROMPT.format(
            schema=self.schema.to_prompt(),
            question=question,
            cypher=cypher,
            issue=issue,
        )
        try:
            return self.llm.chat(
                system=SYSTEM_CYPHER_ENGINEER,
                user=prompt,
                temperature=0.1,
                max_tokens=512,
            ).text
        except Exception:
            return cypher

    def _evaluate_cypher(
        self,
        *,
        question: str,
        cypher: str,
        repair_attempts: int = 0,
    ) -> tuple[str, ValidationResult, ExecutionResult, JudgeResult, int]:
        validation = apply_question_constraints(self._validate_cypher(cypher), question)
        execution = ExecutionResult(success=False, error="not executed")
        executed = False
        while repair_attempts < self.config.generation.repair_attempts:
            if validation.ok:
                execution = self.client.run(validation.normalized_cypher, limit_rows=25)
                executed = True
                if execution.success:
                    break
                issue = execution.error or "execution failed"
            else:
                issue = "; ".join(issue.message for issue in validation.issues) or "validation failed"
            repair_attempts += 1
            cypher = self.repair_cypher(question, validation.normalized_cypher, issue)
            validation = apply_question_constraints(self._validate_cypher(cypher), question)
            executed = False

        if not validation.ok:
            execution = ExecutionResult(success=False, error="validation failed")
        elif not executed:
            execution = self.client.run(validation.normalized_cypher, limit_rows=25)

        judge_result = self.judge.judge(
            question=question,
            cypher=validation.normalized_cypher,
            schema=self.schema,
            validation=validation,
            execution=execution,
        )
        if self.config.generation.require_non_empty and execution.success and not execution.rows:
            judge_result = JudgeResult.failed("execution returned no rows")
        return cypher, validation, execution, judge_result, repair_attempts

    def _accepted(self, validation: ValidationResult, execution: ExecutionResult, judge_result: JudgeResult) -> bool:
        return validation.ok and execution.success and judge_result.passed

    def run_candidate(self, template: TemplateCandidate) -> GenerationRecord:
        bindings, reverse_cypher = self.bind_slots(template)
        if template.slots and not bindings and self._template_identity(template) in self.exhausted_slot_templates:
            validation = self._validate_cypher("RETURN DISTINCT 1 AS SlotBindingsExhausted")
            return GenerationRecord(
                question=template.template,
                cypher=validation.normalized_cypher,
                category=template.category,
                graph_profile=self.config.generation.graph_profile,
                accepted=False,
                validation=validation,
                execution=ExecutionResult(success=False, error="slot bindings exhausted"),
                judge=JudgeResult.failed("slot bindings exhausted"),
                retrieved_examples=[],
                entity_values=[],
                reverse_cypher=reverse_cypher,
                model=getattr(self.llm, "model", self.config.models.generation_model),
            )
        question, entity_hints = self.fill_template(template, bindings)
        cypher, retrieved = self.generate_cypher(
            question=question,
            category=template.category,
            entity_hints=entity_hints,
            fallback_template=template,
            bindings=bindings,
        )
        cypher, validation, execution, judge_result, repair_attempts = self._evaluate_cypher(
            question=question,
            cypher=cypher,
        )
        accepted = self._accepted(validation, execution, judge_result)
        if not accepted and self.config.generation.deterministic_cypher_fallback:
            fallback_cypher = default_cypher_for_template(
                template,
                limit=self.config.generation.generated_query_limit,
                bindings=bindings,
                schema=self.schema,
            )
            if fallback_cypher != "MATCH (n) RETURN DISTINCT n LIMIT 1":
                (
                    candidate_cypher,
                    candidate_validation,
                    candidate_execution,
                    candidate_judge,
                    candidate_repairs,
                ) = self._evaluate_cypher(
                    question=question,
                    cypher=fallback_cypher,
                    repair_attempts=repair_attempts,
                )
                if self._accepted(candidate_validation, candidate_execution, candidate_judge):
                    cypher = candidate_cypher
                    validation = candidate_validation
                    execution = candidate_execution
                    judge_result = candidate_judge
                    repair_attempts = candidate_repairs
                    accepted = True
        empty_result_diagnostic = None
        if (
            self.config.generation.empty_result_diagnostics
            and not accepted
            and validation.ok
            and execution.success
            and not execution.rows
        ):
            diagnostic = diagnose_empty_result(
                cypher=validation.normalized_cypher,
                validation=validation,
                execution=execution,
                client=self.client,
            )
            if diagnostic is not None:
                empty_result_diagnostic = diagnostic.to_dict()
        entity_values = [value.split(" | ", 1)[0] for value in entity_hints.values()]
        return GenerationRecord(
            question=question,
            cypher=validation.normalized_cypher,
            category=template.category,
            graph_profile=self.config.generation.graph_profile,
            accepted=accepted,
            validation=validation,
            execution=execution,
            judge=judge_result,
            retrieved_examples=retrieved,
            entity_values=entity_values,
            reverse_cypher=reverse_cypher,
            empty_result_diagnostic=empty_result_diagnostic,
            repair_attempts=repair_attempts,
            model=getattr(self.llm, "model", self.config.models.generation_model),
        )

    @staticmethod
    def _question_key(category: str, question: str) -> tuple[str, str]:
        return question_key(category, question)

    def _can_produce_new_question(self, category: str, template: TemplateCandidate) -> bool:
        if template.slots:
            return self._template_identity(template) not in self.exhausted_slot_templates
        return self._question_key(category, template.template) not in self.accepted_question_keys

    @staticmethod
    def _template_identity(template: TemplateCandidate) -> str:
        return json.dumps(
            {
                "category": template.category,
                "template": template.template,
                "metadata": template.metadata,
            },
            sort_keys=True,
            default=str,
        )

    def run(self, output_path: str | Path) -> PipelineResult:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("", encoding="utf-8")
        records: list[GenerationRecord] = []
        for category in self.config.generation.categories:
            target = self.config.generation.target_per_category
            templates = self.generate_templates(category)
            if not templates:
                continue
            attempts = 0
            accepted = 0
            max_attempts = max(target * 4, len(templates))
            while accepted < target and attempts < max_attempts:
                attempts += 1
                if attempts <= len(templates):
                    template = templates[attempts - 1]
                else:
                    reusable = [template for template in templates if self._can_produce_new_question(category, template)]
                    if not reusable:
                        break
                    template = self.rng.choice(reusable)
                if self.structural_diversity.seen(category, template.template) and attempts <= len(templates):
                    continue
                record = self.run_candidate(template)
                if record.accepted:
                    question_key = self._question_key(record.category, record.question)
                    if question_key in self.accepted_question_keys:
                        record.accepted = False
                        record.judge = JudgeResult.failed("duplicate accepted question")
                    elif self.entity_diversity.would_exceed(
                        category,
                        record.entity_values,
                        self.config.generation.target_per_category,
                    ):
                        record.accepted = False
                        record.judge = JudgeResult.failed("entity diversity cap exceeded")
                    else:
                        self.accepted_question_keys.add(question_key)
                        self.entity_diversity.record(category, record.entity_values)
                        self.examples.add(record.question, record.cypher, record.category)
                records.append(record)
                append_jsonl(out, record.to_dict())
                if record.accepted:
                    accepted += 1
        return PipelineResult(records=records, output_path=out)
