"""Evaluation metric calculations (FR-9). Pure functions over plain records; no model calls and no network.

Retrieval is scored by whether a retrieved chunk from the right article contains the evidence quote; abstention and citations
are scored deterministically from the answer's status and cited URLs; answer correctness and faithfulness come from an LLM
judge (see judge.py). Counts are kept raw next to percentages because the set is small.
"""

import math
import statistics
from collections import Counter
from typing import Optional, Sequence

from iqm_rag.evaluation.dataset import normalize_text

RETRIEVAL_KS = (1, 3, 5, 8)
OUTCOMES = ("answered", "correct_abstention", "wrongful_abstention", "over_clarified", "invented_answer", "clarified_instead", "small_talk")
OUTCOME_PASSES = {"answered", "correct_abstention"}
PRICES_AS_OF = "2026-10-31; the gpt-4.1-mini figures reproduce LangSmith's own cost estimate for the same calls"
PRICES_PER_MILLION = {  # US dollars per million tokens; published prices, which can change
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    "text-embedding-3-large": {"input": 0.13, "output": 0.0},
}
TOKENS_PER_MILLION = 1_000_000


def ratio(count: int, of: int) -> dict:
    return {"count": count, "of": of, "percent": round(100 * count / of, 1) if of else None}


# --- retrieval --------------------------------------------------------------------------------------


def evidence_ranks(question: dict, chunks: Sequence[dict]) -> list[Optional[int]]:
    """For each required evidence item, the 1-based rank of the first retrieved chunk from the same article that contains its quote."""
    ranks: list[Optional[int]] = []
    for item in question["evidence"]:
        if not item.get("required"):
            continue
        quote = normalize_text(item["quote"])
        ranks.append(next((rank for rank, chunk in enumerate(chunks, start=1)
                           if chunk["article_id"] == item["article_id"] and quote in normalize_text(chunk["text"])), None))
    return ranks


def recall_at(ranks: Sequence[Optional[int]], k: int) -> Optional[float]:
    if not ranks:
        return None
    return sum(1 for rank in ranks if rank is not None and rank <= k) / len(ranks)


def reciprocal_rank(ranks: Sequence[Optional[int]]) -> Optional[float]:
    if not ranks:
        return None
    found = [rank for rank in ranks if rank is not None]
    return 1 / min(found) if found else 0.0


def article_rank(question: dict, chunks: Sequence[dict]) -> Optional[int]:
    expected = set(question["expected_source_urls"])
    return next((rank for rank, chunk in enumerate(chunks, start=1) if chunk["article_url"] in expected), None)


# --- abstention and citations ---------------------------------------------------------------------


def status_outcome(question: dict, status: str) -> str:
    """Name what the bot did relative to what it should have done."""
    if question["should_abstain"]:
        return {"not_covered": "correct_abstention", "answered": "invented_answer", "clarification": "clarified_instead", "smalltalk": "small_talk"}[status]
    return {"answered": "answered", "not_covered": "wrongful_abstention", "clarification": "over_clarified", "smalltalk": "small_talk"}[status]


def citation_scores(question: dict, cited_urls: Sequence[str]) -> dict:
    cited = list(dict.fromkeys(cited_urls))
    expected = set(question["expected_source_urls"])
    if question["should_abstain"]:
        return {"precision": None, "recall": None, "wrong": cited, "clean": not cited}
    allowed = expected | set(question.get("related_urls") or []) | {item["url"] for item in question["evidence"]}
    wrong = [url for url in cited if url not in allowed]
    precision = None if not cited else sum(1 for url in cited if url in allowed) / len(cited)
    recall = None if not expected else sum(1 for url in expected if url in cited) / len(expected)
    return {"precision": precision, "recall": recall, "wrong": wrong, "clean": not wrong}


# --- statistics and cost --------------------------------------------------------------------------


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile."""
    ordered = sorted(values)
    return ordered[max(1, math.ceil(q / 100 * len(ordered))) - 1]


def describe(values: Sequence[float]) -> dict:
    if not values:
        return {"n": 0, "median": None, "p90": None, "mean": None, "max": None}
    return {"n": len(values), "median": round(statistics.median(values), 3), "p90": round(percentile(values, 90), 3),
            "mean": round(statistics.fmean(values), 3), "max": round(max(values), 3)}


def cost_usd(model: str, input_tokens: Optional[int], output_tokens: Optional[int]) -> Optional[float]:
    """An estimate from the stated prices; None if the model has no listed price or the token counts are unknown."""
    prices = PRICES_PER_MILLION.get(model)
    if prices is None or input_tokens is None or output_tokens is None:
        return None
    return (input_tokens * prices["input"] + output_tokens * prices["output"]) / TOKENS_PER_MILLION


# --- aggregation ----------------------------------------------------------------------------------


def _mean(values: list[float]) -> Optional[float]:
    return round(statistics.fmean(values), 3) if values else None


def _retrieval_summary(answerable: list[dict]) -> dict:
    total = sum(len(r["evidence_ranks"]) for r in answerable)
    summary = {f"recall@{k}": ratio(sum(1 for r in answerable for rank in r["evidence_ranks"] if rank is not None and rank <= k), total)
               for k in RETRIEVAL_KS}
    summary["evidence_items"] = total
    summary["mrr"] = _mean([r["rr"] for r in answerable if r.get("rr") is not None])
    with_sources = [r for r in answerable if "article_rank" in r]
    summary["article_hit"] = ratio(sum(1 for r in with_sources if r["article_rank"] is not None), len(with_sources))
    return summary


def _generation_summary(answerable: list[dict]) -> dict:
    judged = [r for r in answerable if r.get("judge") and r["judge"].get("error") is None and r["judge"].get("facts_covered") is not None]
    full = [r for r in judged if r["judge"]["facts_covered"] == r["judge"]["facts_total"]]
    correct = [r for r in answerable if r["outcome"] == "answered" and r in full]
    claims = [c for r in judged for c in r["judge"].get("claims", [])]
    return {
        "claims": {"total": len(claims), "supported": sum(1 for c in claims if c["supported"]), "quote_found": sum(1 for c in claims if c["quote_found"])},
        "judged": len(judged), "judge_errors": sum(1 for r in answerable if r.get("judge") and r["judge"].get("error")),
        "all_facts_covered": ratio(len(full), len(judged)),
        "mean_fact_coverage": _mean([r["judge"]["facts_covered"] / r["judge"]["facts_total"] for r in judged if r["judge"]["facts_total"]]),
        "faithful": ratio(sum(1 for r in judged if r["judge"]["faithful"] is True), len(judged)),
        "end_to_end_correct": ratio(len(correct), len(answerable)),
    }


def _operational_summary(ok: list[dict]) -> dict:
    costs = [r["cost_usd"] for r in ok if r.get("cost_usd") is not None]
    tokens = [r["tokens"]["total"] for r in ok if r.get("tokens") and r["tokens"].get("total") is not None]
    return {"wall_s": describe([r["wall_s"] for r in ok if r.get("wall_s") is not None]),
            "tokens_total": sum(tokens) if tokens else None, "estimated_cost_usd": round(sum(costs), 4) if costs else None,
            "estimated_cost_per_question_usd": round(sum(costs) / len(costs), 5) if costs else None}


def aggregate(records: Sequence[dict]) -> dict:
    """Summarise a run. Questions that errored are counted and left out of every other figure."""
    ok = [r for r in records if not r.get("error")]
    answerable = [r for r in ok if not r["should_abstain"]]
    abstain = [r for r in ok if r["should_abstain"]]
    outcomes = Counter(r["outcome"] for r in ok)
    return {
        "questions": len(records), "errors": len(records) - len(ok), "answerable": len(answerable), "should_abstain": len(abstain),
        "statuses": dict(Counter(r["status"] for r in ok)), "outcomes": dict(outcomes),
        "abstention": {"passed": ratio(sum(1 for r in ok if r["outcome"] in OUTCOME_PASSES), len(ok)),
                       "answered_when_answerable": ratio(outcomes["answered"], len(answerable)),
                       "correct_abstentions": ratio(outcomes["correct_abstention"], len(abstain))},
        "retrieval": _retrieval_summary(answerable),
        "citation": {"mean_precision": _mean([r["citation"]["precision"] for r in ok if r["citation"]["precision"] is not None]),
                     "mean_recall": _mean([r["citation"]["recall"] for r in answerable if r["citation"]["recall"] is not None]),
                     "no_wrong_citation": ratio(sum(1 for r in ok if r["citation"]["clean"]), len(ok))},
        "generation": _generation_summary(answerable),
        "operational": _operational_summary(ok),
    }


def group_summary(records: Sequence[dict], key: str) -> dict:
    """A short per-group table (for example per category): size, pass count, evidence recall@8 and end-to-end correctness."""
    groups: dict[str, list[dict]] = {}
    for record in records:
        groups.setdefault(str(record[key]), []).append(record)
    table = {}
    for name, members in sorted(groups.items()):
        summary = aggregate(members)
        table[name] = {"n": len(members), "passed": summary["abstention"]["passed"], "recall@8": summary["retrieval"]["recall@8"],
                       "end_to_end_correct": summary["generation"]["end_to_end_correct"]}
    return table
