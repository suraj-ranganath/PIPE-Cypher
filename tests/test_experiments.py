import json

from pipecypher.experiments import (
    apply_variant,
    build_experiment_variants,
    format_run_comparison_csv,
    format_run_comparison_markdown,
    format_summary_lines,
    summarize_records,
    variant_applies_to_graph,
)
from pipecypher.io import write_jsonl
from pipecypher.ablation_suite import (
    audit_ablation_suite_for_paper,
    format_ablation_suite_csv,
    format_ablation_suite_audit_markdown,
    format_ablation_suite_markdown,
    summarize_ablation_suite,
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
            "prompt_profile": ["schema_only"],
        },
    }
    names = {variant["name"] for variant in build_experiment_variants(matrix)}
    assert "full_pipe_cypher" in names
    assert "ablation_retrieval_topk_0" in names
    assert "ablation_judge_false" in names
    assert "ablation_rewrite_false" in names
    assert "ablation_model_Qwen_Test" in names
    assert "ablation_graph_mix_finbench_plus_snb" in names
    assert "prompt_profile_schema_only" in names


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


def test_apply_variant_sets_prompt_profile_for_prompt_factorial_ablation():
    cfg = {"generation": {"prompt_profile": "full_pipe_cypher_governed"}, "judge": {"enabled": True}}
    updated = apply_variant(
        cfg,
        {
            "baseline": "full_pipe_cypher",
            "prompt_profile": "examples_plus_instructions",
        },
    )

    assert updated["generation"]["prompt_profile"] == "examples_plus_instructions"


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


def test_summarize_ablation_suite_marks_missing_and_incomplete_runs(tmp_path):
    run_dir = tmp_path / "20260601_finbench_reverse_only"
    write_jsonl(
        run_dir / "records.jsonl",
        [
            {
                "accepted": True,
                "category": "simple_retrieval",
                "validation": {
                    "read_only": True,
                    "syntax_valid": True,
                    "schema_valid": True,
                    "structural_features": {
                        "difficulty": "easy",
                        "primary_strategy": "single_hop",
                    },
                },
                "execution": {"success": True},
                "judge": {"passed": True},
            }
        ],
    )

    report = summarize_ablation_suite(
        [run_dir],
        target_per_category=1,
        category_count=1,
        expected_graphs=["finbench", "snb"],
        expected_variants=["reverse_only"],
    )

    assert report["all_runs_finished"] is False
    assert report["runs"][0]["graph"] == "finbench"
    assert report["runs"][0]["variant"] == "reverse_only"
    assert report["runs"][0]["categories_at_target"] == 1
    assert report["runs"][0]["summary_present"] is False
    assert report["missing"] == [{"graph": "snb", "variant": "reverse_only"}]
    assert "do not report as paper evidence" in report["research_status"]


def test_summarize_ablation_suite_complete_target25_is_interim(tmp_path):
    run_dirs = []
    for graph in ["finbench", "snb"]:
        run_dir = tmp_path / f"20260601_{graph}_full_pipe_cypher"
        write_jsonl(
            run_dir / "records.jsonl",
            [
                {
                    "accepted": True,
                    "category": "simple_retrieval",
                    "validation": {
                        "read_only": True,
                        "syntax_valid": True,
                        "schema_valid": True,
                        "structural_features": {
                            "difficulty": "easy",
                            "primary_strategy": "single_hop",
                        },
                    },
                    "execution": {"success": True},
                    "judge": {"passed": True},
                }
                for _ in range(25)
            ],
        )
        (run_dir / "summary.txt").write_text("records=25\naccepted=25\n", encoding="utf-8")
        run_dirs.append(run_dir)

    report = summarize_ablation_suite(
        run_dirs,
        target_per_category=25,
        category_count=1,
        expected_graphs=["finbench", "snb"],
        expected_variants=["full_pipe_cypher"],
        metadata={
            "run_prefix": "20260601_ablation25",
            "generation_model": "Qwen/Test",
            "judge_model": "Qwen/Test",
            "code_revision": "abc123",
            "log_file": "logs/test.log",
        },
    )
    markdown = format_ablation_suite_markdown(report)

    assert report["all_runs_finished"] is True
    assert report["research_status"] == "interim scaled checkpoint; larger final ablations preferred"
    assert report["metadata"]["code_revision"] == "abc123"
    assert "| Full PIPE-Cypher | finbench |" in markdown
    assert "generation_model: `Qwen/Test`" in markdown
    assert "| Full PIPE-Cypher | finbench | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |" in markdown

    csv_text = format_ablation_suite_csv(report)
    assert "setting,graph,run,candidate_attempts,records,accepted,accept_rate" in csv_text
    assert "Full PIPE-Cypher,finbench" in csv_text
    assert ",25,25,25,1.000000,1,1,true,1.000000,1.000000,1.000000,1.000000,1.000000" in csv_text

    audit = audit_ablation_suite_for_paper(report)
    assert audit["paper_ready"] is False
    assert {check["name"] for check in audit["failed_checks"]} == {"target_is_large_enough"}
    audit_markdown = format_ablation_suite_audit_markdown(audit)
    assert "Status: `not_paper_ready`" in audit_markdown
    assert "| target_is_large_enough | no | target_per_category=25; required>=50 |" in audit_markdown


def test_ablation_suite_audit_accepts_complete_target50(tmp_path):
    run_dirs = []
    rows = [
        {
            "accepted": True,
            "category": "simple_retrieval",
            "validation": {
                "read_only": True,
                "syntax_valid": True,
                "schema_valid": True,
                "structural_features": {
                    "difficulty": "easy",
                    "primary_strategy": "single_hop",
                },
            },
            "execution": {"success": True},
            "judge": {"passed": True},
        }
        for _ in range(50)
    ]
    for graph in ["finbench", "snb"]:
        for variant in ["unconstrained_local_llm", "full_pipe_cypher"]:
            run_dir = tmp_path / f"20260601_{graph}_{variant}"
            if variant == "full_pipe_cypher":
                write_jsonl(run_dir / "records.jsonl", rows)
                attempt_summary = {
                    "candidate_attempts": 50,
                    "emitted_records": 50,
                    "pre_record_skips": 0,
                    "template_generation_empty_categories": 0,
                }
            else:
                write_jsonl(run_dir / "records.jsonl", [])
                attempt_summary = {
                    "candidate_attempts": 200,
                    "emitted_records": 0,
                    "pre_record_skips": 200,
                    "template_generation_empty_categories": 0,
                }
            (run_dir / "summary.txt").write_text(
                "attempt_summary=" + json.dumps(attempt_summary) + "\n",
                encoding="utf-8",
            )
            run_dirs.append(run_dir)

    report = summarize_ablation_suite(
        run_dirs,
        target_per_category=50,
        category_count=1,
        expected_graphs=["finbench", "snb"],
        expected_variants=["unconstrained_local_llm", "full_pipe_cypher"],
        metadata={
            "run_prefix": "20260601_ablation50",
            "generation_model": "Qwen/Test",
            "judge_model": "Qwen/Test",
            "code_revision": "abc123",
            "log_file": "logs/test.log",
        },
    )
    audit = audit_ablation_suite_for_paper(report)

    assert audit["paper_ready"] is True
    assert audit["failed_checks"] == []
    assert len(audit["empty_baseline_runs"]) == 2
    assert len(audit["unconstrained_stress_baseline_runs"]) == 2


def test_ablation_suite_audit_accepts_underfilled_unconstrained_stress_baseline(tmp_path):
    run_dirs = []
    full_rows = [
        {
            "accepted": True,
            "category": "simple_retrieval",
            "validation": {
                "read_only": True,
                "syntax_valid": True,
                "schema_valid": True,
                "structural_features": {
                    "difficulty": "easy",
                    "primary_strategy": "single_hop",
                },
            },
            "execution": {"success": True},
            "judge": {"passed": True},
        }
        for _ in range(50)
    ]
    unconstrained_rows = [
        {
            "accepted": index < 5,
            "category": "simple_retrieval",
            "validation": {
                "read_only": True,
                "syntax_valid": True,
                "schema_valid": index < 5,
                "structural_features": {
                    "difficulty": "easy",
                    "primary_strategy": "single_hop",
                },
                "issues": [] if index < 5 else [{"code": "unknown_property"}],
            },
            "execution": {"success": index < 5},
            "judge": {"passed": False},
        }
        for index in range(20)
    ]
    for graph in ["finbench", "snb"]:
        for variant, rows, attempts in [
            ("unconstrained_local_llm", unconstrained_rows, 80),
            ("full_pipe_cypher", full_rows, 50),
        ]:
            run_dir = tmp_path / f"20260601_{graph}_{variant}"
            write_jsonl(run_dir / "records.jsonl", rows)
            (run_dir / "summary.txt").write_text(
                "attempt_summary="
                + json.dumps(
                    {
                        "candidate_attempts": attempts,
                        "emitted_records": len(rows),
                        "pre_record_skips": attempts - len(rows),
                        "template_generation_empty_categories": 0,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            run_dirs.append(run_dir)

    report = summarize_ablation_suite(
        run_dirs,
        target_per_category=50,
        category_count=1,
        expected_graphs=["finbench", "snb"],
        expected_variants=["unconstrained_local_llm", "full_pipe_cypher"],
        metadata={
            "run_prefix": "20260601_ablation50",
            "generation_model": "Qwen/Test",
            "judge_model": "Qwen/Test",
            "code_revision": "abc123",
            "log_file": "logs/test.log",
        },
    )
    audit = audit_ablation_suite_for_paper(report)

    assert audit["paper_ready"] is True
    assert audit["failed_checks"] == []
    assert len(audit["empty_baseline_runs"]) == 0
    assert len(audit["unconstrained_stress_baseline_runs"]) == 2
