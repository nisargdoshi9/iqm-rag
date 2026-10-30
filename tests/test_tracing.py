"""Tests for tracing (FR-8). Nothing here reaches the network: tracing is off or the traced call is replaced by a stub."""

import os
import unittest
import uuid
from unittest import mock

import hermetic  # noqa: F401  (keeps tracing off for the whole test run)
from iqm_rag import config
from iqm_rag.generation.prompts import PROMPT_VERSION
from iqm_rag.observability import tracing
from iqm_rag.retrieval.retriever import RetrievalResult, RetrievedChunk
from test_generation import ChainTestCase, FakeLLM, draft
from test_indexing import make_chunk

KEY = "lsv2_pt_example"


class TracingConfigTests(unittest.TestCase):
    def env(self, **values):
        base = {name: "" for name in ("LANGSMITH_API_KEY", "LANGSMITH_TRACING", "LANGSMITH_PROJECT")}
        base.update(values)
        return mock.patch.dict(os.environ, base)

    def test_tracing_is_off_without_a_key(self):
        with self.env():
            self.assertFalse(config.tracing_enabled())

    def test_the_placeholder_key_from_the_example_file_does_not_turn_tracing_on(self):
        with self.env(LANGSMITH_API_KEY="ls-your-key-here"):
            self.assertFalse(config.tracing_enabled())

    def test_a_real_key_turns_tracing_on_without_any_other_setting(self):
        with self.env(LANGSMITH_API_KEY=KEY):
            self.assertTrue(config.tracing_enabled())

    def test_tracing_can_be_switched_off_explicitly_even_with_a_key(self):
        for off in ("false", "0", "no", "OFF"):
            with self.env(LANGSMITH_API_KEY=KEY, LANGSMITH_TRACING=off):
                self.assertFalse(config.tracing_enabled(), off)

    def test_the_project_has_a_default_and_can_be_overridden(self):
        with self.env():
            self.assertEqual(config.langsmith_project(), config.DEFAULT_LANGSMITH_PROJECT)
        with self.env(LANGSMITH_PROJECT="my-project"):
            self.assertEqual(config.langsmith_project(), "my-project")

    def test_configuring_sets_the_variables_the_sdk_reads_and_respects_existing_ones(self):
        with self.env(LANGSMITH_API_KEY=KEY, LANGSMITH_PROJECT="mine"):
            self.assertTrue(tracing.configure_tracing())
            self.assertEqual((os.environ["LANGSMITH_TRACING"], os.environ["LANGSMITH_PROJECT"]), ("true", "mine"))

    def test_configuring_does_nothing_when_tracing_is_off(self):
        with self.env():
            self.assertFalse(tracing.configure_tracing())
            self.assertEqual(os.environ["LANGSMITH_TRACING"], "")


class MetadataTests(unittest.TestCase):
    def test_tags_name_the_prompt_and_models_and_keep_extra_tags_once(self):
        tags = tracing.build_tags("v4", "gpt-x", ("eval", "eval", "q:eval-001"))
        self.assertEqual(tags, ["rag", "prompt:v4", "model:gpt-x", "eval", "q:eval-001"])

    def test_run_metadata_describes_the_setup_and_never_holds_secrets_or_the_question(self):
        meta = tracing.build_run_metadata(prompt_version="v4", chat_model="gpt-x", rewrite_model="gpt-y", embedding_model="emb",
                                          top_k=8, history_messages=4, question_chars=42, session_id="abc", extra={"question_id": "eval-001"})
        self.assertEqual((meta["session_id"], meta["top_k"], meta["question_id"]), ("abc", 8, "eval-001"))
        text = str(meta).lower()
        for secret_word in ("api_key", "apikey", "secret", "password", "lsv2"):
            self.assertNotIn(secret_word, text)

    def test_retrieved_chunks_are_shown_as_documents_with_their_scores(self):
        chunk = make_chunk(1, "some text")
        result = RetrievalResult("q", 8, "emb", 5, 12.0, 3.0, [RetrievedChunk(1, 0.25, chunk)])
        logged = tracing.retrieval_documents(result)
        doc = logged["documents"][0]
        self.assertEqual((doc["page_content"], doc["type"]), ("some text", "Document"))
        self.assertEqual((doc["metadata"]["rank"], doc["metadata"]["similarity"], doc["metadata"]["chunk_id"]), (1, 0.75, chunk["chunk_id"]))
        self.assertEqual((logged["embedding_model"], logged["embedding_tokens"]), ("emb", 5))


class TracedChainTests(ChainTestCase):
    def test_every_answer_has_its_own_trace_id_even_with_tracing_off(self):
        chain = self.chain(FakeLLM(draft([1])))
        first, second = chain.answer("schedule a report"), chain.answer("schedule a report")
        self.assertNotEqual(first.trace_id, second.trace_id)
        self.assertEqual(str(uuid.UUID(first.trace_id)), first.trace_id)
        self.assertFalse(first.traced)

    def test_the_trace_id_is_part_of_the_result_for_the_evaluation_runner_and_the_interface(self):
        answer = self.chain(FakeLLM(draft([1]))).answer("schedule a report")
        self.assertEqual(answer.to_dict()["trace_id"], answer.trace_id)

    def test_the_run_is_started_with_our_trace_id_tags_and_metadata(self):
        chain = self.chain(FakeLLM(draft([1])))
        with mock.patch("iqm_rag.generation.chain._run_chain", wraps=__import__("iqm_rag.generation.chain", fromlist=["x"])._run_chain) as spy:
            answer = chain.answer("schedule a report", session_id="sess-1", tags=("eval",), metadata={"question_id": "eval-001"})
        extra = spy.call_args.kwargs["langsmith_extra"]
        self.assertEqual(str(extra["run_id"]), answer.trace_id)
        self.assertIn("eval", extra["tags"])
        self.assertIn(f"prompt:{PROMPT_VERSION}", extra["tags"])
        self.assertEqual((extra["metadata"]["session_id"], extra["metadata"]["question_id"], extra["metadata"]["top_k"]), ("sess-1", "eval-001", 3))
        self.assertEqual(extra["metadata"]["history_messages"], 0)

    def test_tracing_is_only_enabled_when_the_chain_is_told_to(self):
        for flag in (False, True):
            chain = self.chain(FakeLLM(draft([1])))
            chain.tracing_enabled = flag
            with mock.patch("iqm_rag.generation.chain.tracing_context") as context:
                context.return_value.__exit__.return_value = False  # do not swallow exceptions
                chain.answer("schedule a report")
            self.assertEqual(context.call_args.kwargs["enabled"], flag)

    def test_what_is_logged_for_the_whole_request_is_a_compact_summary_with_no_chunk_text(self):
        answer = self.chain(FakeLLM(draft([1]))).answer("schedule a report")
        summary = answer.trace_summary()
        self.assertEqual((summary["status"], summary["answer"]), ("answered", "Use the Reports tab."))
        self.assertEqual(summary["retrieved_chunk_ids"][0], answer.retrieval.hits[0].chunk["chunk_id"])
        self.assertNotIn("schedule schedule a report", str(summary))
        self.assertEqual(summary["usage"]["total_tokens"], 120)

    def test_objects_that_pass_between_steps_are_logged_compactly_without_chunk_text(self):
        import json

        answer = self.chain(FakeLLM(draft([1]))).answer("schedule a report")
        for logged in (answer.dict(), answer.retrieval.dict(), answer.docs[0].dict()):
            self.assertNotIn("schedule schedule a report", json.dumps(logged))
        self.assertLess(len(json.dumps(answer.dict())), 3000)
        self.assertEqual(answer.retrieval.dict()["chunk_ids"][0], answer.retrieval.hits[0].chunk["chunk_id"])

    def test_the_chain_has_one_named_step_per_stage(self):
        chain = self.chain(FakeLLM(draft([1])))
        names = [step.config.get("run_name") for step in chain.chain.steps]
        self.assertEqual(names, ["rewrite", "retrieve", "build_context", "generate", "check_output"])

    def test_the_summary_metadata_added_after_the_run_names_the_outcome(self):
        answer = self.chain(FakeLLM(draft([], status="not_covered", answer="No."))).answer("schedule a report")
        meta = answer.trace_metadata()
        self.assertEqual((meta["status"], meta["abstained"], meta["citation_count"]), ("not_covered", True, 0))


if __name__ == "__main__":
    unittest.main()
