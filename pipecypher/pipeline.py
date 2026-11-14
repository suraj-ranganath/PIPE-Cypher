from __future__ import annotations

import random
import re
import zlib
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
from .judge import DeterministicJudge, LLMJudge, deterministic_judge_notes
from .limit_ties import TIE, UNRESOLVED, UNSUPPORTED, check_limit_tie
from .llm import NullLLM, OpenAICompatibleLLM
from .models import ExecutionResult, GenerationRecord, JudgeResult, SchemaSummary, TemplateCandidate, ValidationResult
from .cypher_parser import analyze_cypher
from .diversity_metrics import canonical_query_signature
from .conventions import WRITER_RULES, convention_sheet
from .difficulty import TIERS, difficulty_score, difficulty_tier, load_difficulty_model, tier_quota_counts
from .evaluation import projected_answer_scores
from .literal_consistency import literal_consistency_problems
from .template_binding import check_template_cypher, derive_binding_queries, is_degenerate, render_with_literals
from .refresh_audit import mask_string_literals
from .text_metrics import sentence_bleu, tokenize
from .prompts import (
    _TEMPLATE_RULES_V3,
    QUESTION_PARAPHRASE_PROMPT,
    QUESTION_REALIZATION_PROMPT_V3,
    TEMPLATE_GENERATION_PROMPT_V3,
    TEMPLATE_INDUCTION_PROMPT_V3,
    TIER_REQUESTS_V3,
    REPAIR_PROMPT,
    REVERSE_CYPHER_PROMPT,
    SYSTEM_CYPHER_ENGINEER,
    SYSTEM_JSON_ENGINEER,
    TEMPLATE_GENERATION_PROMPT,
    TEMPLATE_INDUCTION_PROMPT,
    render_cypher_generation_prompt,
)
from .question_constraints import apply_question_constraints
from .retrieval import ExampleStore
from .schema_templates import SCHEMA_TEMPLATE_KIND, schema_derived_templates
from .value_grounding import ValueGrounder
from .validator import validate_cypher


def _phrase_id_slot(question: str, slot: str, label_prop: str, value: str) -> str:
    """Render an id-valued slot as "<label> with id <value>" so questions never
    read like "How many people does 6 know?". Templates that already say
    "<label> with id {slot}" or "id {slot}" are left unchanged."""

    label, _, prop = label_prop.partition(".")
    if not label or not prop or not (prop.lower() == "id" or prop.lower().endswith("id")):
        return question
    token = "{" + slot + "}"
    # "id {slot}" or "companyId {slot}" already names the id property.
    if token not in question or re.search(r"\b\w*id\s+['\"]?" + re.escape(token), question, re.I):
        return question
    # A quoted slot ('{tag}') already reads as a value; wrapping it would give
    # "id 'tag with id 1152'" (171 malformed v2 questions).
    if re.search(r"['\"]" + re.escape(token) + r"['\"]", question):
        return question
    labelled = re.compile(r"\b(" + re.escape(label) + r")\s+" + re.escape(token), re.I)
    if labelled.search(question):
        return labelled.sub(lambda m: f"{m.group(1)} with id {value}", question)
    return question.replace(token, f"{label.lower()} with id {value}")


_ID_TIEBREAK_RE = re.compile(
    r"(?is)(\bORDER\s+BY\s+.+?)\s*,\s*([A-Za-z_][A-Za-z0-9_]*\.)?([A-Za-z0-9_]*?(?:id|Id|ID))\b(\s+(?:ASC|DESC|ASCENDING|DESCENDING))?(\s+LIMIT\b)"
)


def _strip_identifier_tiebreak(cypher: str, question: str) -> str:
    """Drop a trailing identifier ORDER BY key the question never asks for.

    ``ORDER BY n DESC, c.id ASC LIMIT 1`` makes a tie at the cutoff look
    deterministic; the tie check must see the order the question states.
    """

    if re.search(r"(?i)\b(by|then)\s+(its\s+|their\s+)?(id|identifier)\b", question):
        return cypher
    masked = mask_string_literals(cypher)
    match = _ID_TIEBREAK_RE.search(masked)
    if not match:
        return cypher
    return cypher[: match.start()] + cypher[match.start(1): match.end(1)] + cypher[match.start(5): match.end(5)] + cypher[match.end():]


def question_key(category: str, question: str) -> tuple[str, str]:
    return category, " ".join(question.lower().split())


@dataclass
class PipelineResult:
    records: list[GenerationRecord]
    output_path: Path
    attempt_summary: dict[str, Any]


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
        # Shards of one graph/category start at different binding rows so they
        # ground different entities instead of regenerating the same questions.
        self.binding_offset_base = 0
        self.accepted_question_keys: set[tuple[str, str]] = set(seen_question_keys or set())
        self.exhausted_slot_templates: set[str] = set()
        self.rng = random.Random(config.generation.random_seed)
        symmetric = list(config.generation.symmetric_relationships or [])
        if symmetric:
            merged = sorted({*getattr(schema, "symmetric_relationships", []), *symmetric})
            schema.symmetric_relationships = merged
        self.signature_counts: Counter[tuple[str, str]] = Counter()
        self.saturated_templates: set[str] = set()
        # --- v3 state ---
        self.conventions = convention_sheet(schema) if config.generation.convention_sheet else ""
        self.difficulty_model = (
            load_difficulty_model(config.generation.difficulty_model_path)
            if config.generation.difficulty_model_path
            else None
        )
        self.tier_counts: Counter[tuple[str, str]] = Counter()
        self.accepted_question_tokens: dict[str, list[list[str]]] = {}
        self.last_binding_info: dict[str, Any] = {}
        self.failed_binding_keys: set[str] = set()
        self.template_rejections: Counter[str] = Counter()
        self.template_log_path: Path | None = None
        self._active_category = ""
        self._active_tier_quota: dict[str, int] = {}
        self.template_gate_failures: Counter[str] = Counter()

    def _validate_cypher(self, cypher: str) -> ValidationResult:
        return validate_cypher(
            cypher,
            self.schema,
            normalize=self.config.generation.normalize_cypher,
        )

    def _log_template(self, record: dict[str, Any]) -> None:
        if self.template_log_path is not None:
            append_jsonl(self.template_log_path, record)

    def _template_from_item(
        self, item: dict[str, Any], category: str, metadata: dict[str, Any]
    ) -> TemplateCandidate | None:
        """Build a template; under ``template_cypher`` it must carry valid parameterized Cypher."""

        template = TemplateCandidate(
            template=str(item["template"]),
            category=category,
            slots=self._parse_template_slots(item.get("slots", [])),
            rationale=str(item.get("rationale", "")),
            metadata=dict(metadata),
        )
        if not self.config.generation.template_cypher:
            return template
        cypher = str(item.get("cypher") or "").strip()
        problem = check_template_cypher(cypher, list(template.slots))
        if problem is None:
            undeclared = set(re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", template.template)) - set(template.slots)
            if undeclared:
                problem = "template text has undeclared placeholder(s): " + ", ".join(sorted(undeclared))
        if problem is None:
            validation = self._validate_cypher(cypher)
            if not (validation.read_only and validation.syntax_valid and validation.schema_valid and not validation.errors):
                problem = "template Cypher fails governance: " + "; ".join(i.message for i in validation.errors)[:300]
            else:
                cypher = validation.normalized_cypher
        if problem is None and not template.slots and self.config.generation.outcome_aware_binding:
            # A slot-free template is one fixed question: its own query must answer it.
            if is_degenerate(self.client.run(cypher, limit_rows=25)):
                problem = "template query returns no rows (slot-free template)"
        if problem:
            self.template_rejections[problem.split(":")[0]] += 1
            self._log_template({"category": category, "status": "rejected", "reason": problem, **item, **metadata})
            return None
        template.metadata["parameterized_cypher"] = cypher
        if self.difficulty_model is not None:
            template.metadata["template_tier"] = difficulty_tier(cypher, self.difficulty_model)
        self._log_template({"category": category, "status": "accepted", **item, **template.metadata})
        return template

    @staticmethod
    def _v3_schema_templates(templates: list[TemplateCandidate]) -> list[TemplateCandidate]:
        """Convention C11/C13: drop rankings of one given entity against itself
        (``topk_*_scoped``) and state k (their Cypher uses LIMIT 10) in the rest."""

        kept: list[TemplateCandidate] = []
        for template in templates:
            kind = str(template.metadata.get(SCHEMA_TEMPLATE_KIND) or "")
            if kind.startswith("topk_") and kind.endswith("_scoped"):
                continue
            if kind in {"topk_outgoing", "topk_incoming"} and template.template.startswith("Which "):
                template = TemplateCandidate(
                    template="Which 10 " + template.template[len("Which "):],
                    category=template.category,
                    slots=dict(template.slots),
                    rationale=template.rationale,
                    metadata=dict(template.metadata),
                )
            kept.append(template)
        return kept

    def _tier_request(self, tier: str | None) -> str:
        return TIER_REQUESTS_V3.get(tier or "", "")

    def _template_json(self, prompt: str, temperature: float) -> Any:
        """Template proposal / induction call. A reply lists several templates with
        Cypher, and mandatory reasoning tokens count against max_tokens (GLM used
        1.2-1.9k reasoning tokens on hard categories), so these calls get 3x the
        per-call budget, and a truncated (unparseable) reply is retried once at 4x
        instead of silently leaving the category without templates. Unused budget
        is not billed."""
        budget = self.config.models.max_tokens
        try:
            return self.llm.chat_json(system=SYSTEM_JSON_ENGINEER, user=prompt, temperature=temperature, max_tokens=budget * 3)
        except ValueError:
            return self.llm.chat_json(system=SYSTEM_JSON_ENGINEER, user=prompt, temperature=temperature, max_tokens=budget * 4)

    def generate_templates(self, category: str) -> list[TemplateCandidate]:
        n = self.config.generation.template_candidates
        seeded = [template for template in default_templates(self.config.generation.graph_profile) if template.category == category]
        derived = schema_derived_templates(self.schema, category, max_templates=max(n * 4, 24))
        if self.config.generation.convention_sheet:
            derived = self._v3_schema_templates(derived)
        if self.difficulty_model is not None:
            for template in [*seeded, *derived]:
                if "template_tier" not in template.metadata:
                    default = default_cypher_for_template(
                        template, limit=self.config.generation.generated_query_limit, schema=self.schema
                    )
                    if default and default != "MATCH (n) RETURN DISTINCT n LIMIT 1":
                        template.metadata["template_tier"] = difficulty_tier(default, self.difficulty_model)
        source = self.config.generation.template_source.lower()
        if source == "default":
            return self._dedupe_templates([*seeded, *derived])[: max(n, len(seeded), len(derived))]

        if self.config.generation.template_cypher:
            prompt = TEMPLATE_GENERATION_PROMPT_V3.format(
                schema=self.schema.to_prompt(),
                conventions=self.conventions or "(none)",
                rules=_TEMPLATE_RULES_V3,
                n=n,
                category=category,
                tier_request="",
            )
        else:
            prompt = TEMPLATE_GENERATION_PROMPT.format(
                schema=self.schema.to_prompt(),
                n=n,
                category=category,
            )
        try:
            data = self._template_json(prompt, self.config.models.temperature)
            generated = [
                template
                for item in data
                if isinstance(item, dict) and item.get("template")
                for template in [self._template_from_item(item, category, {"template_origin": "llm"})]
                if template is not None
            ]
            for template in generated:
                template.metadata.setdefault("template_origin", "llm")
            if source == "mixed":
                if self.config.generation.mixed_keep_llm_templates:
                    # v2: never let seed/schema-derived templates crowd out LLM
                    # proposals; they are the main source of new structures.
                    base = self._dedupe_templates([*seeded, *derived])[
                        : max(n, len(seeded), len(derived))
                    ]
                    return self._dedupe_templates([*base, *generated])
                return self._dedupe_templates([*seeded, *derived, *generated])[
                    : max(n, len(seeded), len(derived))
                ]
            return generated
        except Exception:
            if not self.config.generation.allow_seed_template_fallback:
                return []
            return self._dedupe_templates([*seeded, *derived])[: max(n, len(seeded), len(derived))]

    def induce_templates(
        self,
        category: str,
        existing: list[TemplateCandidate],
        *,
        round_index: int,
        tier: str | None = None,
    ) -> list[TemplateCandidate]:
        """Ask the LLM for templates whose query structure is not yet covered."""

        batch = self.config.generation.template_induction_batch
        covered = "\n".join(f"- {template.template}" for template in existing[:60]) or "- (none)"
        if self.config.generation.template_cypher:
            prompt = TEMPLATE_INDUCTION_PROMPT_V3.format(
                schema=self.schema.to_prompt(),
                conventions=self.conventions or "(none)",
                rules=_TEMPLATE_RULES_V3,
                category=category,
                covered=covered,
                n=batch,
                hard_n=max(1, batch // 2),
                tier_request=self._tier_request(tier),
            )
        else:
            prompt = TEMPLATE_INDUCTION_PROMPT.format(
                schema=self.schema.to_prompt(),
                category=category,
                covered=covered,
                n=batch,
                hard_n=max(1, batch // 2),
            )
        try:
            data = self._template_json(prompt, max(self.config.models.temperature, 0.5))
        except Exception:
            return []
        known = {template.template.lower() for template in existing}
        induced: list[TemplateCandidate] = []
        for item in data if isinstance(data, list) else []:
            if not isinstance(item, dict) or not item.get("template"):
                continue
            text = str(item["template"])
            if text.lower() in known:
                continue
            known.add(text.lower())
            metadata: dict[str, Any] = {"template_origin": "llm_induced", "induction_round": round_index}
            if tier:
                metadata["requested_tier"] = tier
            template = self._template_from_item(item, category, metadata)
            if template is not None:
                induced.append(template)
        return induced

    def paraphrase_question(self, question: str, values: list[str]) -> tuple[str, str]:
        """Return (question, status). Values must survive verbatim or we keep the template text."""

        quoted = [value for value in values if value]
        prompt = QUESTION_PARAPHRASE_PROMPT.format(
            values=", ".join(repr(value) for value in quoted) or "(none)",
            question=question,
        )
        try:
            text = self.llm.chat(
                system="You rewrite questions without changing their meaning.",
                user=prompt,
                temperature=max(self.config.models.temperature, 0.7),
                # Headroom for hosted models whose (mandatory) reasoning tokens
                # count against max_tokens; only the paraphrase is kept.
                max_tokens=512,
            ).text.strip()
        except Exception:
            return question, "paraphrase_failed"
        text = " ".join(text.splitlines()).strip().strip('"').strip()
        if not text:
            return question, "paraphrase_empty"
        if any(value not in text for value in quoted):
            return question, "paraphrase_dropped_value"
        return text, "paraphrased"

    def realize_question(self, question: str, values: list[str], category: str) -> tuple[str, str]:
        """v3 style-diverse realization: rewrite in a sampled style, keep the candidate
        least similar (max sentence BLEU) to questions already accepted in the category."""

        styles = self.config.generation.realization_styles
        # Per-question style: a shared RNG seed would give every parallel cell the
        # same style sequence (the first pilot used "business_manager" 90% of the time).
        style = styles[zlib.crc32(f"{category}|{question}".encode("utf-8")) % len(styles)]
        quoted = [value for value in values if value]
        prompt = QUESTION_REALIZATION_PROMPT_V3.format(
            conventions=(self.conventions + "\n\n" + WRITER_RULES).strip(),
            style=style,
            values=", ".join(repr(value) for value in quoted) or "(none)",
            question=question,
        )
        try:
            data = self.llm.chat_json(
                system=SYSTEM_JSON_ENGINEER,
                user=prompt,
                temperature=max(self.config.models.temperature, 0.7),
                max_tokens=max(768, self.config.models.max_tokens // 2),
                response_format={"type": "json_object"},
            )
        except Exception:
            return question, f"realization_failed:{style}"
        raw = data.get("paraphrases") if isinstance(data, dict) else data
        candidates = [str(text) for text in (raw if isinstance(raw, list) else []) if isinstance(text, str)]
        digits = set(re.findall(r"\d+(?:\.\d+)?", question))
        valid: list[str] = []
        for text in candidates[: max(1, self.config.generation.paraphrase_candidates)]:
            text = " ".join(text.splitlines()).strip().strip('"').strip()
            if not text or "{" in text or "}" in text:
                continue
            if any(value not in text for value in quoted):
                continue
            if not digits <= set(re.findall(r"\d+(?:\.\d+)?", text)):
                continue
            valid.append(text)
        if not valid:
            return question, f"realization_rejected:{style}"
        accepted = self.accepted_question_tokens.get(category, [])[-300:]

        def max_similarity(text: str) -> float:
            tokens = tokenize(text)
            return max((sentence_bleu(tokens, other) for other in accepted), default=0.0)

        best = min(valid, key=max_similarity)
        return best, f"realized:{style}"

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

    def _schema_has_node_property(self, label_prop: str) -> bool:
        if "." not in label_prop:
            return False
        label, prop = label_prop.split(".", 1)
        return prop in self.schema.properties_for_label(label)

    def _identifying_property(self, label: str) -> str | None:
        props = self.schema.properties_for_label(label)
        lowered = {prop.lower(): prop for prop in props}
        for candidate in ("name", "title", "id", f"{label.lower()}name", f"{label.lower()}id"):
            if candidate in lowered:
                return f"{label}.{lowered[candidate]}"
        return None

    def _infer_label_property(self, slot: str, label_prop: str = "") -> str:
        """Map a template slot to a schema-visible Label.property.

        Explicit Label.property values are kept when the schema has them;
        otherwise fall back to name heuristics, and finally to the label's
        identifying property (name/title/id) so a slot such as ``person`` on SNB
        binds ``Person.id`` instead of a FinBench-only ``Person.personName``.
        """

        if "." in label_prop and (self._schema_has_node_property(label_prop) or not self.schema.node_properties):
            return label_prop
        inferred = self._legacy_infer_label_property(slot, label_prop)
        if self._schema_has_node_property(inferred) or not self.schema.node_properties:
            return inferred
        labels = {label.lower(): label for label in self.schema.labels}
        hint = (label_prop.split(".", 1)[0] if "." in label_prop else slot).lower().rstrip("0123456789_")
        label = labels.get(hint)
        if label:
            identified = self._identifying_property(label)
            if identified:
                return identified
        return inferred

    def _legacy_infer_label_property(self, slot: str, label_prop: str = "") -> str:
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
            prop = label_prop.partition(".")[2].lower()
            if self.conventions and (prop == "id" or prop.endswith("id")):
                # Convention C1: identifiers are written without quotation marks.
                question = re.sub(r"(['\"])\{" + re.escape(slot) + r"\}\1", "{" + slot + "}", question)
            if self.config.generation.require_slot_bindings and bindings.get(slot) is not None:
                question = _phrase_id_slot(question, slot, label_prop, value)
            question = question.replace("{" + slot + "}", value)
            hints[slot] = f"{value} | {label_prop}"
        return question, hints

    def bind_slots(self, template: TemplateCandidate) -> tuple[dict[str, Any], str | None]:
        if not template.slots:
            return {}, None
        if self.config.generation.outcome_aware_binding:
            if template.metadata.get("parameterized_cypher"):
                return self._bind_from_template_cypher(template)
            if str(template.metadata.get("template_origin", "")).startswith("llm"):
                self.last_binding_info = {"binding_source": None, "binding_problem": "LLM template without parameterized Cypher"}
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
            if all(self._is_valid_slot_binding(slot, row.get(slot)) for slot in template.slots)
        ]
        if not rows:
            return {}, validation.normalized_cypher
        key = f"{template.category}:{template.template}:{validation.normalized_cypher}"
        if key not in self.slot_binding_offsets and self.binding_offset_base:
            self.slot_binding_offsets[key] = self.binding_offset_base % max(1, len(rows))
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

    def _bind_from_template_cypher(self, template: TemplateCandidate) -> tuple[dict[str, Any], str | None]:
        """Outcome-aware binding: candidates come from the template's own Cypher
        (pattern-derived), and a binding is used only after the parameterized
        query returns a non-degenerate answer for it. No unverified fallback."""

        gen = self.config.generation
        cypher = template.metadata["parameterized_cypher"]
        slots = list(template.slots)
        queries, problem = derive_binding_queries(cypher, slots, limit=gen.generated_query_limit)
        info: dict[str, Any] = {"binding_source": None, "derivation_problem": problem, "verify_attempts": 0}
        used_query: str | None = None
        derived: list[tuple[str, dict[str, Any]]] = []
        for query in queries:
            validation = self._validate_cypher(query.cypher)
            if not (validation.read_only and validation.syntax_valid and not validation.errors):
                continue
            execution = self.client.run(validation.normalized_cypher, limit_rows=gen.generated_query_limit)
            if not execution.success or not execution.rows:
                continue
            rows = [row for row in execution.rows if all(self._is_valid_slot_binding(slot, row.get(slot)) for slot in slots)]
            if rows:
                derived = [(query.strategy, {slot: row[slot] for slot in slots}) for row in rows]
                used_query = validation.normalized_cypher
                break
        lookup: list[tuple[str, dict[str, Any]]] = []
        if template.category == "boolean_existence" or not derived:
            # Label-level candidates (also verified below) give boolean templates
            # their "no" answers; derived candidates mostly satisfy the pattern.
            generic = self._generic_slot_lookup_query(template)
            if generic:
                execution = self.client.run(generic, limit_rows=gen.generated_query_limit)
                if execution.success:
                    lookup = [
                        ("label_lookup_verified", {slot: row[slot] for slot in slots})
                        for row in execution.rows
                        if all(self._is_valid_slot_binding(slot, row.get(slot)) for slot in slots)
                    ]
                    used_query = used_query or generic
        if template.category == "boolean_existence" and derived and lookup:
            merged: list[tuple[str, dict[str, Any]]] = []
            for pair in zip(derived, lookup):
                merged.extend(pair)
            merged.extend(derived[len(lookup):] or lookup[len(derived):])
            candidates = merged
        else:
            candidates = derived or lookup
        seen: set[str] = set()
        unique: list[tuple[str, dict[str, Any]]] = []
        for strategy, row in candidates:
            key = json.dumps(row, sort_keys=True, default=str)
            if key not in seen:
                seen.add(key)
                unique.append((strategy, row))
        template_id = self._template_identity(template)
        offset_key = f"v3:{template_id}"
        if offset_key not in self.slot_binding_offsets and self.binding_offset_base:
            self.slot_binding_offsets[offset_key] = self.binding_offset_base % max(1, len(unique))
        offset = self.slot_binding_offsets[offset_key]
        attempts = 0
        fresh = 0
        for step in range(len(unique)):
            index = (offset + step) % len(unique)
            strategy, row = unique[index]
            failed_key = template_id + json.dumps(row, sort_keys=True, default=str)
            if failed_key in self.failed_binding_keys:
                continue
            question, _ = self.fill_template(template, row)
            if self._question_key(template.category, question) in self.accepted_question_keys:
                continue
            fresh += 1
            if attempts >= gen.binding_verify_attempts:
                break
            attempts += 1
            execution = self.client.run(cypher, params=row, limit_rows=25)
            if not is_degenerate(execution):
                self.slot_binding_offsets[offset_key] = index + 1
                info.update(binding_source=strategy, verify_attempts=attempts, verified=True)
                self.last_binding_info = info
                return row, used_query
            self.failed_binding_keys.add(failed_key)
        if fresh == 0 or not unique:
            self.exhausted_slot_templates.add(template_id)
        info.update(verify_attempts=attempts, verified=False, candidates=len(unique))
        self.last_binding_info = info
        return {}, used_query

    RANK_SLOT_NAMES = frozenset({"k", "n", "top", "topk", "top_k", "topn", "top_n", "limit"})

    def _is_valid_slot_binding(self, slot: str, value: Any) -> bool:
        if not self._is_valid_binding_value(value):
            return False
        bound = self.config.generation.max_rank_slot_value
        if bound and slot.lower() in self.RANK_SLOT_NAMES:
            if isinstance(value, bool):
                return False
            try:
                number = int(str(value).strip())
            except ValueError:
                return False
            return 1 <= number <= bound
        return True

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
            conventions=self.conventions,
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
        bound_values: list[Any] | None = None,
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

        if self.config.generation.literal_consistency_gate:
            # v3: deterministic gates run before the (paid) LLM judge.
            failure = self._deterministic_gate_failure(question, validation, execution, bound_values or [])
            if failure:
                return cypher, validation, execution, JudgeResult.failed(failure), repair_attempts
            judge_result = self.judge.judge(
                question=question,
                cypher=validation.normalized_cypher,
                schema=self.schema,
                validation=validation,
                execution=execution,
            )
            return cypher, validation, execution, judge_result, repair_attempts

        judge_result = self.judge.judge(
            question=question,
            cypher=validation.normalized_cypher,
            schema=self.schema,
            validation=validation,
            execution=execution,
        )
        if self.config.generation.require_non_empty and execution.success and not execution.rows:
            judge_result = JudgeResult.failed("execution returned no rows")
        elif (
            self.config.generation.reject_truncated_unordered_limit
            and validation.ok
            and execution.success
            and execution.rows
            and judge_result.passed
            and self._truncated_by_unordered_limit(validation.normalized_cypher)
        ):
            # A set-valued reference cut by LIMIT without ORDER BY has an
            # arbitrary answer; downstream exact-set scoring would be noise.
            judge_result = JudgeResult.failed("reference truncated by unordered LIMIT")
        elif (
            self.config.generation.reject_limit_boundary_ties
            and validation.ok
            and execution.success
            and execution.rows
            and judge_result.passed
        ):
            tie = check_limit_tie(
                validation.normalized_cypher,
                lambda query: self.client.run(query, limit_rows=None),
            )
            if tie.status == TIE:
                judge_result = JudgeResult.failed(f"reference has a tie at the ORDER BY/LIMIT boundary ({tie.detail})")
            elif tie.status in {UNRESOLVED, UNSUPPORTED}:
                judge_result = JudgeResult.failed(f"cannot verify ORDER BY/LIMIT determinism ({tie.detail})")
        return cypher, validation, execution, judge_result, repair_attempts

    def _deterministic_gate_failure(
        self,
        question: str,
        validation: ValidationResult,
        execution: ExecutionResult,
        bound_values: list[Any],
    ) -> str | None:
        """v3 gate cascade (all deterministic): returns the first failure reason."""

        gen = self.config.generation
        if not validation.ok:
            return "validation failed"
        if not execution.success:
            return execution.error or "execution failed"
        if gen.require_non_empty and not execution.rows:
            return "execution returned no rows"
        cypher = validation.normalized_cypher
        if gen.reject_truncated_unordered_limit and self._truncated_by_unordered_limit(cypher):
            return "reference truncated by unordered LIMIT"
        if self._truncated_by_default_limit(cypher):
            return "reference truncated by the default LIMIT"
        category_problem = self._category_contract_problem(cypher, execution)
        if category_problem:
            return category_problem
        if gen.reject_limit_boundary_ties:
            tie_cypher = _strip_identifier_tiebreak(cypher, question)
            tie = check_limit_tie(tie_cypher, lambda query: self.client.run(query, limit_rows=None))
            if tie.status == TIE and tie_cypher != cypher:
                return f"reference hides a tie behind an unstated identifier tie-break ({tie.detail})"
            if tie.status == TIE:
                return f"reference has a tie at the ORDER BY/LIMIT boundary ({tie.detail})"
            if tie.status in {UNRESOLVED, UNSUPPORTED}:
                return f"cannot verify ORDER BY/LIMIT determinism ({tie.detail})"
        problems = literal_consistency_problems(
            question, cypher, bound_values, ignore_limits=[gen.generated_query_limit]
        )
        if problems:
            return "literal mismatch: " + "; ".join(problems[:3])
        # Patterns the schema never lists (also inside NOT EXISTS) and variables
        # dropped at a WITH and silently re-bound: both pass the validator.
        notes = deterministic_judge_notes(cypher, self.schema)
        if notes:
            return "structural defect: " + "; ".join(notes[:2])
        if self.difficulty_model is not None and self._active_tier_quota:
            tier = difficulty_tier(cypher, self.difficulty_model)
            category = self._active_category
            if self.tier_counts[(category, tier)] >= self._active_tier_quota.get(tier, 0):
                return f"tier quota exceeded ({tier})"
        return None

    def _category_contract_problem(self, cypher: str, execution: ExecutionResult) -> str | None:
        """Light structural contract per category, so labels match what the reference does."""

        category = self._active_category
        masked = mask_string_literals(cypher)
        if category == "boolean_existence":
            rows = execution.rows or []
            if len(rows) != 1 or len(rows[0]) != 1 or not isinstance(next(iter(rows[0].values())), bool):
                return "category contract: a yes/no question must return exactly one boolean value"
        elif category == "ranking_topk":
            if not re.search(r"(?i)\bORDER\s+BY\b", masked) or not re.search(r"(?i)\bLIMIT\b", masked):
                return "category contract: a ranking question needs ORDER BY and LIMIT"
        elif category == "negation_difference":
            if not re.search(r"(?i)\bNOT\b", masked):
                return "category contract: a negation question needs a NOT condition"
        elif category in {"simple_aggregation", "complex_aggregation"}:
            if not re.search(r"(?i)\b(count|sum|avg|min|max|collect|stdev|percentile\w*)\s*\(", masked):
                return "category contract: an aggregation question needs an aggregate"
        return None

    def _truncated_by_default_limit(self, cypher: str) -> bool:
        """An ordered query cut at the pipeline's default LIMIT, which the question never states."""

        analysis = analyze_cypher(cypher)
        default = self.config.generation.generated_query_limit
        if not analysis.order_by_items or not analysis.limit_value:
            return False
        try:
            limit = int(str(analysis.limit_value).strip())
        except ValueError:
            return False
        if limit != default:
            return False
        full = self.client.run(cypher, limit_rows=None)
        return bool(full.success and len(full.rows) >= limit)

    def _truncated_by_unordered_limit(self, cypher: str) -> bool:
        analysis = analyze_cypher(cypher)
        if analysis.order_by_items or not analysis.limit_value:
            return False
        try:
            limit = int(str(analysis.limit_value).strip())
        except ValueError:
            return True  # parameterized/expression LIMIT: cannot prove determinism
        if limit <= 1:
            return False
        full = self.client.run(cypher, limit_rows=None)
        return bool(full.success and len(full.rows) >= limit)

    def _accepted(self, validation: ValidationResult, execution: ExecutionResult, judge_result: JudgeResult) -> bool:
        return validation.ok and execution.success and judge_result.passed

    def run_candidate(self, template: TemplateCandidate) -> GenerationRecord:
        self.last_binding_info = {}
        bindings, reverse_cypher = self.bind_slots(template)
        if (
            template.slots
            and not bindings
            and (
                self._template_identity(template) in self.exhausted_slot_templates
                or template.metadata.get(SCHEMA_TEMPLATE_KIND)
                or self.config.generation.require_slot_bindings
            )
        ):
            validation = self._validate_cypher("RETURN DISTINCT 1 AS SlotBindingsExhausted")
            reason = (
                "slot bindings exhausted"
                if self._template_identity(template) in self.exhausted_slot_templates
                else "slot bindings unavailable"
            )
            if self.config.generation.outcome_aware_binding:
                # v3: a template with no valid binding on this graph is retired
                # instead of being retried until the attempt budget runs out.
                self.exhausted_slot_templates.add(self._template_identity(template))
            return GenerationRecord(
                question=template.template,
                cypher=validation.normalized_cypher,
                category=template.category,
                graph_profile=self.config.generation.graph_profile,
                accepted=False,
                validation=validation,
                execution=ExecutionResult(success=False, error=reason),
                judge=JudgeResult.failed(reason),
                retrieved_examples=[],
                entity_values=[],
                reverse_cypher=reverse_cypher,
                model=getattr(self.llm, "model", self.config.models.generation_model),
                template=template.template,
                template_metadata=template.metadata,
            )
        question, entity_hints = self.fill_template(template, bindings)
        generation_metadata: dict[str, Any] = {
            "template_origin": template.metadata.get(
                "template_origin",
                "schema_derived" if template.metadata.get(SCHEMA_TEMPLATE_KIND) else "seed",
            ),
            "canonical_question": question,
            "question_realization": "template",
        }
        if "induction_round" in template.metadata:
            generation_metadata["induction_round"] = template.metadata["induction_round"]
        if self.last_binding_info:
            generation_metadata["binding"] = dict(self.last_binding_info)
        if bindings and self.config.generation.template_cypher:
            # Kept so generator-swap replays can reuse identical plans and bindings.
            generation_metadata["bindings"] = {slot: value for slot, value in bindings.items() if not isinstance(value, (dict, list))}
        for key in ("template_tier", "requested_tier"):
            if key in template.metadata:
                generation_metadata[key] = template.metadata[key]
        bound_raw = [value for value in (bindings or {}).values() if value is not None]
        if self.config.generation.question_paraphrase:
            bound_values = [str(value) for value in bound_raw]
            if self.config.generation.realization_styles:
                question, status = self.realize_question(question, bound_values, template.category)
            else:
                question, status = self.paraphrase_question(question, bound_values)
            generation_metadata["question_realization"] = status
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
            bound_values=bound_raw,
        )
        accepted = self._accepted(validation, execution, judge_result)
        generation_metadata["reference_source"] = "generator"
        template_cypher = template.metadata.get("parameterized_cypher")
        if (
            not accepted
            and self.config.generation.template_cypher_fallback
            and template_cypher
            and (bindings or not template.slots)
        ):
            rendered = render_with_literals(template_cypher, bindings or {})
            if rendered:
                (
                    candidate_cypher,
                    candidate_validation,
                    candidate_execution,
                    candidate_judge,
                    candidate_repairs,
                ) = self._evaluate_cypher(
                    question=question,
                    cypher=rendered,
                    repair_attempts=self.config.generation.repair_attempts,
                    bound_values=bound_raw,
                )
                generation_metadata["generator_rejection"] = judge_result.failure_reason
                if self._accepted(candidate_validation, candidate_execution, candidate_judge):
                    cypher, validation, execution, judge_result = (
                        candidate_cypher,
                        candidate_validation,
                        candidate_execution,
                        candidate_judge,
                    )
                    accepted = True
                    generation_metadata["reference_source"] = "template_cypher"
        if accepted and template_cypher and generation_metadata["reference_source"] == "generator":
            generation_metadata["template_cypher_agreement"] = self._template_agreement(
                template_cypher, bindings or {}, validation.normalized_cypher
            )
        if self.difficulty_model is not None and validation.ok:
            generation_metadata["difficulty_score"] = difficulty_score(validation.normalized_cypher, self.difficulty_model)
            generation_metadata["difficulty_tier"] = difficulty_tier(validation.normalized_cypher, self.difficulty_model)
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
                    bound_values=bound_raw,
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
            template=template.template,
            template_metadata=template.metadata,
            generation_metadata={
                **generation_metadata,
                "query_signature": canonical_query_signature(validation.normalized_cypher),
            },
        )

    def _template_agreement(self, template_cypher: str, bindings: dict[str, Any], reference: str) -> bool | None:
        """Does the generated reference return the same answer as the template's own query?"""

        template_run = self.client.run(template_cypher, params=bindings, limit_rows=300)
        reference_run = self.client.run(reference, limit_rows=300)
        if not (template_run.success and reference_run.success):
            return None
        forward, _ = projected_answer_scores(reference_run.rows, template_run.rows)
        backward, _ = projected_answer_scores(template_run.rows, reference_run.rows)
        return bool(forward.exact or backward.exact)

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
        if self.config.generation.template_cypher:
            self.template_log_path = out.with_suffix(".templates.jsonl")
            self.template_log_path.write_text("", encoding="utf-8")
        records: list[GenerationRecord] = []
        attempt_summary: dict[str, Any] = {
            "candidate_attempts": 0,
            "emitted_records": 0,
            "pre_record_skips": 0,
            "template_generation_empty_categories": 0,
            "no_reusable_template_breaks": 0,
            "template_candidates": 0,
            "by_category": {},
        }
        for category in self.config.generation.categories:
            target = self.config.generation.target_per_category
            templates = self.generate_templates(category)
            category_summary = {
                "target": target,
                "template_candidates": len(templates),
                "candidate_attempts": 0,
                "emitted_records": 0,
                "pre_record_skips": 0,
                "accepted": 0,
                "no_templates": False,
                "no_reusable_template_break": False,
            }
            attempt_summary["template_candidates"] += len(templates)
            if not templates:
                category_summary["no_templates"] = True
                attempt_summary["template_generation_empty_categories"] += 1
                attempt_summary["by_category"][category] = category_summary
                continue
            attempts = 0
            accepted = 0
            gen = self.config.generation
            quota = gen.max_examples_per_signature
            induction_rounds = 0
            category_summary["induced_templates"] = 0
            category_summary["signature_quota_rejections"] = 0
            untried = list(templates)
            first_pass = len(templates)
            max_attempts = max(target * gen.max_attempts_multiplier, len(templates))
            tier_quota = self._tier_quota(category, target)
            self._active_category = category
            self._active_tier_quota = tier_quota
            if tier_quota:
                category_summary["tier_quota"] = dict(tier_quota)
                category_summary["tier_quota_rejections"] = 0
            spilled = False
            while accepted < target and attempts < max_attempts:
                needed = self._needed_tiers(category, tier_quota)
                if tier_quota and not spilled and attempts >= int(0.75 * max_attempts):
                    spill = self._spill_tier_quota(category, tier_quota)
                    if spill:
                        category_summary["tier_spillover"] = spill
                    spilled = True
                    needed = self._needed_tiers(category, tier_quota)
                pick = self._pick_untried(untried, needed) if untried else None
                if pick is not None:
                    template = pick
                    is_first_pass = first_pass > 0
                    first_pass = max(0, first_pass - 1)
                else:
                    is_first_pass = False
                    reusable = [
                        template
                        for template in templates
                        if self._can_produce_new_question(category, template)
                        and self._template_identity(template) not in self.saturated_templates
                    ]
                    in_tier = [t for t in reusable if not needed or t.metadata.get("template_tier", "") in needed]
                    if tier_quota and reusable and not in_tier and induction_rounds < gen.template_induction_rounds:
                        reusable = []
                    elif in_tier:
                        reusable = in_tier
                    if not reusable:
                        if induction_rounds < gen.template_induction_rounds:
                            induction_rounds += 1
                            target_tier = self._most_lacking_tier(category, tier_quota)
                            tier_kwargs = {"tier": target_tier} if target_tier else {}
                            induced = self.induce_templates(
                                category, templates, round_index=induction_rounds, **tier_kwargs
                            )
                            category_summary["induced_templates"] += len(induced)
                            attempt_summary["template_candidates"] += len(induced)
                            templates.extend(induced)
                            untried.extend(induced)
                            continue
                        category_summary["no_reusable_template_break"] = True
                        attempt_summary["no_reusable_template_breaks"] += 1
                        break
                    template = self.rng.choice(reusable)
                attempts += 1
                category_summary["candidate_attempts"] += 1
                attempt_summary["candidate_attempts"] += 1
                if is_first_pass and self.structural_diversity.seen(category, template.template):
                    category_summary["pre_record_skips"] += 1
                    attempt_summary["pre_record_skips"] += 1
                    continue
                record = self.run_candidate(template)
                if record.accepted:
                    question_key = self._question_key(record.category, record.question)
                    signature = record.generation_metadata.get("query_signature", "")
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
                    elif quota and self.signature_counts[(category, signature)] >= quota:
                        record.accepted = False
                        record.judge = JudgeResult.failed("signature quota exceeded")
                        self.saturated_templates.add(self._template_identity(template))
                        category_summary["signature_quota_rejections"] += 1
                    elif tier_quota and self.tier_counts[
                        (category, record.generation_metadata.get("difficulty_tier", ""))
                    ] >= tier_quota.get(record.generation_metadata.get("difficulty_tier", ""), 0):
                        record.accepted = False
                        record.judge = JudgeResult.failed(
                            f"tier quota exceeded ({record.generation_metadata.get('difficulty_tier')})"
                        )
                        category_summary["tier_quota_rejections"] += 1
                    else:
                        if tier_quota:
                            self.tier_counts[(category, record.generation_metadata.get("difficulty_tier", ""))] += 1
                        self.accepted_question_tokens.setdefault(category, []).append(tokenize(record.question))
                        self.accepted_question_keys.add(question_key)
                        self.entity_diversity.record(category, record.entity_values)
                        self.examples.add(record.question, record.cypher, record.category)
                        self.signature_counts[(category, signature)] += 1
                        if quota and self.signature_counts[(category, signature)] >= quota:
                            self.saturated_templates.add(self._template_identity(template))
                if not record.accepted and gen.outcome_aware_binding:
                    self._retire_on_repeated_gate_failure(template, record, category_summary)
                records.append(record)
                category_summary["emitted_records"] += 1
                attempt_summary["emitted_records"] += 1
                append_jsonl(out, record.to_dict())
                if record.accepted:
                    accepted += 1
                    category_summary["accepted"] += 1
            category_summary["unique_accepted_signatures"] = sum(
                1 for (cat, _), count in self.signature_counts.items() if cat == category and count
            )
            category_summary["induction_rounds"] = induction_rounds
            if tier_quota:
                category_summary["tier_accepted"] = {tier: self.tier_counts[(category, tier)] for tier in TIERS}
                category_summary["tier_quota_unmet"] = {
                    tier: tier_quota[tier] - self.tier_counts[(category, tier)]
                    for tier in TIERS
                    if self.tier_counts[(category, tier)] < tier_quota[tier]
                }
            attempt_summary["by_category"][category] = category_summary
        if self.template_rejections:
            attempt_summary["template_rejections"] = dict(self.template_rejections)
        return PipelineResult(records=records, output_path=out, attempt_summary=attempt_summary)

    _RETIRING_GATE_FAILURES = (
        "reference has a tie",
        "cannot verify ORDER BY/LIMIT",
        "reference truncated",
        "execution returned no rows",
        "literal mismatch",
        "structural defect",
    )

    def _retire_on_repeated_gate_failure(
        self, template: TemplateCandidate, record: GenerationRecord, category_summary: dict[str, Any]
    ) -> None:
        """v3: stop retrying a template whose candidates keep failing the same deterministic gate.

        A slot-free template asks the same question every time, so one failure
        retires it; a slotted template is retired after two failures for the
        same reason (e.g. counts that tie at the top-k cutoff on this graph).
        """

        reason = record.judge.failure_reason or ""
        prefix = next((p for p in self._RETIRING_GATE_FAILURES if reason.startswith(p)), None)
        if prefix is None:
            return
        template_id = self._template_identity(template)
        self.template_gate_failures[f"{template_id}|{prefix}"] += 1
        limit = 1 if not template.slots else 2
        if self.template_gate_failures[f"{template_id}|{prefix}"] >= limit and template_id not in self.saturated_templates:
            self.saturated_templates.add(template_id)
            category_summary["templates_retired_by_gates"] = category_summary.get("templates_retired_by_gates", 0) + 1

    # --- v3 difficulty quotas ---------------------------------------------
    def _tier_quota(self, category: str, target: int) -> dict[str, int]:
        if self.difficulty_model is None:
            return {}
        shares = self.config.generation.tier_quotas.get(category) or self.config.generation.tier_quotas.get("_default")
        if not shares:
            return tier_quota_counts(category, target, self.difficulty_model)
        total = sum(float(shares.get(tier, 0.0)) for tier in TIERS) or 1.0
        raw = {tier: target * float(shares.get(tier, 0.0)) / total for tier in TIERS}
        counts = {tier: int(raw[tier]) for tier in TIERS}
        for tier in sorted(TIERS, key=lambda t: raw[t] - counts[t], reverse=True)[: target - sum(counts.values())]:
            counts[tier] += 1
        return counts

    def _needed_tiers(self, category: str, tier_quota: dict[str, int]) -> set[str]:
        return {tier for tier in TIERS if tier_quota and self.tier_counts[(category, tier)] < tier_quota.get(tier, 0)}

    def _most_lacking_tier(self, category: str, tier_quota: dict[str, int]) -> str | None:
        if not tier_quota:
            return None
        gaps = {tier: tier_quota[tier] - self.tier_counts[(category, tier)] for tier in TIERS}
        tier = max(gaps, key=lambda t: (gaps[t], TIERS.index(t)))
        return tier if gaps[tier] > 0 else None

    def _pick_untried(self, untried: list[TemplateCandidate], needed: set[str]) -> TemplateCandidate | None:
        if not untried:
            return None
        if needed:
            for index, template in enumerate(untried):
                if template.metadata.get("template_tier", "") in needed or "template_tier" not in template.metadata:
                    return untried.pop(index)
            return None
        return untried.pop(0)

    def _spill_tier_quota(self, category: str, tier_quota: dict[str, int]) -> dict[str, Any] | None:
        """After 75% of the attempt budget, move unmet quota to adjacent tiers (reported, never silent)."""

        moves: dict[str, Any] = {}
        neighbours = {"easy": ["medium", "hard"], "medium": ["hard", "easy"], "hard": ["medium", "easy"]}
        for tier in TIERS:
            gap = tier_quota[tier] - self.tier_counts[(category, tier)]
            if gap <= 0:
                continue
            # Keep what the tier reached so far plus half the gap; move the rest.
            moved = gap - gap // 2
            tier_quota[tier] -= moved
            receiver = neighbours[tier][0]
            tier_quota[receiver] += moved
            moves[tier] = {"moved": moved, "to": receiver}
        return moves or None
