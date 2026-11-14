from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from .config import RunConfig
from .graph_profiles import default_reverse_cypher_for_template, default_templates, reference_schema
from .models import SchemaSummary, TemplateCandidate
from .schema import load_schema


def estimate_run_capacity(
    config: RunConfig,
    *,
    assumed_accept_rate: float = 0.25,
    llm_calls_per_minute: float | None = None,
) -> dict[str, Any]:
    """Estimate candidate attempts and LLM calls before a long generation run."""
    if not 0 < assumed_accept_rate <= 1:
        raise ValueError("assumed_accept_rate must be in (0, 1]")
    if llm_calls_per_minute is not None and llm_calls_per_minute <= 0:
        raise ValueError("llm_calls_per_minute must be > 0")

    schema = _load_schema_for_estimate(config)
    schema_prompt_tokens = _rough_tokens(schema.to_prompt())
    templates = default_templates(config.generation.graph_profile)
    by_category: dict[str, list[TemplateCandidate]] = defaultdict(list)
    for template in templates:
        by_category[template.category].append(template)

    category_rows = []
    totals = {
        "target_examples": 0,
        "nominal_candidate_attempts": 0,
        "upper_candidate_attempts": 0,
        "template_generation_calls": 0,
        "cypher_generation_calls_nominal": 0,
        "cypher_generation_calls_upper": 0,
        "reverse_generation_calls_nominal": 0,
        "reverse_generation_calls_upper": 0,
        "repair_calls_upper": 0,
        "judge_calls_nominal": 0,
        "judge_calls_upper": 0,
        "approx_input_tokens_nominal": 0,
        "approx_input_tokens_upper": 0,
        "approx_output_tokens_upper": 0,
    }
    for category in config.generation.categories:
        seed_templates = by_category.get(category, [])
        effective_templates = _effective_template_count(
            seed_count=len(seed_templates),
            requested=config.generation.template_candidates,
            source=config.generation.template_source,
        )
        target = config.generation.target_per_category
        upper_attempts = max(target * 4, effective_templates)
        nominal_attempts = min(upper_attempts, math.ceil(target / assumed_accept_rate))
        template_generation_calls = int(
            config.generation.template_source.lower() in {"llm", "mixed"}
        )
        reverse_upper = _estimate_reverse_generation_calls(
            seed_templates=seed_templates,
            source=config.generation.template_source,
            attempts=upper_attempts,
        )
        reverse_nominal = min(
            reverse_upper,
            _estimate_reverse_generation_calls(
                seed_templates=seed_templates,
                source=config.generation.template_source,
                attempts=nominal_attempts,
            ),
        )
        fallback_multiplier = 2 if config.generation.deterministic_cypher_fallback else 1
        judge_nominal = nominal_attempts * fallback_multiplier if config.judge.enabled else 0
        judge_upper = upper_attempts * fallback_multiplier if config.judge.enabled else 0
        repair_upper = upper_attempts * config.generation.repair_attempts * fallback_multiplier
        input_tokens_per_generation = schema_prompt_tokens + 900
        input_tokens_per_judge = schema_prompt_tokens + 700
        nominal_input_tokens = (
            template_generation_calls * (schema_prompt_tokens + 500)
            + nominal_attempts * input_tokens_per_generation
            + reverse_nominal * (schema_prompt_tokens + 450)
            + judge_nominal * input_tokens_per_judge
        )
        upper_input_tokens = (
            template_generation_calls * (schema_prompt_tokens + 500)
            + upper_attempts * input_tokens_per_generation
            + reverse_upper * (schema_prompt_tokens + 450)
            + repair_upper * (schema_prompt_tokens + 550)
            + judge_upper * input_tokens_per_judge
        )
        output_tokens_upper = (
            template_generation_calls * config.models.max_tokens
            + upper_attempts * config.models.max_tokens
            + reverse_upper * 512
            + repair_upper * 512
            + judge_upper * 512
        )
        row = {
            "category": category,
            "target": target,
            "seed_templates": len(seed_templates),
            "effective_templates": effective_templates,
            "nominal_candidate_attempts": nominal_attempts,
            "upper_candidate_attempts": upper_attempts,
            "template_generation_calls": template_generation_calls,
            "cypher_generation_calls_nominal": nominal_attempts,
            "cypher_generation_calls_upper": upper_attempts,
            "reverse_generation_calls_nominal": reverse_nominal,
            "reverse_generation_calls_upper": reverse_upper,
            "repair_calls_upper": repair_upper,
            "judge_calls_nominal": judge_nominal,
            "judge_calls_upper": judge_upper,
            "approx_input_tokens_nominal": nominal_input_tokens,
            "approx_input_tokens_upper": upper_input_tokens,
            "approx_output_tokens_upper": output_tokens_upper,
        }
        category_rows.append(row)
        for key in totals:
            if key == "target_examples":
                totals[key] += target
            else:
                totals[key] += int(row.get(key, 0))

    totals["approx_total_tokens_nominal"] = (
        totals["approx_input_tokens_nominal"]
        + totals["cypher_generation_calls_nominal"] * config.models.max_tokens
        + totals["judge_calls_nominal"] * 512
    )
    totals["approx_total_tokens_upper"] = (
        totals["approx_input_tokens_upper"] + totals["approx_output_tokens_upper"]
    )
    nominal_llm_calls = _nominal_llm_calls(totals)
    upper_llm_calls = _upper_llm_calls(totals)
    if llm_calls_per_minute is not None:
        totals["nominal_wall_clock_minutes"] = nominal_llm_calls / llm_calls_per_minute
        totals["upper_wall_clock_minutes"] = upper_llm_calls / llm_calls_per_minute
    return {
        "graph_profile": config.generation.graph_profile,
        "model": config.models.generation_model,
        "judge_model": config.models.judge_model if config.judge.enabled else "disabled",
        "template_source": config.generation.template_source,
        "assumed_accept_rate": assumed_accept_rate,
        "llm_calls_per_minute": llm_calls_per_minute,
        "schema_prompt_tokens_rough": schema_prompt_tokens,
        "categories": category_rows,
        "totals": totals,
        "notes": [
            "Nominal attempts use ceil(target_per_category / assumed_accept_rate), capped by the pipeline attempt ceiling.",
            "Upper attempts match the pipeline ceiling: max(target_per_category * 4, effective_templates).",
            "Token counts are rough char/4 estimates for launch planning, not billing claims.",
        ],
    }


def format_run_estimate_markdown(estimate: dict[str, Any]) -> str:
    totals = estimate["totals"]
    lines = [
        f"# PIPE-Cypher Run Estimate: {estimate['graph_profile']}",
        "",
        f"- Model: `{estimate['model']}`",
        f"- Judge model: `{estimate['judge_model']}`",
        f"- Template source: `{estimate['template_source']}`",
        f"- Assumed acceptance rate: {estimate['assumed_accept_rate']:.2f}",
        f"- Target accepted examples: {totals['target_examples']}",
        f"- Nominal candidate attempts: {totals['nominal_candidate_attempts']}",
        f"- Upper candidate attempts: {totals['upper_candidate_attempts']}",
        f"- Nominal LLM calls: {_nominal_llm_calls(totals)}",
        f"- Upper LLM calls: {_upper_llm_calls(totals)}",
        f"- Rough nominal total tokens: {totals['approx_total_tokens_nominal']:,}",
        f"- Rough upper total tokens: {totals['approx_total_tokens_upper']:,}",
    ]
    if estimate.get("llm_calls_per_minute"):
        lines.extend(
            [
                f"- Calibrated calls/minute: {estimate['llm_calls_per_minute']:.2f}",
                f"- Rough nominal wall-clock: {_format_minutes(totals['nominal_wall_clock_minutes'])}",
                f"- Rough upper wall-clock: {_format_minutes(totals['upper_wall_clock_minutes'])}",
            ]
        )
    lines.extend(
        [
            "",
            "| Category | Target | Seeds | Effective templates | Nominal attempts | Upper attempts | Upper judge calls | Upper repair calls |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in estimate["categories"]:
        lines.append(
            "| {category} | {target} | {seed_templates} | {effective_templates} | "
            "{nominal_candidate_attempts} | {upper_candidate_attempts} | "
            "{judge_calls_upper} | {repair_calls_upper} |".format(**row)
        )
    lines.extend(["", "Notes:"])
    lines.extend(f"- {note}" for note in estimate["notes"])
    return "\n".join(lines)


def _load_schema_for_estimate(config: RunConfig) -> SchemaSummary:
    if config.paths.schema_path:
        try:
            return load_schema(config.paths.schema_path)
        except FileNotFoundError:
            pass
    return reference_schema(config.generation.graph_profile)


def _rough_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


def _effective_template_count(*, seed_count: int, requested: int, source: str) -> int:
    source = source.lower()
    if source == "default":
        return min(requested, seed_count) if seed_count else 0
    if source == "mixed":
        return max(requested, seed_count)
    if source == "llm":
        return requested
    return max(requested, seed_count)


def _estimate_reverse_generation_calls(
    *,
    seed_templates: list[TemplateCandidate],
    source: str,
    attempts: int,
) -> int:
    source = source.lower()
    if attempts <= 0:
        return 0
    if source == "llm":
        return attempts
    if not seed_templates:
        return attempts if source == "mixed" else 0
    missing_reverse = [
        template
        for template in seed_templates
        if template.slots and default_reverse_cypher_for_template(template) is None
    ]
    seeded_missing_share = len(missing_reverse) / len(seed_templates)
    seeded_calls = math.ceil(attempts * seeded_missing_share)
    if source == "mixed":
        generated_attempts = max(0, attempts - len(seed_templates))
        return max(seeded_calls, generated_attempts)
    return seeded_calls


def _nominal_llm_calls(totals: dict[str, int]) -> int:
    return (
        totals["template_generation_calls"]
        + totals["cypher_generation_calls_nominal"]
        + totals["reverse_generation_calls_nominal"]
        + totals["judge_calls_nominal"]
    )


def _upper_llm_calls(totals: dict[str, int]) -> int:
    return (
        totals["template_generation_calls"]
        + totals["cypher_generation_calls_upper"]
        + totals["reverse_generation_calls_upper"]
        + totals["repair_calls_upper"]
        + totals["judge_calls_upper"]
    )


def _format_minutes(minutes: float) -> str:
    if minutes < 60:
        return f"{minutes:.1f} minutes"
    hours = minutes / 60
    if hours < 48:
        return f"{hours:.1f} hours"
    return f"{hours / 24:.1f} days"
