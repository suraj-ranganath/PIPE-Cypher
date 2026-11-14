from pipecypher.capacity import estimate_seed_capacity
from pipecypher.models import DEFAULT_CATEGORIES


def test_finbench_seed_capacity_meets_full_category_target():
    estimate = estimate_seed_capacity(
        profile="finbench",
        categories=DEFAULT_CATEGORIES,
        target_per_category=250,
        binding_limit=300,
    )
    assert estimate["all_meet_target"]


def test_snb_seed_capacity_meets_full_category_target():
    estimate = estimate_seed_capacity(
        profile="snb",
        categories=DEFAULT_CATEGORIES,
        target_per_category=125,
        binding_limit=200,
    )
    assert estimate["all_meet_target"]
