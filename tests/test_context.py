"""Tests for building the numbered context shown to the model (FR-5). No network calls."""

import unittest

from iqm_rag.generation.context import build_context_docs, format_context
from iqm_rag.retrieval.retriever import RetrievedChunk
from test_indexing import make_chunk


def hit(rank: int, n: int, text: str = "", part: int = 1, parts: int = 1, article: str = "1", header: str = "") -> RetrievedChunk:
    chunk = make_chunk(n, text)
    chunk.update({"chunk_id": f"{article}:s{n}:p{part}", "part": part, "parts": parts, "article_id": article,
                  "article_url": f"https://help.iqm.com/en/articles/{article}-t"})
    if header:
        chunk["context_header"] = header
    return RetrievedChunk(rank=rank, distance=0.1 * rank, chunk=chunk)


class BuildContextTests(unittest.TestCase):
    def test_documents_are_numbered_from_one_in_rank_order(self):
        docs = build_context_docs([hit(1, 1), hit(2, 2), hit(3, 3)])
        self.assertEqual([d.number for d in docs], [1, 2, 3])
        self.assertEqual([d.chunk_ids for d in docs], [("1:s1:p1",), ("1:s2:p1",), ("1:s3:p1",)])

    def test_parts_of_one_section_are_joined_in_part_order_at_the_best_rank(self):
        hits = [hit(1, 5, "second half", part=2, parts=2), hit(2, 6), hit(3, 5, "first half", part=1, parts=2)]
        docs = build_context_docs(hits)
        self.assertEqual(len(docs), 2)
        self.assertEqual(docs[0].text, "first half\n\nsecond half")
        self.assertEqual(docs[0].chunk_ids, ("1:s5:p1", "1:s5:p2"))
        self.assertEqual((docs[0].best_rank, docs[1].number), (1, 2))

    def test_a_lone_part_stays_a_document_and_keeps_its_text(self):
        docs = build_context_docs([hit(1, 5, "only the tail", part=2, parts=3)])
        self.assertEqual((len(docs), docs[0].text), (1, "only the tail"))

    def test_sections_with_the_same_part_number_in_different_articles_are_not_joined(self):
        docs = build_context_docs([hit(1, 1, article="1"), hit(2, 1, article="2")])
        self.assertEqual(len(docs), 2)

    def test_a_document_carries_what_the_application_needs_for_citation(self):
        doc = build_context_docs([hit(1, 1)])[0]
        self.assertEqual(doc.article_url, "https://help.iqm.com/en/articles/1-t")
        self.assertEqual((doc.article_title, doc.section), ("Title", "A › B1"))
        self.assertAlmostEqual(doc.best_similarity, 0.9)

    def test_no_hits_gives_no_documents(self):
        self.assertEqual(build_context_docs([]), [])
        self.assertEqual(format_context([]), "")


class FormatContextTests(unittest.TestCase):
    def test_each_document_is_a_numbered_block_with_its_header_and_text(self):
        text = format_context(build_context_docs([hit(1, 1, "alpha"), hit(2, 2, "beta")]))
        self.assertIn('<doc id="1" title="Title › A › B1">\nalpha\n</doc>', text)
        self.assertIn('<doc id="2" title="Title › A › B2">\nbeta\n</doc>', text)

    def test_urls_are_never_shown_to_the_model(self):
        self.assertNotIn("help.iqm.com", format_context(build_context_docs([hit(1, 1)])))

    def test_quotes_in_a_title_cannot_break_the_tag(self):
        text = format_context(build_context_docs([hit(1, 1, header='Title › "Quoted" heading')]))
        self.assertIn('title="Title › \'Quoted\' heading"', text)


if __name__ == "__main__":
    unittest.main()
