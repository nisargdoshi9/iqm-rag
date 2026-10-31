"""Tests for the evaluation runner (FR-9). Real chain pieces with fake models; no network."""

import csv
import json
import tempfile
import unittest
from pathlib import Path

import hermetic  # noqa: F401  (keeps tracing off in tests)
from iqm_rag.evaluation import runner
from iqm_rag.evaluation.judge import Claim, FactCheck, JudgeVerdict
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
    return JudgeVerdict(fact_checks=[FactCheck(fact=f, covered=c, note="n") for f, c in zip(facts, covered)],
                        claims=[Claim(claim="Use the Reports tab", supporting_doc=1, quote="schedule schedule a report")], comment="none")


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

    def test_the_dataset_hash_changes_when_a_question_changes_but_not_when_only_its_status_does(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "q.jsonl"
            path.write_text(json.dumps({"id": "a", "question": "x", "status": "drafted"}) + "\n")
            first = runner.dataset_hash(path)
            path.write_text(json.dumps({"id": "a", "question": "x", "status": "verified"}) + "\n")
            self.assertEqual(first, runner.dataset_hash(path))
            path.write_text(json.dumps({"id": "a", "question": "y", "status": "verified"}) + "\n")
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

    def test_holdout_questions_are_frozen_like_test_questions(self):
        problems = runner.check_freeze([eval_question("h", split="holdout", status="drafted")], allow_unverified=False)
        self.assertTrue(problems and "verified" in problems[0])
        self.assertEqual(runner.check_freeze([eval_question("h", split="holdout")], allow_unverified=False), [])

    def test_the_holdout_file_is_separate_so_it_cannot_change_the_frozen_hash(self):
        self.assertEqual(runner.question_files("test"), [runner.QUESTIONS_PATH])
        self.assertEqual(runner.question_files("holdout"), [runner.HOLDOUT_PATH])
        self.assertEqual(runner.question_files("all"), [runner.QUESTIONS_PATH])  # "all" never includes the holdout
        with tempfile.TemporaryDirectory() as tmp:
            one, two = Path(tmp) / "a.jsonl", Path(tmp) / "b.jsonl"
            one.write_text(json.dumps(eval_question("a")) + "\n", encoding="utf-8")
            two.write_text(json.dumps(eval_question("b")) + "\n", encoding="utf-8")
            self.assertEqual(runner.dataset_hash(one), runner.dataset_hash([one]))
            self.assertNotEqual(runner.dataset_hash(one), runner.dataset_hash([one, two]))

    def test_a_frozen_split_is_run_once_per_retrieval_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, retrieval in (("old", None), ("hybrid", {"label": "hybrid"}), ("hybrid-llm", {"label": "hybrid+llm"})):
                setup = {"completed": True, "includes_test": True, "dataset_hash": "H", **({"retrieval": retrieval} if retrieval else {})}
                (Path(tmp) / name).mkdir()
                (Path(tmp) / name / "config.json").write_text(json.dumps(setup))
            self.assertEqual(runner.previous_test_runs(Path(tmp), "H"), ["old"])  # runs saved before the switches were plain dense
            self.assertEqual(runner.previous_test_runs(Path(tmp), "H", "hybrid"), ["hybrid"])
            self.assertEqual(runner.previous_test_runs(Path(tmp), "H", "hybrid+llm+neighbours"), [])

    def test_run_ids_name_the_configuration_unless_it_is_plain_dense(self):
        from datetime import datetime, timezone
        now = datetime(2026, 11, 1, 9, 30, tzinfo=timezone.utc)
        self.assertEqual(runner.make_run_id("holdout", now), "20261101-093000-holdout")
        self.assertEqual(runner.make_run_id("holdout", now, "dense"), "20261101-093000-holdout")
        self.assertEqual(runner.make_run_id("holdout", now, "hybrid+llm"), "20261101-093000-holdout-hybrid-llm")

    def test_the_unverified_flag_overrides_the_check(self):
        self.assertEqual(runner.check_freeze([eval_question("t", split="test", status="drafted")], allow_unverified=True), [])

    def test_a_completed_test_run_of_the_same_dataset_is_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, setup in (("done", {"completed": True, "includes_test": True, "dataset_hash": "H"}),
                                ("rejudged", {"completed": True, "includes_test": True, "dataset_hash": "H", "rejudged_from": "done"}),
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


class RejudgeTests(ChainTestCase):
    def saved_run(self, results: Path) -> Path:
        chain = SpyChain(self.chain(FakeLLM(draft([1], answer="Use the Reports tab."))))
        questions = [eval_question("a"), abstain_question("b")]
        runner.run_evaluation(questions, chain, FakeJudgeLLM(verdict(True, False)).judge(), "RUN", results, {"dataset_hash": "H", "split": "dev"})
        return results / "RUN"

    def test_the_plan_counts_only_the_answers_that_would_be_judged(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(runner.plan_rejudge(self.saved_run(Path(tmp))), {"judge_calls": 1, "records": 2})

    def test_rejudging_writes_a_new_run_and_leaves_the_original_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = self.saved_run(Path(tmp))
            before = (original / "results.jsonl").read_text()
            judge = FakeJudgeLLM(verdict(True, True))
            new_dir, summary = runner.rejudge(original, judge.judge(), {c["chunk_id"]: c for c in CHUNKS})
            self.assertEqual((original / "results.jsonl").read_text(), before)
            self.assertEqual(new_dir.name, "RUN-rejudge-j2")
            records = [json.loads(line) for line in (new_dir / "results.jsonl").read_text().splitlines()]
            self.assertEqual(records[0]["judge"]["facts_covered"], 2)
            self.assertIsNone(records[1]["judge"])
            self.assertEqual(len(judge.prompts), 1)
            setup = json.loads((new_dir / "config.json").read_text())
            self.assertEqual((setup["rejudged_from"], setup["completed"], setup["judge_prompt_version"]), ("RUN", True, "j2"))
            self.assertEqual(summary["generation"]["all_facts_covered"]["count"], 1)

    def test_the_judge_is_shown_the_same_documents_the_answer_was_written_from(self):
        with tempfile.TemporaryDirectory() as tmp:
            judge = FakeJudgeLLM(verdict(True, True))
            runner.rejudge(self.saved_run(Path(tmp)), judge.judge(), {c["chunk_id"]: c for c in CHUNKS})
            text = judge.prompts[0][1].content
            self.assertIn('<doc id="1"', text)
            self.assertIn("schedule schedule a report", text)

    def test_the_judge_token_count_and_cost_are_swapped_not_added(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = self.saved_run(Path(tmp))
            first = json.loads((original / "results.jsonl").read_text().splitlines()[0])
            new_dir, _ = runner.rejudge(original, FakeJudgeLLM(verdict(True, True)).judge(), {c["chunk_id"]: c for c in CHUNKS})
            second = json.loads((new_dir / "results.jsonl").read_text().splitlines()[0])
            self.assertEqual(second["tokens"]["total"], first["tokens"]["total"])

    def test_a_missing_chunk_is_reported_not_guessed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(KeyError, "1:s1:p1"):
                runner.rejudge(self.saved_run(Path(tmp)), FakeJudgeLLM(verdict(True, True)).judge(), {})


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
        self.assertIn("doc 1", row["judge_claims"])

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
