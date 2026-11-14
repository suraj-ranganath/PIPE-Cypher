from __future__ import annotations

import importlib.util
import math
import re
import string
from collections import Counter
from typing import Any


TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


DETERMINISTIC_TEXT_METRIC_KEYS = [
    "exact_match",
    "normalized_exact_match",
    "rouge1_precision",
    "rouge1_recall",
    "rouge1_f1",
    "rouge2_precision",
    "rouge2_recall",
    "rouge2_f1",
    "rougeL_precision",
    "rougeL_recall",
    "rougeL_f1",
    "bleu",
    "meteor",
    "cosine",
    "jaro_winkler",
]

OPTIONAL_TEXT_METRIC_KEYS = [
    "bertscore_precision",
    "bertscore_recall",
    "bertscore_f1",
    "frugalscore",
]


def compute_text_pair_metrics(
    prediction: str,
    reference: str,
    *,
    include_optional: bool = False,
    bertscore_model: str | None = None,
    bertscore_lang: str = "en",
) -> dict[str, Any]:
    """Compute reference-based surface metrics for a prediction/reference text pair."""
    pred = "" if prediction is None else str(prediction)
    ref = "" if reference is None else str(reference)
    pred_tokens = tokenize(pred)
    ref_tokens = tokenize(ref)
    metrics: dict[str, Any] = {
        "exact_match": float(pred == ref),
        "normalized_exact_match": float(normalize_answer(pred) == normalize_answer(ref)),
        "bleu": sentence_bleu(pred_tokens, ref_tokens),
        "meteor": meteor_score(pred_tokens, ref_tokens),
        "cosine": cosine_similarity(pred_tokens, ref_tokens),
        "jaro_winkler": jaro_winkler_similarity(
            normalize_whitespace(pred).lower(),
            normalize_whitespace(ref).lower(),
        ),
    }
    for n in (1, 2):
        scores = rouge_n(pred_tokens, ref_tokens, n)
        metrics[f"rouge{n}_precision"] = scores["precision"]
        metrics[f"rouge{n}_recall"] = scores["recall"]
        metrics[f"rouge{n}_f1"] = scores["f1"]
    rouge_l_scores = rouge_l(pred_tokens, ref_tokens)
    metrics["rougeL_precision"] = rouge_l_scores["precision"]
    metrics["rougeL_recall"] = rouge_l_scores["recall"]
    metrics["rougeL_f1"] = rouge_l_scores["f1"]

    if include_optional:
        metrics.update(
            optional_embedding_metrics(
                pred,
                ref,
                bertscore_model=bertscore_model,
                bertscore_lang=bertscore_lang,
            )
        )
    else:
        metrics.update({key: None for key in OPTIONAL_TEXT_METRIC_KEYS})
        metrics["bertscore_status"] = optional_metric_status()["bertscore"]
        metrics["frugalscore_status"] = optional_metric_status()["frugalscore"]
    return metrics


def prefix_metrics(metrics: dict[str, Any], prefix: str) -> dict[str, Any]:
    return {f"{prefix}_{key}": value for key, value in metrics.items()}


def optional_metric_status() -> dict[str, str]:
    return {
        "bertscore": "available" if importlib.util.find_spec("bert_score") else "unavailable",
        "frugalscore": "available" if importlib.util.find_spec("evaluate") else "unavailable",
    }


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def normalize_whitespace(text: str) -> str:
    return " ".join(str(text).split())


def normalize_answer(text: str) -> str:
    lowered = str(text).lower()
    no_punc = "".join(" " if char in string.punctuation else char for char in lowered)
    tokens = [token for token in no_punc.split() if token not in {"a", "an", "the"}]
    return " ".join(tokens)


def rouge_n(pred_tokens: list[str], ref_tokens: list[str], n: int) -> dict[str, float]:
    if n <= 0:
        raise ValueError("n must be positive")
    pred = Counter(_ngrams(pred_tokens, n))
    ref = Counter(_ngrams(ref_tokens, n))
    return _overlap_scores(pred, ref)


def rouge_l(pred_tokens: list[str], ref_tokens: list[str]) -> dict[str, float]:
    if not pred_tokens and not ref_tokens:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    if not pred_tokens or not ref_tokens:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    lcs = _lcs_len(pred_tokens, ref_tokens)
    precision = lcs / len(pred_tokens)
    recall = lcs / len(ref_tokens)
    return {"precision": precision, "recall": recall, "f1": _f1(precision, recall)}


def sentence_bleu(pred_tokens: list[str], ref_tokens: list[str], max_order: int = 4) -> float:
    """Dependency-light sentence BLEU with effective order and mild smoothing."""
    if not pred_tokens and not ref_tokens:
        return 1.0
    if not pred_tokens or not ref_tokens:
        return 0.0
    max_order = min(max_order, len(pred_tokens))
    if max_order == 0:
        return 0.0
    precisions = []
    for n in range(1, max_order + 1):
        pred = Counter(_ngrams(pred_tokens, n))
        ref = Counter(_ngrams(ref_tokens, n))
        total = sum(pred.values())
        overlap = sum(min(count, ref[gram]) for gram, count in pred.items())
        if n == 1 and overlap == 0:
            return 0.0
        precisions.append((overlap + 1) / (total + 1))
    brevity_penalty = 1.0
    if len(pred_tokens) < len(ref_tokens):
        brevity_penalty = math.exp(1 - len(ref_tokens) / len(pred_tokens))
    return brevity_penalty * math.exp(sum(math.log(p) for p in precisions) / len(precisions))


def meteor_score(pred_tokens: list[str], ref_tokens: list[str]) -> float:
    if not pred_tokens and not ref_tokens:
        return 1.0
    if not pred_tokens or not ref_tokens:
        return 0.0
    matches = _exact_unigram_alignment(pred_tokens, ref_tokens)
    matched = len(matches)
    if matched == 0:
        return 0.0
    precision = matched / len(pred_tokens)
    recall = matched / len(ref_tokens)
    f_mean = (10 * precision * recall) / (recall + 9 * precision) if precision and recall else 0.0
    chunks = _alignment_chunks(matches)
    penalty = 0.5 * (chunks / matched) ** 3
    return (1 - penalty) * f_mean


def cosine_similarity(pred_tokens: list[str], ref_tokens: list[str]) -> float:
    if not pred_tokens and not ref_tokens:
        return 1.0
    if not pred_tokens or not ref_tokens:
        return 0.0
    pred = Counter(pred_tokens)
    ref = Counter(ref_tokens)
    dot = sum(count * ref[token] for token, count in pred.items())
    pred_norm = math.sqrt(sum(count * count for count in pred.values()))
    ref_norm = math.sqrt(sum(count * count for count in ref.values()))
    if pred_norm == 0 or ref_norm == 0:
        return 0.0
    return dot / (pred_norm * ref_norm)


def jaro_winkler_similarity(s1: str, s2: str, *, prefix_scale: float = 0.1) -> float:
    if s1 == s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    match_distance = max(len(s1), len(s2)) // 2 - 1
    s1_matches = [False] * len(s1)
    s2_matches = [False] * len(s2)
    matches = 0
    for i, char in enumerate(s1):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len(s2))
        for j in range(start, end):
            if s2_matches[j] or char != s2[j]:
                continue
            s1_matches[i] = True
            s2_matches[j] = True
            matches += 1
            break
    if matches == 0:
        return 0.0
    s1_matched = [char for char, matched in zip(s1, s1_matches, strict=True) if matched]
    s2_matched = [char for char, matched in zip(s2, s2_matches, strict=True) if matched]
    transpositions = sum(c1 != c2 for c1, c2 in zip(s1_matched, s2_matched, strict=True)) / 2
    jaro = (
        matches / len(s1)
        + matches / len(s2)
        + (matches - transpositions) / matches
    ) / 3
    prefix = 0
    for c1, c2 in zip(s1[:4], s2[:4], strict=False):
        if c1 != c2:
            break
        prefix += 1
    return jaro + prefix * prefix_scale * (1 - jaro)


def optional_embedding_metrics(
    prediction: str,
    reference: str,
    *,
    bertscore_model: str | None = None,
    bertscore_lang: str = "en",
) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "bertscore_precision": None,
        "bertscore_recall": None,
        "bertscore_f1": None,
        "frugalscore": None,
    }
    metrics.update(
        _bertscore(
            prediction,
            reference,
            model_type=bertscore_model,
            lang=bertscore_lang,
        )
    )
    metrics.update(_frugalscore(prediction, reference))
    return metrics


def _bertscore(
    prediction: str,
    reference: str,
    *,
    model_type: str | None,
    lang: str,
) -> dict[str, Any]:
    if importlib.util.find_spec("bert_score") is None:
        return {"bertscore_status": "unavailable"}
    try:
        from bert_score import score

        precision, recall, f1 = score(
            [prediction],
            [reference],
            model_type=model_type,
            lang=lang,
            verbose=False,
            rescale_with_baseline=False,
        )
        return {
            "bertscore_precision": float(precision[0]),
            "bertscore_recall": float(recall[0]),
            "bertscore_f1": float(f1[0]),
            "bertscore_status": "ok",
        }
    except Exception as exc:  # pragma: no cover - optional dependency path
        return {"bertscore_status": f"error: {type(exc).__name__}: {str(exc)[:120]}"}


def _frugalscore(prediction: str, reference: str) -> dict[str, Any]:
    if importlib.util.find_spec("evaluate") is None:
        return {"frugalscore_status": "unavailable"}
    try:
        import evaluate

        metric = evaluate.load("frugalscore")
        result = metric.compute(predictions=[prediction], references=[reference])
        score = _first_numeric_value(result)
        return {"frugalscore": score, "frugalscore_status": "ok" if score is not None else "empty"}
    except Exception as exc:  # pragma: no cover - optional dependency path
        return {"frugalscore_status": f"error: {type(exc).__name__}: {str(exc)[:120]}"}


def _first_numeric_value(value: Any) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, list):
        for item in value:
            found = _first_numeric_value(item)
            if found is not None:
                return found
    if isinstance(value, dict):
        for key in ("frugalscore", "score", "scores", "f1"):
            if key in value:
                found = _first_numeric_value(value[key])
                if found is not None:
                    return found
        for item in value.values():
            found = _first_numeric_value(item)
            if found is not None:
                return found
    return None


def _ngrams(tokens: list[str], n: int) -> list[tuple[str, ...]]:
    if n <= 0 or len(tokens) < n:
        return []
    return [tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


def _overlap_scores(
    pred: Counter[tuple[str, ...]],
    ref: Counter[tuple[str, ...]],
) -> dict[str, float]:
    if not pred and not ref:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    if not pred or not ref:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    overlap = sum(min(count, ref[gram]) for gram, count in pred.items())
    precision = overlap / sum(pred.values())
    recall = overlap / sum(ref.values())
    return {"precision": precision, "recall": recall, "f1": _f1(precision, recall)}


def _f1(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _lcs_len(a: list[str], b: list[str]) -> int:
    previous = [0] * (len(b) + 1)
    for token_a in a:
        current = [0]
        for j, token_b in enumerate(b, start=1):
            if token_a == token_b:
                current.append(previous[j - 1] + 1)
            else:
                current.append(max(previous[j], current[-1]))
        previous = current
    return previous[-1]


def _exact_unigram_alignment(
    pred_tokens: list[str],
    ref_tokens: list[str],
) -> list[tuple[int, int]]:
    used_ref: set[int] = set()
    matches: list[tuple[int, int]] = []
    for i, token in enumerate(pred_tokens):
        for j, ref_token in enumerate(ref_tokens):
            if j in used_ref or token != ref_token:
                continue
            used_ref.add(j)
            matches.append((i, j))
            break
    return matches


def _alignment_chunks(matches: list[tuple[int, int]]) -> int:
    if not matches:
        return 0
    chunks = 1
    ordered = sorted(matches)
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if current[0] != previous[0] + 1 or current[1] != previous[1] + 1:
            chunks += 1
    return chunks
