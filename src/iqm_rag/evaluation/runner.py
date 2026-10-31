"""Run the evaluation set against the bot and save the results (FR-9).

Every question goes through the same chain as the chat page, once, with its scripted history. Nothing is retried or polled.
The run is saved as raw per-question records, a side-by-side CSV for manual review, a JSON summary and a Markdown summary.
Guards keep the method honest: the final test split must be on a verified question set, and it is run once per dataset version.
"""

import csv
import hashlib
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Sequence

from iqm_rag import config
from iqm_rag.evaluation import metrics
from iqm_rag.evaluation.dataset import QUESTIONS_PATH
from iqm_rag.evaluation.judge import JUDGE_PROMPT_VERSION, Judge, should_judge
from iqm_rag.history import messages_from_dicts

RESULTS_DIR = config.EVALUATION_DIR / "results"
SPLITS = ("dev", "test", "all")
ROUGH_TOKENS = {"answer": (3000, 150), "rewrite": (480, 15), "judge": (3600, 350), "embedding": 15}  # planning figures from a measured trace
MANUAL_COLUMNS = ("manual_verdict", "manual_notes")
REVIEW_COLUMNS = ("id", "split", "category", "question", "history", "expected_answer", "key_facts", "bot_answer", "bot_status", "outcome",
                  "cited_urls", "expected_urls", "search_query", "evidence_rank", "top_retrieved", "judge_facts", "judge_fact_notes",
                  "judge_unsupported", "judge_claims", "judge_comment", "auto_pass", *MANUAL_COLUMNS, "trace_id", "error")


# --- selection, hashing, planning --------------------------------------------------------------------


def select_questions(questions: Sequence[dict], split: str = "all", ids: Optional[Sequence[str]] = None, limit: Optional[int] = None) -> list[dict]:
    if split not in SPLITS:
        raise ValueError(f"split must be one of {SPLITS}, got {split!r}")
    if ids:
        known = {q["id"] for q in questions}
        unknown = [i for i in ids if i not in known]
        if unknown:
            raise ValueError(f"Unknown question ids: {unknown}")
    chosen = [q for q in questions if (split == "all" or q["split"] == split) and (not ids or q["id"] in ids)]
    return chosen[:limit] if limit else chosen


def dataset_hash(path: Path = QUESTIONS_PATH) -> str:
    """A hash of the questions' content. The `status` field is left out, so verifying the set does not change its identity."""
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for row in rows:
        row.pop("status", None)
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _evidence_coverage(questions: Sequence[dict], chunks: Sequence[dict]) -> dict:
    found = total = 0
    missing: list[str] = []
    for question in questions:
        for rank in metrics.evidence_ranks(question, chunks):
            total += 1
            found += rank is not None
            if rank is None and question["id"] not in missing:
                missing.append(question["id"])
    return {"found": found, "of": total, "missing": missing}


def plan_run(questions: Sequence[dict], chunks: Sequence[dict], judge_enabled: bool = True, chat_model: str = config.DEFAULT_CHAT_MODEL,
             judge_model: str = config.DEFAULT_JUDGE_MODEL) -> dict:
    """What a run would do and roughly cost, worked out locally. This makes no API call."""
    n = len(questions)
    rewrites = sum(1 for q in questions if q["history"])
    judges = sum(1 for q in questions if not q["should_abstain"]) if judge_enabled else 0
    in_chat = n * ROUGH_TOKENS["answer"][0] + rewrites * ROUGH_TOKENS["rewrite"][0]
    out_chat = n * ROUGH_TOKENS["answer"][1] + rewrites * ROUGH_TOKENS["rewrite"][1]
    parts = [metrics.cost_usd(chat_model, in_chat, out_chat), metrics.cost_usd("text-embedding-3-large", n * ROUGH_TOKENS["embedding"], 0)]
    if judges:
        parts.append(metrics.cost_usd(judge_model, judges * ROUGH_TOKENS["judge"][0], judges * ROUGH_TOKENS["judge"][1]))
    tokens = in_chat + out_chat + n * ROUGH_TOKENS["embedding"] + judges * sum(ROUGH_TOKENS["judge"][:2])
    return {"api_calls_made": 0, "questions": n, "by_split": {s: sum(1 for q in questions if q["split"] == s) for s in ("dev", "test") if any(q["split"] == s for q in questions)},
            "calls": {"answer": n, "rewrite": rewrites, "embedding": n, "judge_at_most": judges},
            "rough_estimate": {"tokens": tokens, "cost_usd": None if None in parts else round(sum(parts), 4)},
            "evidence_in_chunks": _evidence_coverage(questions, chunks), "statuses": _count(q["status"] for q in questions),
            "models": {"chat": chat_model, "judge": judge_model if judge_enabled else None}}


def _count(values) -> dict:
    counts: dict = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def check_freeze(questions: Sequence[dict], allow_unverified: bool) -> list[str]:
    """The final test split must be run on verified questions; the dev split may be run on drafts while debugging."""
    unverified = [q["id"] for q in questions if q["split"] == "test" and q["status"] != "verified"]
    if unverified and not allow_unverified:
        return [f"{len(unverified)} test question(s) are not verified yet ({', '.join(unverified[:5])}...). Review and verify the set before the final run."]
    return []


def previous_test_runs(results_dir: Path, current_hash: str) -> list[str]:
    """Completed runs that included the test split for this exact dataset: the test split is used once per dataset version."""
    found = []
    for config_file in sorted(results_dir.glob("*/config.json")) if results_dir.exists() else []:
        setup = json.loads(config_file.read_text())
        if setup.get("completed") and setup.get("includes_test") and setup.get("dataset_hash") == current_hash and not setup.get("rejudged_from"):
            found.append(config_file.parent.name)
    return found


# --- one question ------------------------------------------------------------------------------------


def _retrieved(answer) -> list[dict]:
    return [{"rank": hit.rank, "similarity": round(hit.similarity, 4), "chunk_id": hit.chunk["chunk_id"], "header": hit.chunk["context_header"],
             "url": hit.chunk["article_url"]} for hit in answer.retrieval.hits]


def _usage_numbers(usage) -> tuple[Optional[int], Optional[int]]:
    return (None, None) if usage is None else (usage.input_tokens, usage.output_tokens)


def _tokens_and_cost(answer, judge) -> tuple[dict, Optional[float]]:
    chat_in, chat_out = _usage_numbers(answer.usage)
    rewrite_in, rewrite_out = _usage_numbers(answer.rewrite.usage)
    judge_in, judge_out = _usage_numbers(None if judge is None else judge.usage)
    embed = answer.retrieval.embedding_tokens
    parts = [(answer.model, chat_in, chat_out), ("text-embedding-3-large", embed, 0)]
    if rewrite_in is not None:
        parts.append((answer.rewrite.model, rewrite_in, rewrite_out))
    if judge_in is not None:
        parts.append((judge.model, judge_in, judge_out))
    costs = [metrics.cost_usd(model, i, o) for model, i, o in parts if i is not None]
    total = sum(v for v in (chat_in, chat_out, rewrite_in, rewrite_out, embed, judge_in, judge_out) if v is not None)
    tokens = {"chat_in": chat_in, "chat_out": chat_out, "rewrite_in": rewrite_in, "rewrite_out": rewrite_out, "embed": embed,
              "judge_in": judge_in, "judge_out": judge_out, "total": total}
    return tokens, (None if (not costs or None in costs) else round(sum(costs), 6))


def _base_record(question: dict) -> dict:
    return {"id": question["id"], "split": question["split"], "category": question["category"], "question": question["question"],
            "history": question["history"], "expected_answer": question["expected_answer"], "key_facts": question["key_facts"],
            "expected_source_urls": question["expected_source_urls"], "should_abstain": question["should_abstain"]}


def _scored_record(question: dict, answer, judge, wall_s: float) -> dict:
    chunks = [hit.chunk for hit in answer.retrieval.hits]
    ranks = metrics.evidence_ranks(question, chunks)
    cited = [c.url for c in answer.citations]
    tokens, cost = _tokens_and_cost(answer, judge)
    return {**_base_record(question), "status": answer.status, "outcome": metrics.status_outcome(question, answer.status), "answer": answer.text,
            "cited_urls": cited, "search_query": answer.rewrite.query, "rewritten": answer.rewrite.rewritten, "retrieved": _retrieved(answer),
            "evidence_ranks": ranks, "recall_at": {str(k): metrics.recall_at(ranks, k) for k in metrics.RETRIEVAL_KS},
            "rr": metrics.reciprocal_rank(ranks), "article_rank": metrics.article_rank(question, chunks),
            "citation": metrics.citation_scores(question, cited), "judge": None if judge is None else judge.to_dict(),
            "wall_s": round(wall_s, 3), "latency_ms": {"rewrite": round(answer.rewrite.ms, 1), "embed": round(answer.retrieval.embed_ms, 1),
                                                      "search": round(answer.retrieval.search_ms, 1), "llm": round(answer.llm_ms, 1)},
            "tokens": tokens, "cost_usd": cost, "trace_id": answer.trace_id, "warnings": list(answer.warnings),
            "llm_attempts": answer.llm_attempts, "error": None}


def evaluate_question(question: dict, chain, judge: Optional[Judge], run_id: str) -> dict:
    """Ask one question once and score it. A failure is recorded in the record, not raised, so the batch can finish."""
    tags = ("eval", f"run:{run_id}", f"q:{question['id']}", f"split:{question['split']}", f"category:{question['category']}")
    metadata = {"question_id": question["id"], "category": question["category"], "split": question["split"], "run_id": run_id}
    started = time.perf_counter()
    try:
        answer = chain.answer(question["question"], messages_from_dicts(question["history"]), session_id=f"{run_id}:{question['id']}",
                              tags=tags, metadata=metadata)
    except Exception as exc:  # the batch boundary: record what failed and carry on with the next question
        return {**_base_record(question), "error": f"{type(exc).__name__}: {exc}"}
    wall_s = time.perf_counter() - started
    verdict = judge.evaluate(question, answer, tags=tags) if judge is not None and should_judge(question, answer) else None
    return _scored_record(question, answer, verdict, wall_s)


# --- outputs -----------------------------------------------------------------------------------------


def _list(items: Sequence[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _review_row(record: dict) -> dict:
    row = {name: "" for name in REVIEW_COLUMNS}
    row.update({"id": record["id"], "split": record["split"], "category": record["category"], "question": record["question"],
                "history": "\n".join(f"{m['role']}: {m['content']}" for m in record["history"]), "expected_answer": record["expected_answer"],
                "key_facts": _list(record["key_facts"]), "expected_urls": "\n".join(record["expected_source_urls"]), "error": record.get("error") or ""})
    if record.get("error"):
        return row
    judge = record.get("judge") or {}
    ranks = record["evidence_ranks"]
    notes = [f"{'YES' if c['covered'] else 'NO '} | {c['fact']} | {c['note']}" for c in judge.get("fact_checks", [])]
    row.update({"bot_answer": record["answer"], "bot_status": record["status"], "outcome": record["outcome"], "cited_urls": "\n".join(record["cited_urls"]),
                "search_query": record["search_query"], "trace_id": record["trace_id"],
                "evidence_rank": ", ".join("not retrieved" if r is None else str(r) for r in ranks) if ranks else "n/a",
                "top_retrieved": "\n".join(f"{h['rank']}. {h['header']}" for h in record["retrieved"][:3]),
                "judge_facts": "" if judge.get("facts_covered") is None else f"{judge['facts_covered']}/{judge['facts_total']}",
                "judge_fact_notes": "\n".join(notes), "judge_unsupported": "\n".join(judge.get("unsupported_claims", [])),
                "judge_claims": "\n".join(f"{'OK ' if c['supported'] else 'NO '} doc {c['supporting_doc']} | {c['claim']}" for c in judge.get("claims", [])),
                "judge_comment": judge.get("error") or judge.get("comment", ""), "auto_pass": "yes" if _auto_pass(record) else "no"})
    return row


def _auto_pass(record: dict) -> bool:
    judge = record.get("judge")
    fully = judge is None or (judge.get("facts_covered") is not None and judge["facts_covered"] == judge["facts_total"] and judge["faithful"])
    return record["outcome"] in metrics.OUTCOME_PASSES and record["citation"]["clean"] and fully


def _problems(record: dict) -> list[str]:
    if record.get("error"):
        return [f"error: {record['error']}"]
    found = []
    if record["outcome"] not in metrics.OUTCOME_PASSES:
        found.append(f"outcome={record['outcome']}")
    if any(rank is None for rank in record["evidence_ranks"]):
        found.append("evidence not retrieved")
    if not record["citation"]["clean"]:
        found.append(f"wrong citation: {', '.join(record['citation']['wrong'])}")
    judge = record.get("judge")
    if judge and judge.get("error"):
        found.append(f"judge error: {judge['error']}")
    elif judge and judge["facts_covered"] != judge["facts_total"]:
        found.append(f"facts covered {judge['facts_covered']}/{judge['facts_total']}")
    if judge and judge.get("faithful") is False:
        found.append("unsupported claims")
    return found


def _fmt(r: dict) -> str:
    return f"{r['count']}/{r['of']}" + ("" if r["percent"] is None else f" ({r['percent']}%)")


def summary_markdown(summary: dict, groups: dict, setup: dict, records: Sequence[dict]) -> str:
    ret, gen, cit, ab, ops = summary["retrieval"], summary["generation"], summary["citation"], summary["abstention"], summary["operational"]
    lines = [f"# Evaluation run {setup.get('run_id', '')}", "",
             f"- Split: {setup.get('split')} · questions: {summary['questions']} (errors: {summary['errors']}) · dataset {str(setup.get('dataset_hash', ''))[:12]} · statuses {setup.get('dataset_statuses')}",
             f"- Models: chat {setup.get('chat_model')}, rewrite {setup.get('rewrite_model')}, embedding {setup.get('embedding_model')}, judge {setup.get('judge_model')} "
             f"(judge prompt {setup.get('judge_prompt_version')}) · answer prompt {setup.get('prompt_version')} · top_k {setup.get('top_k')} · index chunks {setup.get('index_chunks')}",
             f"- Git commit {setup.get('git_commit')} · tracing {'on' if setup.get('tracing') else 'off'}", "",
             "## Headline", "", "| Measure | Result |", "|---|---|",
             f"| Right answer or right abstention | {_fmt(ab['passed'])} |", f"| Answerable questions answered | {_fmt(ab['answered_when_answerable'])} |",
             f"| End-to-end correct (answered with every key fact) | {_fmt(gen['end_to_end_correct'])} |", "",
             f"## Retrieval (answerable questions, {ret['evidence_items']} required evidence items)", "",
             "| Recall@1 | Recall@3 | Recall@5 | Recall@8 | MRR | Right article retrieved |", "|---|---|---|---|---|---|",
             f"| {_fmt(ret['recall@1'])} | {_fmt(ret['recall@3'])} | {_fmt(ret['recall@5'])} | {_fmt(ret['recall@8'])} | {ret['mrr']} | {_fmt(ret['article_hit'])} |", "",
             "## Abstention", "", "| Measure | Result |", "|---|---|", f"| Correct abstentions (should abstain, said not covered) | {_fmt(ab['correct_abstentions'])} |",
             f"| Outcomes | {summary['outcomes']} |", "",
             "## Citations", "", f"- Mean precision {cit['mean_precision']} · mean recall {cit['mean_recall']} · no wrong citation {_fmt(cit['no_wrong_citation'])}", "",
             "## Answer quality (LLM judge, answered answerable questions)", "",
             f"- Judged {gen['judged']} (judge errors {gen['judge_errors']}) · every key fact covered {_fmt(gen['all_facts_covered'])} · mean fact coverage {gen['mean_fact_coverage']} · "
             f"every claim supported {_fmt(gen['faithful'])} · claims {gen['claims']['total']} (supported {gen['claims']['supported']}, quote found in the named document {gen['claims']['quote_found']})",
             "- The judge is a model of the same family as the answerer; treat it as a guide and use the manual columns in review.csv to check it.", "",
             "## Operational", "", f"- Wall time per question (seconds): {ops['wall_s']}",
             f"- Tokens {ops['tokens_total']} · estimated cost {ops['estimated_cost_usd']} USD ({ops['estimated_cost_per_question_usd']} per question). "
             f"This is an estimate from stated prices ({metrics.PRICES_AS_OF}), not a billed amount.", "", "## Per category", "",
             "| Category | n | Passed | Recall@8 | End-to-end correct |", "|---|---|---|---|---|"]
    lines += [f"| {name} | {g['n']} | {_fmt(g['passed'])} | {_fmt(g['recall@8'])} | {_fmt(g['end_to_end_correct'])} |" for name, g in groups.items()]
    lines += ["", "## Failures", ""]
    failures = [(r["id"], r["category"], _problems(r)) for r in records if _problems(r)]
    lines += [f"- {qid} [{category}]: {'; '.join(problems)}" for qid, category, problems in failures] or ["- none"]
    return "\n".join(lines) + "\n"


def write_outputs(run_dir: Path, records: Sequence[dict], setup: dict) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    summary, groups = metrics.aggregate(records), metrics.group_summary(records, "category")
    (run_dir / "results.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    with (run_dir / "review.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        writer.writerows(_review_row(r) for r in records)
    (run_dir / "summary.json").write_text(json.dumps({"summary": summary, "by_category": groups}, indent=2, ensure_ascii=False), encoding="utf-8")
    (run_dir / "summary.md").write_text(summary_markdown(summary, groups, setup, records), encoding="utf-8")
    return summary


def rebuild_outputs(run_dir: Path) -> dict:
    """Recreate the summaries and the review CSV from saved results; no model is called."""
    records = [json.loads(line) for line in (run_dir / "results.jsonl").read_text(encoding="utf-8").splitlines() if line]
    setup = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    return write_outputs(run_dir, records, setup)


def git_commit() -> Optional[str]:
    try:
        result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=config.ROOT_DIR, capture_output=True, text=True, timeout=5)
        return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def make_run_id(split: str, now: Optional[datetime] = None) -> str:
    return f"{(now or datetime.now(timezone.utc)):%Y%m%d-%H%M%S}-{split}"


def run_evaluation(questions: Sequence[dict], chain, judge: Optional[Judge], run_id: str, results_dir: Path, setup: dict,
                   on_progress: Optional[Callable[[int, int, dict], None]] = None) -> dict:
    """Ask every question once, in order, then save everything. Returns the summary."""
    run_dir = results_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    describe = getattr(chain, "describe", lambda: {})()
    full_setup = {**setup, **describe, "run_id": run_id, "created_at": datetime.now(timezone.utc).isoformat(), "git_commit": git_commit(),
                  "judge_model": None if judge is None else judge.model, "judge_prompt_version": None if judge is None else JUDGE_PROMPT_VERSION,
                  "dataset_statuses": _count(q["status"] for q in questions), "includes_test": any(q["split"] == "test" for q in questions),
                  "question_ids": [q["id"] for q in questions], "completed": False}
    (run_dir / "config.json").write_text(json.dumps(full_setup, indent=2), encoding="utf-8")
    records = []
    for index, question in enumerate(questions, start=1):
        records.append(evaluate_question(question, chain, judge, run_id))
        if on_progress:
            on_progress(index, len(questions), records[-1])
    summary = write_outputs(run_dir, records, full_setup)
    (run_dir / "config.json").write_text(json.dumps({**full_setup, "completed": True}, indent=2), encoding="utf-8")
    return summary


# --- re-judging saved answers -----------------------------------------------------------------------


def _needs_judge(record: dict) -> bool:
    return not record.get("error") and not record["should_abstain"] and record["status"] == "answered"


def plan_rejudge(run_dir: Path) -> dict:
    records = [json.loads(line) for line in (run_dir / "results.jsonl").read_text(encoding="utf-8").splitlines() if line]
    return {"judge_calls": sum(1 for r in records if _needs_judge(r)), "records": len(records)}


def _swap_judge(record: dict, result) -> dict:
    """Replace the judge's result and its share of the tokens and cost; the answer's own usage is unchanged."""
    old = record["judge"] or {}
    old_usage = old.get("usage") or {}
    tokens = dict(record["tokens"])
    tokens["total"] += (result.usage.total_tokens or 0) - (old_usage.get("total_tokens") or 0) if result.usage else -(old_usage.get("total_tokens") or 0)
    tokens["judge_in"], tokens["judge_out"] = (result.usage.input_tokens, result.usage.output_tokens) if result.usage else (None, None)
    old_cost = metrics.cost_usd(old.get("model", ""), old_usage.get("input_tokens"), old_usage.get("output_tokens")) if old_usage else 0.0
    new_cost = metrics.cost_usd(result.model, result.usage.input_tokens, result.usage.output_tokens) if result.usage else 0.0
    cost = None if (record["cost_usd"] is None or old_cost is None or new_cost is None) else round(record["cost_usd"] - old_cost + new_cost, 6)
    return {**record, "judge": result.to_dict(), "tokens": tokens, "cost_usd": cost}


def rejudge(run_dir: Path, judge: Judge, chunks_by_id: dict, on_progress: Optional[Callable[[int, int, dict], None]] = None) -> tuple[Path, dict]:
    """Judge the saved answers of a run again with the current judge, into a new run directory. No answer is generated again."""
    from types import SimpleNamespace

    from iqm_rag.generation.context import build_context_docs
    from iqm_rag.retrieval.retriever import RetrievedChunk

    records = [json.loads(line) for line in (run_dir / "results.jsonl").read_text(encoding="utf-8").splitlines() if line]
    setup = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    updated = []
    for index, record in enumerate(records, start=1):
        if _needs_judge(record):
            hits = [RetrievedChunk(h["rank"], 1 - h["similarity"], chunks_by_id[h["chunk_id"]]) for h in record["retrieved"]]
            answer = SimpleNamespace(docs=build_context_docs(hits), text=record["answer"], status=record["status"])
            record = _swap_judge(record, judge.evaluate(record, answer, tags=("rejudge", f"from:{setup['run_id']}")))
        updated.append(record)
        if on_progress:
            on_progress(index, len(records), record)
    new_id = f"{setup['run_id']}-rejudge-{JUDGE_PROMPT_VERSION}"
    new_setup = {**setup, "run_id": new_id, "rejudged_from": setup["run_id"], "judge_model": judge.model, "judge_prompt_version": JUDGE_PROMPT_VERSION,
                 "created_at": datetime.now(timezone.utc).isoformat(), "git_commit": git_commit(), "completed": False}
    new_dir = run_dir.parent / new_id
    new_dir.mkdir(parents=True, exist_ok=True)
    summary = write_outputs(new_dir, updated, new_setup)
    (new_dir / "config.json").write_text(json.dumps({**new_setup, "completed": True}, indent=2), encoding="utf-8")
    return new_dir, summary
