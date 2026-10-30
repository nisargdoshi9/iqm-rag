"""Tests for the trace exporter (FR-8). Fake run objects; no network."""

import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from iqm_rag.observability.export import build_tree, run_to_dict, to_json

T0 = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)


def run(name: str, run_id: str, parent=None, offset: float = 0.0, seconds: float = 1.0, **extra):
    base = dict(id=run_id, name=name, run_type="chain", parent_run_id=parent, start_time=T0 + timedelta(seconds=offset),
                end_time=T0 + timedelta(seconds=offset + seconds), prompt_tokens=None, completion_tokens=None, total_tokens=None,
                total_cost=None, tags=["rag"], extra={"metadata": {"top_k": 8, "revision_id": "x", "ls_run_depth": 1}},
                inputs={"a": 1}, outputs={"b": 2}, error=None)
    base.update(extra)
    return SimpleNamespace(**base)


class ExportTests(unittest.TestCase):
    def test_a_run_keeps_latency_tokens_cost_inputs_and_outputs_and_drops_noisy_metadata(self):
        data = run_to_dict(run("llm", "1", prompt_tokens=100, completion_tokens=20, total_tokens=120, total_cost=0.0005, seconds=2.5))
        self.assertEqual((data["latency_seconds"], data["tokens"]["total"], data["estimated_cost_usd"]), (2.5, 120, 0.0005))
        self.assertEqual(data["metadata"], {"top_k": 8})
        self.assertEqual((data["inputs"], data["outputs"]), ({"a": 1}, {"b": 2}))

    def test_a_run_that_has_not_finished_has_no_latency(self):
        self.assertIsNone(run_to_dict(run("x", "1", end_time=None))["latency_seconds"])

    def test_runs_are_nested_under_their_parents_in_start_order(self):
        tree = build_tree([run("retrieve", "3", parent="1", offset=2), run("rewrite", "2", parent="1", offset=1), run("root", "1")])
        self.assertEqual(tree["name"], "root")
        self.assertEqual([child["name"] for child in tree["children"]], ["rewrite", "retrieve"])

    def test_deeper_levels_nest_too(self):
        tree = build_tree([run("root", "1"), run("retrieve", "2", parent="1", offset=1), run("embed", "3", parent="2", offset=2)])
        self.assertEqual(tree["children"][0]["children"][0]["name"], "embed")

    def test_langchains_wrapper_runs_are_left_out_and_their_children_attach_to_the_real_step(self):
        runs = [run("root", "1"), run("RunnableSequence", "2", parent="1", offset=1), run("rewrite", "3", parent="2", offset=2),
                run("RunnableParallel<x>", "4", parent="2", offset=3), run("retrieve", "5", parent="4", offset=4)]
        tree = build_tree(runs)
        self.assertEqual([child["name"] for child in tree["children"]], ["rewrite", "retrieve"])
        self.assertNotIn("Runnable", json.dumps(tree))

    def test_a_trace_without_a_root_is_an_error(self):
        with self.assertRaises(ValueError):
            build_tree([])

    def test_the_output_is_valid_json_with_readable_text(self):
        text = to_json(build_tree([run("root", "1", inputs={"q": "café › menu"})]))
        self.assertEqual(json.loads(text)["inputs"]["q"], "café › menu")
        self.assertIn("café", text)


if __name__ == "__main__":
    unittest.main()
