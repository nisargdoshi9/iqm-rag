"""Run the evaluation set against the bot and save the results (FR-9).

    python scripts/evaluate.py --split dev --dry-run     # plan only: call counts, rough cost, checks. Makes NO API calls
    python scripts/evaluate.py --split dev --yes         # run the 9 dev questions (model calls; costs a few cents)
    python scripts/evaluate.py --split test --yes        # the final run: needs a verified question set, once per dataset version
    python scripts/evaluate.py --split holdout --yes     # the held-out questions (data/evaluation/holdout.jsonl); same rules as test
    python scripts/evaluate.py --rebuild data/evaluation/results/<run-id>   # rebuild summaries and review.csv; no API calls
    python scripts/evaluate.py --rejudge data/evaluation/results/<run-id> --yes   # judge the saved answers again (judge calls only)

Without --dry-run the script only calls the API when you also pass --yes. Each question is asked exactly once.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from iqm_rag import config
from iqm_rag.evaluation import runner
from iqm_rag.evaluation.dataset import load_questions, validate_dataset
from iqm_rag.ingestion.chunking import CHUNKS_JSONL
from iqm_rag.scraping.normalization import read_jsonl


def print_plan(plan: dict, problems: list[str], previous: list[str]) -> None:
    calls, estimate, coverage = plan["calls"], plan["rough_estimate"], plan["evidence_in_chunks"]
    cost = "unknown (a model has no listed price)" if estimate["cost_usd"] is None else f"about ${estimate['cost_usd']}"
    print("Evaluation plan (no API calls were made while planning)")
    print(f"  Questions: {plan['questions']} {plan['by_split']}  statuses: {plan['statuses']}")
    print(f"  Calls if you run it:  answers {calls['answer']} ({plan['models']['chat']}) · rewrites {calls['rewrite']} · "
          f"query embeddings {calls['embedding']} · judge up to {calls['judge_at_most']} ({plan['models']['judge']})")
    print(f"  Rough estimate: about {estimate['tokens']:,} tokens, {cost} (planning figures; the run reports actuals)")
    print(f"  Evidence quotes found in the chunks: {coverage['found']}/{coverage['of']}" + (f"  MISSING for {coverage['missing']}" if coverage["missing"] else ""))
    print(f"  Freeze check: {'ok' if not problems else problems[0]}")
    print(f"  Completed test run for this dataset: {previous or 'none'}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--split", choices=runner.SPLITS, default="dev")
    parser.add_argument("--ids", nargs="+", help="only these question ids")
    parser.add_argument("--limit", type=int, help="only the first N selected questions")
    parser.add_argument("--dry-run", action="store_true", help="plan only; no API calls")
    parser.add_argument("--yes", action="store_true", help="confirm that the model calls may be made")
    parser.add_argument("--no-judge", action="store_true", help="skip the LLM judge (retrieval, abstention and citation metrics only)")
    parser.add_argument("--allow-unverified", action="store_true", help="run the test or holdout split on a question set that is not verified")
    parser.add_argument("--allow-repeat-test", action="store_true", help="run a frozen split (test or holdout) again for the same dataset version")
    parser.add_argument("--results-dir", type=Path, default=runner.RESULTS_DIR)
    parser.add_argument("--rebuild", type=Path, help="rebuild summaries and review.csv from a saved run; no API calls")
    parser.add_argument("--rejudge", type=Path, help="judge the saved answers of a run again with the current judge (needs --yes)")
    args = parser.parse_args(argv)
    if args.rejudge:
        return rejudge_command(args)
    if args.rebuild:
        summary = runner.rebuild_outputs(args.rebuild)
        print(f"Rebuilt outputs in {args.rebuild} ({summary['questions']} questions).")
        return 0
    files = runner.question_files(args.split)
    articles = read_jsonl(config.PROCESSED_ARTICLES_JSONL)
    questions = [q for path in files for q in load_questions(path)]
    errors = [e for path in files for e in validate_dataset(load_questions(path), articles)]
    if errors:
        print("The evaluation set does not validate:\n  " + "\n  ".join(errors[:10]), file=sys.stderr)
        return 1
    try:
        selected = runner.select_questions(questions, args.split, args.ids, args.limit)
    except ValueError as exc:
        print(f"Evaluation stopped: {exc}", file=sys.stderr)
        return 1
    digest = runner.dataset_hash(files)
    plan = runner.plan_run(selected, read_jsonl(CHUNKS_JSONL), not args.no_judge, config.chat_model(), config.judge_model())
    problems = runner.check_freeze(selected, args.allow_unverified)
    previous = runner.previous_test_runs(args.results_dir, digest) if any(q["split"] in runner.FROZEN_SPLITS for q in selected) else []
    print_plan(plan, problems, previous)
    if args.dry_run:
        return 0
    if problems or (previous and not args.allow_repeat_test):
        print("\nNot run: " + (problems[0] if problems else f"a frozen split was already run for this dataset ({previous}); use --allow-repeat-test only for a new, recorded reason."), file=sys.stderr)
        return 1
    if not args.yes:
        print("\nNot run. Add --yes to make these calls.")
        return 0
    return execute(args, selected, digest)


def execute(args, selected: list[dict], digest: str) -> int:
    from iqm_rag.evaluation.judge import default_judge
    from iqm_rag.generation.chain import default_chain
    from iqm_rag.observability.tracing import flush_traces

    try:
        chain = default_chain()
        judge = None if args.no_judge else default_judge()
    except RuntimeError as exc:
        print(f"Evaluation stopped: {exc}", file=sys.stderr)
        return 1
    run_id = runner.make_run_id(args.split)
    setup = {"split": args.split, "dataset_hash": digest, "dataset_path": [str(path) for path in runner.question_files(args.split)], "allow_unverified": args.allow_unverified}
    progress = lambda i, n, r: print(f"[{i}/{n}] {r['id']:9} {r.get('status', 'ERROR'):13} {r.get('outcome', r.get('error', ''))}")  # noqa: E731
    summary = runner.run_evaluation(selected, chain, judge, run_id, args.results_dir, setup, on_progress=progress)
    flush_traces()
    print(json.dumps({"run_dir": str(args.results_dir / run_id), "questions": summary["questions"], "errors": summary["errors"],
                      "passed": summary["abstention"]["passed"], "end_to_end_correct": summary["generation"]["end_to_end_correct"]}, indent=2))
    return 0



def rejudge_command(args) -> int:
    from iqm_rag.evaluation.judge import default_judge
    from iqm_rag.observability.tracing import flush_traces

    plan = runner.plan_rejudge(args.rejudge)
    print(f"Re-judge plan: {plan['judge_calls']} judge call(s) for {plan['records']} saved answers; no answer is generated again. Judge: {config.judge_model()}")
    if args.dry_run or not args.yes:
        print("Not run." + ("" if args.dry_run else " Add --yes to make these calls."))
        return 0
    try:
        judge = default_judge()
    except RuntimeError as exc:
        print(f"Evaluation stopped: {exc}", file=sys.stderr)
        return 1
    chunks = {chunk["chunk_id"]: chunk for chunk in read_jsonl(CHUNKS_JSONL)}
    progress = lambda i, n, r: print(f"[{i}/{n}] {r['id']:9} judge: {(r.get('judge') or {}).get('facts_covered', '-')}/{(r.get('judge') or {}).get('facts_total', '-')}")  # noqa: E731
    new_dir, summary = runner.rejudge(args.rejudge, judge, chunks, on_progress=progress)
    flush_traces()
    print(json.dumps({"run_dir": str(new_dir), "generation": summary["generation"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
