"""Tests for FR-3 embedding and indexing. A fake embedder and a throwaway local Chroma folder; no network calls."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import chromadb
from chromadb.config import Settings

from iqm_rag.ingestion.embeddings import BATCH_SIZE, EmbeddingError, EmbeddingResult, batched
from iqm_rag.ingestion.indexing import (
    COLLECTION_NAME,
    IndexMismatchError,
    chunk_metadata,
    plan_index,
    record_to_chunk,
    run_indexing,
)

DIMENSION = 8


class FakeEmbedder:
    """Deterministic vectors from the text; counts calls and tokens so tests can check what was embedded."""

    def __init__(self, model: str = "fake-model", fail_on_call: int = 0) -> None:
        self.model = model
        self.calls: list[list[str]] = []
        self.fail_on_call = fail_on_call

    def embed(self, texts: list[str]) -> EmbeddingResult:
        self.calls.append(list(texts))
        if self.fail_on_call and len(self.calls) == self.fail_on_call:
            raise EmbeddingError("simulated outage")
        vectors = [[b / 255 for b in hashlib.sha256(t.encode()).digest()[:DIMENSION]] for t in texts]
        return EmbeddingResult(vectors=vectors, tokens=sum(len(t) for t in texts))

    @property
    def texts_embedded(self) -> int:
        return sum(len(call) for call in self.calls)


def make_chunk(n: int, text: str = "") -> dict:
    return {
        "chunk_id": f"1:s{n}:p1", "article_id": "1", "article_title": "Title", "article_url": "https://help.iqm.com/en/articles/1-t",
        "collection": "Coll", "section_path": ["A", f"B{n}"], "section_ids": [f"1:s{n}"], "media_section_ids": [f"1:s{n}", "1:s99"],
        "chunk_index": n, "part": 1, "parts": 1, "context_header": f"Title › A › B{n}", "text": text or f"text number {n}",
        "token_estimate": 5, "last_updated": "2026-01-01T00:00:00Z", "content_hash": hashlib.sha256(f"{n}{text}".encode()).hexdigest(),
    }


class BatchTests(unittest.TestCase):
    def test_batches_keep_order_and_size(self):
        batches = list(batched(list(range(250)), BATCH_SIZE))
        self.assertEqual([len(b) for b in batches], [100, 100, 50])
        self.assertEqual([x for b in batches for x in b], list(range(250)))

    def test_nothing_to_batch(self):
        self.assertEqual(list(batched([], BATCH_SIZE)), [])


class PlanTests(unittest.TestCase):
    def test_new_changed_unchanged_and_stale_are_separated(self):
        chunks = [make_chunk(1), make_chunk(2, "edited"), make_chunk(3)]
        existing = {chunks[0]["chunk_id"]: chunks[0]["content_hash"], chunks[1]["chunk_id"]: "old-hash", "1:s9:p1": "gone"}
        plan = plan_index(chunks, existing)
        self.assertEqual([c["chunk_id"] for c in plan.to_embed], ["1:s2:p1", "1:s3:p1"])
        self.assertEqual((plan.unchanged, plan.stale_ids, plan.updated), (1, ["1:s9:p1"], 1))

    def test_duplicate_chunk_ids_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            plan_index([make_chunk(1), make_chunk(1)], {})


class MetadataTests(unittest.TestCase):
    def test_metadata_is_scalar_and_round_trips_to_the_chunk(self):
        chunk = make_chunk(1)
        metadata = chunk_metadata(chunk)
        self.assertTrue(all(isinstance(v, (str, int, float, bool)) for v in metadata.values()))
        self.assertEqual(record_to_chunk(chunk["chunk_id"], chunk["text"], metadata), chunk)


class IndexingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "chroma"
        self.addCleanup(self.tmp.cleanup)

    def collection(self):
        client = chromadb.PersistentClient(path=str(self.path), settings=Settings(anonymized_telemetry=False))
        return client.get_collection(COLLECTION_NAME)

    def test_a_fresh_index_stores_every_chunk_with_metadata_and_cosine_space(self):
        chunks = [make_chunk(n) for n in range(1, 6)]
        report = run_indexing(chunks, FakeEmbedder(), self.path)
        self.assertEqual((report["added"], report["updated"], report["unchanged"], report["deleted"]), (5, 0, 0, 0))
        col = self.collection()
        self.assertEqual(col.count(), 5)
        self.assertEqual(col.metadata["embedding_model"], "fake-model")
        self.assertEqual(col.configuration["hnsw"]["space"], "cosine")
        stored = col.get(ids=["1:s2:p1"], include=["documents", "metadatas"])
        self.assertEqual(record_to_chunk("1:s2:p1", stored["documents"][0], stored["metadatas"][0]), chunks[1])

    def test_rerunning_creates_no_duplicates_and_embeds_nothing(self):
        chunks = [make_chunk(n) for n in range(1, 4)]
        run_indexing(chunks, FakeEmbedder(), self.path)
        second = FakeEmbedder()
        report = run_indexing(chunks, second, self.path)
        self.assertEqual((report["added"], report["unchanged"]), (0, 3))
        self.assertEqual(second.texts_embedded, 0)
        self.assertEqual(self.collection().count(), 3)

    def test_changed_chunks_are_re_embedded_and_removed_chunks_are_deleted(self):
        run_indexing([make_chunk(1), make_chunk(2), make_chunk(3)], FakeEmbedder(), self.path)
        second = FakeEmbedder()
        report = run_indexing([make_chunk(1), make_chunk(2, "edited text")], second, self.path)
        self.assertEqual((report["updated"], report["unchanged"], report["deleted"]), (1, 1, 1))
        self.assertEqual(second.texts_embedded, 1)
        self.assertEqual(sorted(self.collection().get()["ids"]), ["1:s1:p1", "1:s2:p1"])

    def test_the_text_that_is_embedded_starts_with_the_context_header(self):
        embedder = FakeEmbedder()
        run_indexing([make_chunk(1)], embedder, self.path)
        self.assertTrue(embedder.calls[0][0].startswith("Title › A › B1\n\n"))

    def test_a_different_embedding_model_is_refused_until_rebuild(self):
        run_indexing([make_chunk(1)], FakeEmbedder("model-a"), self.path)
        with self.assertRaisesRegex(IndexMismatchError, "model-a"):
            run_indexing([make_chunk(1)], FakeEmbedder("model-b"), self.path)
        report = run_indexing([make_chunk(1)], FakeEmbedder("model-b"), self.path, rebuild=True)
        self.assertEqual(report["added"], 1)
        self.assertEqual(self.collection().metadata["embedding_model"], "model-b")

    def test_a_dimension_change_is_refused(self):
        run_indexing([make_chunk(1)], FakeEmbedder(), self.path)

        class WideEmbedder(FakeEmbedder):
            def embed(self, texts):
                return EmbeddingResult(vectors=[[0.1] * 3 for _ in texts], tokens=1)

        with self.assertRaisesRegex(IndexMismatchError, "dimension"):
            run_indexing([make_chunk(1), make_chunk(2)], WideEmbedder(), self.path)

    def test_a_failed_batch_keeps_earlier_progress_and_a_rerun_resumes(self):
        chunks = [make_chunk(n) for n in range(1, 251)]  # three batches of at most 100
        with self.assertRaises(EmbeddingError):
            run_indexing(chunks, FakeEmbedder(fail_on_call=3), self.path)
        self.assertEqual(self.collection().count(), 200)
        resume = FakeEmbedder()
        report = run_indexing(chunks, resume, self.path)
        self.assertEqual((report["added"], report["unchanged"]), (50, 200))
        self.assertEqual(resume.texts_embedded, 50)

    def test_dry_run_plans_without_embedding_or_writing(self):
        embedder = FakeEmbedder()
        report = run_indexing([make_chunk(1), make_chunk(2)], embedder, self.path, dry_run=True)
        self.assertEqual((report["would_embed"], embedder.texts_embedded), (2, 0))
        self.assertFalse(self.path.exists())

    def test_the_report_is_json_serialisable_and_names_the_model(self):
        report = run_indexing([make_chunk(1)], FakeEmbedder(), self.path)
        self.assertEqual(json.loads(json.dumps(report))["embedding_model"], "fake-model")
        self.assertEqual(report["dimension"], DIMENSION)


if __name__ == "__main__":
    unittest.main()
