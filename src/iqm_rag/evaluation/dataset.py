"""Load and validate the evaluation set.

Validation checks that every question is grounded in the cleaned corpus: quotes exist in the cited section,
section hashes still match, and "unanswerable" questions use terms that really are absent from the corpus.
"""

import json
import re
import sys
from pathlib import Path

from iqm_rag import config
from iqm_rag.scraping.normalization import read_jsonl, section_markdown

QUESTIONS_PATH = config.EVALUATION_DIR / "questions.jsonl"
HOLDOUT_PATH = config.EVALUATION_DIR / "holdout.jsonl"  # written after the first test run, so no fix was tuned on it
CATEGORIES = {
    "direct_factual", "procedural", "list_multi_condition", "multi_section", "follow_up",
    "unanswerable", "similar_but_wrong", "table_lookup",
}
SPLITS = {"dev", "test", "holdout"}
MIN_QUESTIONS = 15  # the assignment's minimum
REQUIRED_FIELDS = ("id", "category", "split", "question", "history", "expected_answer", "key_facts",
                   "expected_source_urls", "evidence", "should_abstain")


def load_questions(path: Path = QUESTIONS_PATH) -> list[dict]:
    return read_jsonl(path)


def normalize_text(text: str) -> str:
    """Text as compared when matching quotes: markdown emphasis and code marks removed, whitespace collapsed."""
    return re.sub(r"\s+", " ", re.sub(r"[*`]", "", text)).strip()


_norm = normalize_text


def _evidence_errors(item: dict, articles: dict[str, dict]) -> list[str]:
    article = articles.get(item["article_id"])
    if article is None:
        return [f"article {item['article_id']} not in corpus"]
    sections = [s for s in article["sections"] if s["heading"] == item["section_heading"]]
    if len(sections) != 1:
        return [f"{item['article_id']}: heading {item['section_heading']!r} matches {len(sections)} sections"]
    errors = []
    if item["url"] != article["canonical_url"]:
        errors.append(f"{item['article_id']}: url differs from the corpus")
    if item["section_content_hash"] != sections[0]["content_hash"]:
        errors.append(f"{item['article_id']}: section changed since the question was written")
    if _norm(item["quote"]) not in _norm(section_markdown(sections[0])):
        errors.append(f"{item['article_id']}: quote not found in {item['section_heading']!r}")
    return errors


def _history_errors(question: dict) -> list[str]:
    roles = [turn["role"] for turn in question["history"]]
    if roles != ["user", "assistant"] * (len(roles) // 2):
        return ["history must alternate user, assistant"]
    if (question["category"] == "follow_up") != bool(roles):
        return ["only follow_up questions have history, and every follow_up needs it"]
    return []


def _abstain_errors(question: dict, corpus_text: str) -> list[str]:
    check = question.get("absence_check") or {}
    if question["evidence"] or not check.get("terms"):
        return ["an unanswerable question needs no evidence and a list of absence_check terms"]
    found = [t for t in check["terms"] if re.search(rf"\b{re.escape(t)}\b", corpus_text, re.I)]
    return [f"terms present in the corpus: {found}"] if found else []


def validate_question(question: dict, articles: dict[str, dict], corpus_text: str) -> list[str]:
    errors = [f"missing field {name}" for name in REQUIRED_FIELDS if name not in question]
    if errors:
        return errors
    if question["category"] not in CATEGORIES or question["split"] not in SPLITS:
        errors.append("unknown category or split")
    errors += _history_errors(question)
    if question["should_abstain"]:
        return errors + _abstain_errors(question, corpus_text)
    required = [e["url"] for e in question["evidence"] if e["required"]]
    if not required or required != question["expected_source_urls"] or not question["key_facts"]:
        errors.append("needs required evidence, matching expected_source_urls, and key_facts")
    for item in question["evidence"]:
        errors += _evidence_errors(item, articles)
    return errors


def validate_dataset(questions: list[dict], articles: list[dict]) -> list[str]:
    by_id = {a["article_id"]: a for a in articles}
    corpus_text = "\n".join(a["cleaned_markdown"] for a in articles)
    errors = [] if len(questions) >= MIN_QUESTIONS else [f"fewer than {MIN_QUESTIONS} questions"]
    if len({q.get("id") for q in questions}) != len(questions):
        errors.append("duplicate question ids")
    for question in questions:
        errors += [f"{question.get('id')}: {e}" for e in validate_question(question, by_id, corpus_text)]
    return errors


def main() -> int:
    questions = load_questions()
    errors = validate_dataset(questions, read_jsonl(config.PROCESSED_ARTICLES_JSONL))
    print(json.dumps({"questions": len(questions), "errors": errors}, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
