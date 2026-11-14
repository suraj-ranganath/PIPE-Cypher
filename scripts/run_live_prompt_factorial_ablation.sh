#!/usr/bin/env bash
set -euo pipefail

PROMPT_VARIANTS="prompt_profile_schema_only"
PROMPT_VARIANTS+=" prompt_profile_instructions_only"
PROMPT_VARIANTS+=" prompt_profile_examples_only"
PROMPT_VARIANTS+=" prompt_profile_examples_plus_instructions"
PROMPT_VARIANTS+=" prompt_profile_full_pipe_cypher_governed"

TARGET_PER_CATEGORY="${TARGET_PER_CATEGORY:-50}" \
RUN_PREFIX="${RUN_PREFIX:-$(date +%Y%m%d_%H%M%S)_prompt_factorial${TARGET_PER_CATEGORY}}" \
VARIANT_SET="${VARIANT_SET:-${PROMPT_VARIANTS}}" \
bash scripts/run_live_ablation_suite.sh
