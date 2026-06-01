from __future__ import annotations

from collections import defaultdict
from typing import Any

from .graph_profiles import default_templates


def estimate_seed_capacity(
    *,
    profile: str,
    categories: list[str],
    target_per_category: int,
    binding_limit: int,
) -> dict[str, Any]:
    templates = default_templates(profile)
    by_category = defaultdict(list)
    for template in templates:
        by_category[template.category].append(template)

    rows = []
    for category in categories:
        category_templates = by_category.get(category, [])
        slotted = [template for template in category_templates if template.slots]
        no_slot = [template for template in category_templates if not template.slots]
        capacity = len(slotted) * binding_limit + len(no_slot)
        rows.append(
            {
                "category": category,
                "target": target_per_category,
                "seed_templates": len(category_templates),
                "slotted_templates": len(slotted),
                "no_slot_templates": len(no_slot),
                "binding_limit": binding_limit,
                "estimated_capacity": capacity,
                "meets_target": capacity >= target_per_category,
            }
        )

    return {
        "profile": profile,
        "target_per_category": target_per_category,
        "binding_limit": binding_limit,
        "categories": rows,
        "all_meet_target": all(row["meets_target"] for row in rows),
    }
