#!/usr/bin/env python3
"""Re-judge PIPE-Cypher benchmark items with an independent local judge (E2.1).

The judge call goes through the unchanged ``pipecypher.judge.LLMJudge`` path, so
the system prompt, ``JUDGE_PROMPT`` template, schema slice, execution sample,
validation summary, temperature (0.0), and token budget (512) match the
original Qwen judge contract. Output rows are PRIVATE/internal (they contain
questions, Cypher literals, result rows, and raw judge text).

Exit codes: 0 complete; 2 preflight/config failure; 3 aborted after consecutive
failed calls; 4 failed-call rate above --max-error-rate.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipecypher.judge_agreement import (  # noqa: E402
    ORIGINAL_JUDGE_MAX_TOKENS,
    ORIGINAL_JUDGE_TEMPERATURE,
    PRIVATE_NOTICE,
    RejudgeAborted,
    SourceRecordIndex,
    assert_hosted_graphs_public,
    default_judge_label,
    default_judge_role,
    git_revision,
    items_from_benchmark,
    items_from_records,
    load_benchmark_rows,
    load_records_files,
    merge_items,
    preflight_judge_endpoint,
    reexecute_items,
    run_rejudge,
    select_items,
    sha256_file,
    summary_path_for,
    write_skipped_log,
)
from pipecypher.llm import OpenAICompatibleLLM  # noqa: E402
from pipecypher.schema import load_schema  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--benchmark", default="", help="Benchmark export directory or JSONL")
    parser.add_argument("--split", default="all", choices=["all", "train", "dev", "test"])
    parser.add_argument(
        "--records",
        nargs="*",
        default=[],
        help="Generation run directories or records.jsonl files whose judge-decided candidates are re-judged",
    )
    parser.add_argument(
        "--records-scope",
        choices=["rejected", "all"],
        default="rejected",
        help="Which records to include (accepted records duplicate benchmark rows and are deduped by id)",
    )
    parser.add_argument(
        "--schema",
        action="append",
        required=True,
        help="graph_profile=path; use the schema file the original generation run used",
    )
    parser.add_argument(
        "--context-source",
        choices=["auto", "record", "export"],
        default="auto",
        help=(
            "auto: restore original judge context from the source records.jsonl when available, "
            "else reconstruct from the export row; record: require source records; export: export-only"
        ),
    )
    parser.add_argument(
        "--source-root",
        action="append",
        default=[],
        help="Extra directories used to resolve relative source.records_path values (repo root is always tried)",
    )
    parser.add_argument(
        "--neo4j-config",
        action="append",
        default=[],
        help="graph_profile=config.yaml; re-execute references read-only for that graph instead of stored rows",
    )
    parser.add_argument(
        "--provider",
        choices=["vllm", "openai", "openrouter"],
        default="vllm",
        help=(
            "vllm: local weights behind a project-controlled OpenAI-compatible server (default). "
            "openai / openrouter: hosted APIs, allowed only for public LDBC graphs (finbench, snb); "
            "keys are read from OPENAI_API_KEY / OPENROUTER_API_KEY and never logged. OpenRouter "
            "routing comes from PIPE_CYPHER_OPENROUTER_ROUTING (JSON)"
        ),
    )
    parser.add_argument(
        "--base-url",
        default="",
        help="Default: http://localhost:8000/v1 (vllm) or https://api.openai.com/v1 (openai)",
    )
    parser.add_argument("--model", required=True, help="Served model id (must appear in /models)")
    parser.add_argument(
        "--no-temperature",
        action="store_true",
        help="Omit temperature from requests (hosted reasoning models that reject non-default values)",
    )
    parser.add_argument(
        "--reasoning-effort",
        default=None,
        help=(
            "Default: 'none' for vllm (reasoning disabled, as in the original judge); unset for openai. "
            "For openai, 'none' or '' omits the field"
        ),
    )
    parser.add_argument("--judge-label", default="", help="Short label used in reports (default: model basename)")
    parser.add_argument(
        "--judge-role",
        choices=["independent", "same_family_control"],
        default="",
        help="Default: same_family_control for Qwen models, else independent",
    )
    parser.add_argument("--output", required=True, help="Output JSONL (PRIVATE/internal)")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--seed", type=int, default=None, help="Seed for the random subset when --limit is set")
    parser.add_argument(
        "--system-message-mode",
        choices=["separate", "merge"],
        default=os.getenv("PIPE_CYPHER_SYSTEM_MESSAGE_MODE", "separate"),
        help="Use 'merge' for chat templates that reject the system role (e.g. Gemma)",
    )
    parser.add_argument("--timeout-sec", type=int, default=180)
    parser.add_argument("--temperature", type=float, default=ORIGINAL_JUDGE_TEMPERATURE)
    parser.add_argument("--max-tokens", type=int, default=ORIGINAL_JUDGE_MAX_TOKENS)
    parser.add_argument("--concurrency", type=int, default=1, help="Parallel requests to the endpoint")
    parser.add_argument(
        "--request-retries",
        type=int,
        default=0,
        help=(
            "Extra wrapper-level retries for transport/429/5xx errors. The client already retries these "
            "internally, so an item is a failed call only after all retries are exhausted"
        ),
    )
    parser.add_argument("--max-consecutive-errors", type=int, default=5)
    parser.add_argument("--max-error-rate", type=float, default=0.01)
    parser.add_argument("--resume", action="store_true", help="Skip items already decided in --output")
    parser.add_argument("--no-save-prompts", action="store_true", help="Do not store full prompt text per row")
    parser.add_argument("--dry-run", action="store_true", help="Build items and report counts without calling a model")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.benchmark and not args.records:
        raise SystemExit("pass --benchmark and/or --records")
    if (
        args.temperature != ORIGINAL_JUDGE_TEMPERATURE
        or args.max_tokens != ORIGINAL_JUDGE_MAX_TOKENS
        or args.no_temperature
    ):
        print(
            "warning: sampling settings differ from the original judge contract "
            f"(temperature={ORIGINAL_JUDGE_TEMPERATURE}, max_tokens={ORIGINAL_JUDGE_MAX_TOKENS}); "
            "the deviation is recorded in every output row's call_settings/temperature/max_tokens",
            file=sys.stderr,
        )

    schemas = {}
    for item in args.schema:
        if "=" not in item:
            raise SystemExit("--schema entries must use graph_profile=path")
        graph, path = item.split("=", 1)
        schemas[graph] = load_schema(path)

    groups = []
    skipped = []
    if args.benchmark:
        rows = load_benchmark_rows(args.benchmark, args.split)
        index = SourceRecordIndex([Path.cwd(), PROJECT_ROOT, *args.source_root])
        bench_items, bench_skipped = items_from_benchmark(
            rows, schemas, context_mode=args.context_source, source_index=index
        )
        groups.append(bench_items)
        skipped.extend(bench_skipped)
    if args.records:
        records = load_records_files(args.records)
        record_items, record_skipped = items_from_records(records, schemas, scope=args.records_scope)
        groups.append(record_items)
        skipped.extend(record_skipped)
    items, merge_skipped = merge_items(*groups)
    skipped.extend(merge_skipped)
    items = select_items(items, limit=args.limit, seed=args.seed)
    if args.provider in ("openai", "openrouter"):
        try:
            assert_hosted_graphs_public(item.graph_profile for item in items)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2

    counts: dict[str, int] = {}
    for item in items:
        key = f"{item.item_source}:{item.context_source}"
        counts[key] = counts.get(key, 0) + 1
    print(f"items={len(items)} by_source_context={json.dumps(counts, sort_keys=True)} skipped={len(skipped)}", flush=True)

    out = Path(args.output)
    skipped_path = out.with_name(out.stem + ".skipped.jsonl")
    if args.dry_run:
        write_skipped_log(skipped_path, skipped)
        print(f"dry_run: wrote skipped log {skipped_path}")
        return 0
    if out.exists() and not args.resume:
        raise SystemExit(f"{out} exists; pass --resume to continue it or choose a new --output")
    from pipecypher.llm import DEFAULT_BASE_URLS

    base_url = args.base_url or DEFAULT_BASE_URLS[args.provider]
    reasoning_effort = args.reasoning_effort
    if reasoning_effort is None and args.provider == "vllm":
        reasoning_effort = "none"

    try:
        served = preflight_judge_endpoint(base_url, args.model, provider=args.provider)
    except Exception as exc:
        print(f"Model preflight failed: {exc}", file=sys.stderr)
        return 2
    print(f"preflight_ok model={args.model} served={served}", flush=True)

    if args.neo4j_config:
        from pipecypher.config import load_config
        from pipecypher.cypher_client import Neo4jCypherClient

        clients = {}
        for item in args.neo4j_config:
            if "=" not in item:
                raise SystemExit("--neo4j-config entries must use graph_profile=config.yaml")
            graph, path = item.split("=", 1)
            cfg = load_config(path).neo4j
            clients[graph] = Neo4jCypherClient(
                cfg.uri,
                cfg.user,
                cfg.password,
                database=cfg.database,
                timeout_sec=cfg.query_timeout_sec,
                enforce_read_transactions=True,
            )
        try:
            reexecute_items(items, clients)
        finally:
            for client in clients.values():
                client.close()

    llm = OpenAICompatibleLLM(
        base_url,
        args.model,
        timeout_sec=args.timeout_sec,
        reasoning_effort=reasoning_effort,
        include_reasoning=False,
        enable_thinking=False,
        strip_reasoning=True,
        system_message_mode=args.system_message_mode,
        provider=args.provider,
        send_temperature=not args.no_temperature,
    )
    call_settings = {
        "provider": args.provider,
        "base_url": base_url,
        "send_temperature": not args.no_temperature,
        "reasoning_effort": reasoning_effort,
        "include_reasoning": False if args.provider == "vllm" else None,
        "enable_thinking": False if args.provider == "vllm" else None,
        "timeout_sec": args.timeout_sec,
    }
    judge_label = args.judge_label or default_judge_label(args.model)
    judge_role = args.judge_role or default_judge_role(args.model)
    benchmark_rows_file = None
    if args.benchmark:
        candidate = Path(args.benchmark)
        benchmark_rows_file = candidate / f"{args.split}.jsonl" if candidate.is_dir() else candidate
    metadata = {
        "privacy": PRIVATE_NOTICE,
        "base_url": base_url,
        "served_models": served,
        "system_message_mode": args.system_message_mode,
        "code_revision": git_revision(PROJECT_ROOT),
        "benchmark": args.benchmark,
        "benchmark_split": args.split,
        "benchmark_sha256": sha256_file(benchmark_rows_file) if benchmark_rows_file and benchmark_rows_file.exists() else None,
        "records": args.records,
        "records_scope": args.records_scope,
        "context_source_mode": args.context_source,
        "neo4j_reexecution_graphs": [item.split("=", 1)[0] for item in args.neo4j_config],
        "schemas": {item.split("=", 1)[0]: {"path": item.split("=", 1)[1], "sha256": sha256_file(item.split("=", 1)[1])} for item in args.schema},
        "limit": args.limit,
        "seed": args.seed,
        "skipped_log": str(skipped_path),
        "argv": sys.argv if argv is None else argv,
    }
    write_skipped_log(skipped_path, skipped)
    try:
        summary = run_rejudge(
            items,
            llm=llm,
            schemas=schemas,
            output_path=out,
            judge_label=judge_label,
            judge_model=args.model,
            judge_role=judge_role,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            concurrency=args.concurrency,
            max_consecutive_errors=args.max_consecutive_errors,
            max_error_rate=args.max_error_rate,
            request_retries=args.request_retries,
            resume=args.resume,
            save_prompts=not args.no_save_prompts,
            system_message_mode=args.system_message_mode,
            call_settings=call_settings,
            run_metadata=metadata,
            skipped=skipped,
        )
    except RejudgeAborted as exc:
        _write_summary(out, exc.summary)
        print(str(exc), file=sys.stderr)
        return 3
    _write_summary(out, summary)
    print(
        f"status={summary['status']} processed={summary['items_processed']} "
        f"failed_calls={summary['failed_calls']} rate={summary['failed_call_rate']:.4f} output={out}"
    )
    if summary["status"] != "complete":
        print(
            f"failed-call rate {summary['failed_call_rate']:.4f} exceeds --max-error-rate {args.max_error_rate}; "
            "rerun with --resume after fixing the endpoint",
            file=sys.stderr,
        )
        return 4
    return 0


def _write_summary(out: Path, summary: dict) -> None:
    path = summary_path_for(out)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(f"wrote {path}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
