from __future__ import annotations

import csv
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class CalibrationMetrics:
    total_labeled: int
    agreement_rate: float
    judge_precision: float
    judge_recall: float
    false_accepts: int
    false_rejects: int


@dataclass
class AuditCoverage:
    total_rows: int
    labeled_rows: int
    unlabeled_rows: int
    judge_accepts: int
    judge_rejects: int
    by_category: dict[str, int]
    by_difficulty: dict[str, int]
    by_strategy: dict[str, int]


def load_records(path: str | Path) -> list[dict[str, Any]]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def sample_for_audit(
    records: list[dict[str, Any]],
    *,
    n: int,
    seed: int = 13,
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    unique_records = _dedupe_records(records)
    accepted = [row for row in unique_records if row.get("accepted")]
    rejected = [row for row in unique_records if not row.get("accepted")]
    half = n // 2
    sample = []
    sample.extend(rng.sample(accepted, min(half, len(accepted))))
    sample.extend(rng.sample(rejected, min(n - len(sample), len(rejected))))
    if len(sample) < n:
        remaining = [row for row in unique_records if row not in sample]
        sample.extend(rng.sample(remaining, min(n - len(sample), len(remaining))))
    rng.shuffle(sample)
    return sample


def _dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, bool]] = set()
    unique: list[dict[str, Any]] = []
    for row in records:
        key = (
            str(row.get("category", "")),
            str(row.get("question", "")),
            str(row.get("cypher", "")),
            bool(row.get("accepted")),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def write_audit_csv(records: list[dict[str, Any]], path: str | Path) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "id",
        "judge_accept",
        "human_accept",
        "category",
        "difficulty",
        "primary_strategy",
        "question",
        "cypher",
        "judge_failure_reason",
        "human_notes",
    ]
    with out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for idx, row in enumerate(records):
            features = row.get("validation", {}).get("structural_features", {})
            writer.writerow(
                {
                    "id": idx,
                    "judge_accept": str(bool(row.get("accepted"))).lower(),
                    "human_accept": "",
                    "category": row.get("category", ""),
                    "difficulty": features.get("difficulty", ""),
                    "primary_strategy": features.get("primary_strategy", ""),
                    "question": row.get("question", ""),
                    "cypher": row.get("cypher", ""),
                    "judge_failure_reason": row.get("judge", {}).get("failure_reason", ""),
                    "human_notes": "",
                }
            )


def _parse_bool(value: str) -> bool | None:
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "accept", "accepted"}:
        return True
    if text in {"false", "0", "no", "n", "reject", "rejected"}:
        return False
    return None


def analyze_audit_csv(path: str | Path) -> CalibrationMetrics:
    rows = []
    with Path(path).open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            judge = _parse_bool(row.get("judge_accept", ""))
            human = _parse_bool(row.get("human_accept", ""))
            if judge is None or human is None:
                continue
            rows.append((judge, human))
    total = len(rows)
    if total == 0:
        return CalibrationMetrics(0, 0.0, 0.0, 0.0, 0, 0)
    agreements = sum(1 for judge, human in rows if judge == human)
    true_accepts = sum(1 for judge, human in rows if judge and human)
    judge_accepts = sum(1 for judge, _ in rows if judge)
    human_accepts = sum(1 for _, human in rows if human)
    false_accepts = sum(1 for judge, human in rows if judge and not human)
    false_rejects = sum(1 for judge, human in rows if not judge and human)
    precision = true_accepts / judge_accepts if judge_accepts else 0.0
    recall = true_accepts / human_accepts if human_accepts else 0.0
    return CalibrationMetrics(
        total_labeled=total,
        agreement_rate=agreements / total,
        judge_precision=precision,
        judge_recall=recall,
        false_accepts=false_accepts,
        false_rejects=false_rejects,
    )


def summarize_audit_csv(path: str | Path) -> AuditCoverage:
    total = 0
    labeled = 0
    judge_accepts = 0
    judge_rejects = 0
    by_category: dict[str, int] = {}
    by_difficulty: dict[str, int] = {}
    by_strategy: dict[str, int] = {}
    with Path(path).open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += 1
            if _parse_bool(row.get("human_accept", "")) is not None:
                labeled += 1
            judge = _parse_bool(row.get("judge_accept", ""))
            if judge is True:
                judge_accepts += 1
            elif judge is False:
                judge_rejects += 1
            _increment(by_category, row.get("category", "unknown"))
            _increment(by_difficulty, row.get("difficulty", "unknown"))
            _increment(by_strategy, row.get("primary_strategy", "unknown"))
    return AuditCoverage(
        total_rows=total,
        labeled_rows=labeled,
        unlabeled_rows=total - labeled,
        judge_accepts=judge_accepts,
        judge_rejects=judge_rejects,
        by_category=dict(sorted(by_category.items())),
        by_difficulty=dict(sorted(by_difficulty.items())),
        by_strategy=dict(sorted(by_strategy.items())),
    )


def _increment(counts: dict[str, int], value: str | None) -> None:
    key = str(value or "unknown")
    counts[key] = counts.get(key, 0) + 1
