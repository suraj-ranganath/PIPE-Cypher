from pipecypher.experiments import (
    apply_variant,
    build_experiment_variants,
    format_run_comparison_csv,
    format_run_comparison_markdown,
    format_summary_lines,
    summarize_records,
    variant_applies_to_graph,
)


def test_build_experiment_variants_includes_baseline():
    matrix = {
        "baselines": [{"name": "full_pipe_cypher"}],
        "ablations": {
            "retrieval_top_k": [0],
            "judge": [False],
            "rewrite": [False],
            "generation_model": ["Qwen/Test"],
            "graph_mix": ["finbench_plus_snb"],
        },
    }
    names = {variant["name"] for variant in build_experiment_variants(matrix)}
    assert "full_pipe_cypher" in names
    assert "ablation_retrieval_topk_0" in names
    assert "ablation_judge_false" in names
    assert "ablation_rewrite_false" in names
    assert "ablation_model_Qwen_Test" in names
    assert "ablation_graph_mix_finbench_plus_snb" in names


def test_apply_variant_disables_judge_for_validators_repair():
    cfg = {"generation": {"retrieval_top_k": 4, "repair_attempts": 0}, "judge": {"enabled": True}}
    updated = apply_variant(cfg, {"baseline": "validators_repair"})
    assert updated["generation"]["retrieval_top_k"] == 0
    assert updated["generation"]["normalize_cypher"] is True
    assert updated["generation"]["repair_attempts"] == 1
    assert updated["judge"]["enabled"] is False


def test_apply_variant_unconstrained_disables_seed_fallbacks():
    cfg = {
        "generation": {
            "template_source": "mixed",
            "allow_seed_template_fallback": True,
            "retrieval_top_k": 4,
            "normalize_cypher": True,
            "repair_attempts": 2,
            "deterministic_cypher_fallback": True,
        },
        "judge": {"enabled": True},
    }
    updated = apply_variant(cfg, {"baseline": "unconstrained_local_llm"})
    assert updated["generation"]["template_source"] == "llm"
    assert updated["generation"]["allow_seed_template_fallback"] is False
    assert updated["generation"]["deterministic_cypher_fallback"] is False
    assert updated["judge"]["enabled"] is False


def test_apply_variant_can_disable_rewrite_for_ablation():
    cfg = {"generation": {"normalize_cypher": True}, "judge": {"enabled": True}}
    updated = apply_variant(cfg, {"baseline": "full_pipe_cypher", "rewrite": False})
    assert updated["generation"]["normalize_cypher"] is False
    assert updated["judge"]["enabled"] is True


def test_graph_mix_variants_are_filtered_by_graph_profile():
    finbench_only = {"graph_mix": "finbench_only"}
    combined = {"graph_mix": "finbench_plus_snb"}
    assert variant_applies_to_graph(finbench_only, "finbench")
    assert not variant_applies_to_graph(finbench_only, "snb")
    assert variant_applies_to_graph(combined, "finbench")
    assert variant_applies_to_graph(combined, "snb")


def test_summarize_records_counts_core_gates():
    rows = [
        {
            "accepted": True,
            "category": "simple_retrieval",
            "validation": {
                "read_only": True,
                "syntax_valid": True,
                "schema_valid": True,
                "structural_features": {"difficulty": "easy", "primary_strategy": "single_hop"},
                "issues": [],
            },
            "execution": {"success": True},
            "judge": {"passed": True},
        },
        {
            "accepted": False,
            "category": "simple_retrieval",
            "validation": {
                "read_only": True,
                "syntax_valid": True,
                "schema_valid": False,
                "structural_features": {"difficulty": "medium", "primary_strategy": "node_scan"},
                "issues": [{"code": "unknown_property"}],
            },
            "execution": {"success": False},
            "judge": {"passed": False},
        },
    ]
    summary = summarize_records(rows)
    assert summary["records"] == 2
    assert summary["accepted"] == 1
    assert summary["accept_rate"] == 0.5
    assert summary["accepted_by_category"] == {"simple_retrieval": 1}
    assert summary["gates"]["judge_pass"] == 1
    assert summary["issues"] == {"unknown_property": 1}
    assert "accept_rate=0.500" in format_summary_lines(summary)


def test_format_run_comparison_outputs_paper_tables():
    summaries = [
        {
            "run": "run_a",
            "records": 2,
            "accepted": 1,
            "accept_rate": 0.5,
            "gates": {"judge_pass": 1, "execution_success": 2},
            "accepted_by_category": {"simple_retrieval": 1},
        }
    ]
    markdown = format_run_comparison_markdown(summaries)
    csv_text = format_run_comparison_csv(summaries)
    assert "| run_a | 2 | 1 | 0.500 | 1 | 2 | simple_retrieval:1 |" in markdown
    assert "run_a,2,1,0.500,1,2,simple_retrieval:1" in csv_text
