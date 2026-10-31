"""Tests for the evaluation runner (FR-9). Real chain pieces with fake models; no network."""

import csv
import json
import tempfile
import unittest
from pathlib import Path

import hermetic  # noqa: F401  (keeps tracing off in tests)
from iqm_rag.evaluation import runner
from iqm_rag.evaluation.judge import FactCheck, JudgeVerdict
from test_eval_judge import FakeJudgeLLM
from test_generation import ChainTestCase, FakeLLM, draft
from test_retrieval import CHUNKS

URL = CHUNKS[0]["article_url"]


def eval_question(qid: str = "q1", **overrides) -> dict:
    base = {"id": qid, "category": "direct_factual", "split": "dev", "question": "schedule a report", "history": [],
            "expected_answer": "Use the Reports tab.", "key_facts": ["Use the Reports tab", "Pick a weekly frequency"],
            "expected_source_urls": [URL], "related_urls": [], "should_abstain": False, "status": "verified",
            "evidence": [{"article_id": "1", "url": URL, "section_heading": "B1", "quote": "schedule schedule a report", "required": True}]}
    base.update(overrides)
    return base


def abstain_question(qid: str = "q2") -> dict:
    return eval_question(qid, category="unanswerable", question="tiktok", should_abstain=True, expected_source_urls=[], evidence=[], key_facts=[])


def verdict(*covered: bool) -> JudgeVerdict:
    facts = ["Use the Reports tab", "Pick a weekly frequency"]
    return JudgeVerdict(fact_checks=[FactCheck(fact=f, covered=c, note="n") for f, c in zip(facts, covered)], unsupported_claims=[], comment="none")


class SpyChain:
    def __init__(self, real) -> None:
        self.real, self.calls = real, []

    def answer(self, question, history=(), **kwargs):
        self.calls.append({"question": question, "history": list(history), **kwargs})
        return self.real.answer(question, history, **kwargs)


class ExplodingChain:
    def __init__(self, fail_on: str, real) -> None:
        self.fail_on, self.real = fail_on, real

    def answer(self, question, history=(), **kwargs):
        if question == self.fail_on:
            raise RuntimeError("boom")
        return self.real.answer(question, history, **kwargs)


class SelectionAndPlanTests(unittest.TestCase):
    QUESTIONS = [eval_question("a"), eval_question("b", split="test"), eval_question("c", split="test", history=[{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}]),
                 abstain_question("d")]

    def test_questions_can_be_selected_by_split_ids_and_limit(self):
        self.assertEqual([q["id"] for q in runner.select_questions(self.QUESTIONS, "test")], ["b", "c"])
        self.assertEqual([q["id"] for q in runner.select_questions(self.QUESTIONS, "all", ids=["d", "a"])], ["a", "d"])
        self.assertEqual([q["id"] for q in runner.select_questions(self.QUESTIONS, "all", limit=2)], ["a", "b"])

    def test_an_unknown_id_is_reported(self):
        with self.assertRaisesRegex(ValueError, "zzz"):
            runner.select_questions(self.QUESTIONS, "all", ids=["zzz"])

    def test_the_dataset_hash_changes_when_the_file_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "q.jsonl"
            path.write_text("a\n")
            first = runner.dataset_hash(path)
            path.write_text("b\n")
            self.assertNotEqual(first, runner.dataset_hash(path))
            self.assertEqual(len(first), 64)

    def test_the_plan_counts_calls_without_making_any(self):
        plan = runner.plan_run(self.QUESTIONS, CHUNKS, judge_enabled=True)
        self.assertEqual(plan["api_calls_made"], 0)
        self.assertEqual((plan["calls"]["answer"], plan["calls"]["rewrite"], plan["calls"]["judge_at_most"]), (4, 1, 3))
        self.assertEqual(plan["by_split"], {"dev": 2, "test": 2})
        self.assertGreater(plan["rough_estimate"]["tokens"], 0)
        self.assertIsNotNone(plan["rough_estimate"]["cost_usd"])

    def test_the_plan_without_the_judge_has_no_judge_calls(self):
        self.assertEqual(runner.plan_run(self.QUESTIONS, CHUNKS, judge_enabled=False)["calls"]["judge_at_most"], 0)

    def test_the_plan_checks_that_every_evidence_quote_exists_in_the_chunks(self):
        missing = eval_question("m", evidence=[{"article_id": "1", "url": URL, "quote": "text that is nowhere", "required": True}])
        plan = runner.plan_run([self.QUESTIONS[0], missing], CHUNKS, judge_enabled=True)
        self.assertEqual((plan["evidence_in_chunks"]["found"], plan["evidence_in_chunks"]["of"], plan["evidence_in_chunks"]["missing"]), (1, 2, ["m"]))


class GuardTests(unittest.TestCase):
    def test_final_test_questions_must_be_verified(self):
        problems = runner.check_freeze([eval_question("t", split="test", status="drafted")], allow_unverified=False)
        self.assertTrue(problems and "verified" in problems[0])

    def test_verified_test_questions_and_drafted_dev_questions_pass(self):
        self.assertEqual(runner.check_freeze([eval_question("t", split="test")], allow_unverified=False), [])
        self.assertEqual(runner.check_freeze([eval_question("d", status="drafted")], allow_unverified=False), [])

    def test_the_unverified_flag_overrides_the_check(self):
        self.assertEqual(runner.check_freeze([eval_question("t", split="test", status="drafted")], allow_unverified=True), [])

    def test_a_completed_test_run_of_the_same_dataset_is_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, setup in (("done", {"completed": True, "includes_test": True, "dataset_hash": "H"}),
                                ("dev", {"completed": True, "includes_test": False, "dataset_hash": "H"}),
                                ("other", {"completed": True, "includes_test": True, "dataset_hash": "X"}),
                                ("partial", {"completed": False, "includes_test": True, "dataset_hash": "H"})):
                (Path(tmp) / name).mkdir()
                (Path(tmp) / name / "config.json").write_text(json.dumps(setup))
            self.assertEqual(runner.previous_test_runs(Path(tmp), "H"), ["done"])
            self.assertEqual(runner.previous_test_runs(Path(tmp) / "missing", "H"), [])


class EvaluateQuestionTests(ChainTestCase):
    def chain_for(self, status="answered", sources=(1,)):
        return SpyChain(self.chain(FakeLLM(draft(list(sources), status=status, answer="Use the Reports tab."))))

    def test_an_answered_question_is_scored_on_every_metric(self):
        spy = self.chain_for()
        record = runner.evaluate_question(eval_question(), spy, FakeJudgeLLM(verdict(True, True)).judge(), "RUN")
        self.assertEqual((record["status"], record["outcome"], record["error"]), ("answered", "answered", None))
        self.assertEqual((record["evidence_ranks"], record["recall_at"]["1"], record["recall_at"]["8"], record["rr"]), ([1], 1.0, 1.0, 1.0))
        self.assertEqual((record["article_rank"], record["cited_urls"], record["citation"]["clean"]), (1, [URL], True))
        self.assertEqual((record["judge"]["facts_covered"], record["judge"]["faithful"]), (2, True))
        self.assertEqual(record["retrieved"][0]["rank"], 1)
        self.assertIsNotNone(record["trace_id"])

    def test_the_run_is_tagged_so_traces_can_be_filtered(self):
        spy = self.chain_for()
        runner.evaluate_question(eval_question("q7", category="procedural"), spy, None, "RUN1")
        call = spy.calls[0]
        self.assertTrue({"eval", "run:RUN1", "q:q7", "split:dev", "category:procedural"} <= set(call["tags"]))
        self.assertEqual((call["metadata"]["question_id"], call["session_id"]), ("q7", "RUN1:q7"))

    def test_a_follow_up_is_asked_with_its_scripted_history(self):
        spy = self.chain_for()
        history = [{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "reply"}]
        runner.evaluate_question(eval_question(history=history, category="follow_up"), spy, None, "RUN")
        self.assertEqual([m.content for m in spy.calls[0]["history"]], ["earlier", "reply"])

    def test_a_correct_abstention_is_not_judged(self):
        judge = FakeJudgeLLM(verdict(True, True))
        record = runner.evaluate_question(abstain_question(), self.chain_for("not_covered", ()), judge.judge(), "RUN")
        self.assertEqual((record["outcome"], record["judge"]), ("correct_abstention", None))
        self.assertEqual(judge.prompts, [])

    def test_a_wrongful_abstention_is_a_failure_and_is_not_judged(self):
        record = runner.evaluate_question(eval_question(), self.chain_for("not_covered", ()), FakeJudgeLLM(verdict(True, True)).judge(), "RUN")
        self.assertEqual((record["outcome"], record["judge"]), ("wrongful_abstention", None))

    def test_a_judge_failure_is_recorded_as_an_error_not_a_score(self):
        from openai import OpenAIError

        record = runner.evaluate_question(eval_question(), self.chain_for(), FakeJudgeLLM(error=OpenAIError("down")).judge(), "RUN")
        self.assertIsNone(record["judge"]["facts_covered"])
        self.assertIn("down", record["judge"]["error"])

    def test_without_a_judge_nothing_is_judged(self):
        self.assertIsNone(runner.evaluate_question(eval_question(), self.chain_for(), None, "RUN")["judge"])

    def test_tokens_and_cost_include_every_model_call(self):
        record = runner.evaluate_question(eval_question(), self.chain_for(), FakeJudgeLLM(verdict(True, True)).judge(), "RUN")
        tokens = record["tokens"]
        self.assertEqual((tokens["chat_in"], tokens["chat_out"], tokens["judge_in"]), (100, 20, 900))
        self.assertEqual(tokens["total"], 120 + tokens["embed"] + 980)
        self.assertIsNone(record["cost_usd"])  # the fake models have no listed price, so no cost is guessed


class RunTests(ChainTestCase):
    def run_eval(self, questions, chain=None, judge=None, results=None, **kwargs):
        tmp = results or Path(self.tmp.name) / "results"
        chain = chain or SpyChain(self.chain(FakeLLM(draft([1], answer="Use the Reports tab."))))
        setup = {"dataset_hash": "H", "split": "dev"}
        summary = runner.run_evaluation(questions, chain, judge, "RUN", tmp, setup, **kwargs)
        return tmp / "RUN", summary

    def test_all_the_files_are_written(self):
        run_dir, summary = self.run_eval([eval_question("a"), eval_question("b")], judge=FakeJudgeLLM(verdict(True, True)).judge())
        for name in ("config.json", "results.jsonl", "review.csv", "summary.json", "summary.md"):
            self.assertTrue((run_dir / name).exists(), name)
        self.assertEqual(len((run_dir / "results.jsonl").read_text().splitlines()), 2)
        self.assertEqual(json.loads((run_dir / "config.json").read_text())["completed"], True)
        self.assertEqual(summary["questions"], 2)

    def test_the_review_csv_puts_expected_and_actual_side_by_side_with_blank_manual_columns(self):
        run_dir, _ = self.run_eval([eval_question("a")], judge=FakeJudgeLLM(verdict(True, False)).judge())
        raw = (run_dir / "review.csv").read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))  # a byte-order mark, so Excel reads the accents
        with (run_dir / "review.csv").open(encoding="utf-8-sig", newline="") as handle:
            row = list(csv.DictReader(handle))[0]
        for column in ("id", "question", "expected_answer", "key_facts", "bot_answer", "bot_status", "outcome", "cited_urls", "expected_urls",
                       "evidence_rank", "judge_facts", "judge_fact_notes", "judge_unsupported", "judge_comment", "auto_pass", "manual_verdict", "manual_notes", "trace_id"):
            self.assertIn(column, row)
        self.assertEqual((row["expected_answer"], row["bot_answer"], row["judge_facts"]), ("Use the Reports tab.", "Use the Reports tab.", "1/2"))
        self.assertEqual((row["manual_verdict"], row["manual_notes"]), ("", ""))
        self.assertIn("Pick a weekly frequency", row["judge_fact_notes"])

    def test_a_question_that_fails_is_recorded_and_the_run_continues(self):
        chain = ExplodingChain("tiktok", self.chain(FakeLLM(draft([1], answer="Use the Reports tab."))))
        run_dir, summary = self.run_eval([abstain_question("a"), eval_question("b")], chain=chain)
        records = [json.loads(line) for line in (run_dir / "results.jsonl").read_text().splitlines()]
        self.assertIn("boom", records[0]["error"])
        self.assertIsNone(records[1]["error"])
        self.assertEqual((summary["questions"], summary["errors"]), (2, 1))

    def test_each_question_is_asked_exactly_once(self):
        spy = SpyChain(self.chain(FakeLLM(draft([1], answer="Use the Reports tab."))))
        self.run_eval([eval_question("a"), eval_question("b")], chain=spy)
        self.assertEqual(len(spy.calls), 2)

    def test_progress_is_reported_after_each_question(self):
        seen = []
        self.run_eval([eval_question("a"), eval_question("b")], on_progress=lambda i, n, record: seen.append((i, n, record["id"])))
        self.assertEqual(seen, [(1, 2, "a"), (2, 2, "b")])

    def test_the_summary_can_be_rebuilt_from_saved_results_without_the_chain(self):
        run_dir, _ = self.run_eval([eval_question("a")], judge=FakeJudgeLLM(verdict(True, True)).judge())
        (run_dir / "summary.md").unlink()
        (run_dir / "review.csv").unlink()
        summary = runner.rebuild_outputs(run_dir)
        self.assertEqual(summary["questions"], 1)
        self.assertTrue((run_dir / "summary.md").exists() and (run_dir / "review.csv").exists())

    def test_the_markdown_summary_states_counts_setup_and_price_assumptions(self):
        run_dir, _ = self.run_eval([eval_question("a"), abstain_question("b")], judge=FakeJudgeLLM(verdict(True, True)).judge())
        text = (run_dir / "summary.md").read_text()
        for expected in ("Recall@8", "MRR", "Correct abstentions", "dataset", "Per category", "direct_factual", "unanswerable", "estimate"):
            self.assertIn(expected, text)
        self.assertIn("/", text)  # raw counts such as 1/1 sit next to percentages

    def test_failures_are_listed_for_the_report(self):
        wrong = SpyChain(self.chain(FakeLLM(draft([], status="not_covered", answer="No."))))
        run_dir, _ = self.run_eval([eval_question("a")], chain=wrong)
        self.assertIn("wrongful_abstention", (run_dir / "summary.md").read_text().split("## Failures")[1])


if __name__ == "__main__":
    unittest.main()
