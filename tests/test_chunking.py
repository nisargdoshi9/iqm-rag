"""Tests for FR-3 chunking. Small hand-built articles with one character counted as one token."""

import re
import unittest

from iqm_rag import config
from iqm_rag.ingestion.chunking import ChunkingConfig, chunk_article, chunk_corpus, embedding_text
from iqm_rag.scraping.markdown import render_blocks
from iqm_rag.scraping.normalization import read_jsonl

CFG = ChunkingConfig(merge_min_tokens=20, max_tokens=60, overlap_max_tokens=12, chars_per_token=1)
ROOMY = ChunkingConfig(merge_min_tokens=20, max_tokens=150, overlap_max_tokens=12, chars_per_token=1)  # fits repeated intros


# --- Builders (structured blocks as produced by FR-2) ------------------------------------------------


def para(text: str) -> dict:
    return {"type": "paragraph", "text": text}


def lst(texts: list[str], ordered: bool = False) -> dict:
    items = [{"blocks": [para(text)], "id": f"1:s1:l1:i{n}"} for n, text in enumerate(texts, start=1)]
    return {"type": "list", "ordered": ordered, "items": items, "id": "1:s1:l1"}


def data_table(rows: list[list[str]]) -> dict:
    built = [{"cells": [{"blocks": [para(text)]} for text in row], "id": f"1:s1:t1:r{n}"} for n, row in enumerate(rows, 1)]
    return {"type": "table", "table_class": "data", "rows": built, "id": "1:s1:t1"}


def section(ordinal: int, path: list[str], blocks: list[dict]) -> dict:
    return {"heading": path[-1] if path else None, "level": len(path) or None, "heading_path": path,
            "blocks": blocks, "ordinal": ordinal, "section_id": f"1:s{ordinal}", "content_hash": f"h{ordinal}"}


def article(sections: list[dict]) -> dict:
    return {"article_id": "1", "title": "Title", "canonical_url": "https://help.iqm.com/en/articles/1-title",
            "collection": "Coll", "last_updated": "2026-01-01T00:00:00Z", "sections": sections}


def texts_of(chunks: list[dict]) -> str:
    return "\n".join(chunk["text"] for chunk in chunks)


# --- Tests -------------------------------------------------------------------------------------------


class SingleSectionTests(unittest.TestCase):
    def test_one_small_section_is_one_chunk_with_metadata(self):
        chunks = chunk_article(article([section(1, ["A"], [para("x" * 30)])]), CFG)
        self.assertEqual(len(chunks), 1)
        chunk = chunks[0]
        self.assertTrue(chunk["text"].startswith("## A"))
        self.assertEqual(chunk["context_header"], "Title › A")
        self.assertEqual(
            (chunk["chunk_id"], chunk["article_id"], chunk["article_title"], chunk["collection"], chunk["part"], chunk["parts"]),
            ("1:s1:p1", "1", "Title", "Coll", 1, 1),
        )
        self.assertEqual((chunk["section_path"], chunk["section_ids"], chunk["chunk_index"]), (["A"], ["1:s1"], 0))
        self.assertEqual(chunk["article_url"], "https://help.iqm.com/en/articles/1-title")

    def test_empty_article_gives_no_chunks(self):
        self.assertEqual(chunk_article(article([]), CFG), [])

    def test_a_heading_only_section_is_not_a_chunk_but_stays_in_the_path(self):
        sections = [section(1, ["P"], []), section(2, ["P", "C"], [para("x" * 30)])]
        chunks = chunk_article(article(sections), CFG)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["context_header"], "Title › P › C")

    def test_section_without_heading_uses_the_title_only(self):
        chunks = chunk_article(article([section(1, [], [para("x" * 30)])]), CFG)
        self.assertEqual(chunks[0]["context_header"], "Title")
        self.assertFalse(chunks[0]["text"].startswith("#"))


class MergeTests(unittest.TestCase):
    def children(self, n: int, parent: str = "P") -> list[dict]:
        return [section(i + 2, [parent, f"B{i + 1}"], [para("x" * 8)]) for i in range(n)]

    def test_small_siblings_merge_until_the_minimum_is_reached(self):
        sections = [section(1, ["P"], [])] + self.children(3)
        chunks = chunk_article(article(sections), CFG)
        self.assertEqual([c["section_ids"] for c in chunks], [["1:s2", "1:s3"], ["1:s4"]])
        self.assertEqual(chunks[0]["context_header"], "Title › P")
        self.assertIn("### B1", chunks[0]["text"])
        self.assertIn("### B2", chunks[0]["text"])

    def test_sections_with_different_parents_do_not_merge(self):
        sections = [section(1, ["P", "B1"], [para("x" * 8)]), section(2, ["Q", "B2"], [para("x" * 8)])]
        self.assertEqual(len(chunk_article(article(sections), CFG)), 2)

    def test_merging_never_exceeds_the_maximum(self):
        sections = [section(1, ["P", "B1"], [para("x" * 8)]), section(2, ["P", "B2"], [para("y" * 50)])]
        self.assertEqual(len(chunk_article(article(sections), CFG)), 2)


class SplitTests(unittest.TestCase):
    def test_an_oversized_section_is_split_into_even_pieces_that_keep_all_text(self):
        paragraphs = [para(f"para{n}" + "x" * 15) for n in range(8)]
        chunks = chunk_article(article([section(1, ["A"], paragraphs)]), CFG)
        self.assertGreater(len(chunks), 1)
        self.assertEqual([c["part"] for c in chunks], list(range(1, len(chunks) + 1)))
        self.assertTrue(all(c["parts"] == len(chunks) for c in chunks))
        self.assertEqual(len({c["chunk_id"] for c in chunks}), len(chunks))
        self.assertTrue(all(c["token_estimate"] <= CFG.max_tokens for c in chunks))
        for n in range(8):
            self.assertIn(f"para{n}", texts_of(chunks))

    def test_every_split_piece_repeats_the_section_heading(self):
        chunks = chunk_article(article([section(1, ["A"], [para("p" * 25) for _ in range(6)])]), CFG)
        self.assertTrue(all(c["text"].startswith("## A") for c in chunks))

    def test_a_split_list_repeats_the_intro_and_keeps_item_numbers(self):
        blocks = [para("Follow these steps:"), lst([f"step{n}" + "x" * 7 for n in range(1, 15)], ordered=True)]
        chunks = chunk_article(article([section(1, ["A"], blocks)]), ROOMY)
        self.assertGreater(len(chunks), 1)
        second = chunks[1]["text"]
        self.assertIn("Follow these steps:", second)
        first_number = int(re.search(r"^(\d+)\. ", second, re.M).group(1))
        self.assertGreater(first_number, 1)

    def test_a_split_data_table_repeats_the_header_row_and_loses_no_row(self):
        rows = [["Col A", "Col B"]] + [[f"a{n}" + "x" * 6, f"b{n}"] for n in range(12)]
        chunks = chunk_article(article([section(1, ["A"], [data_table(rows)])]), ROOMY)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertIn("| Col A | Col B |", chunk["text"])
            self.assertIn("| --- | --- |", chunk["text"])
        for n in range(12):
            self.assertEqual(texts_of(chunks).count(f"| a{n}" + "x" * 6), 1)

    def test_the_maximum_holds_even_with_repeated_intro_and_header(self):
        rows = [["Col A", "Col B"]] + [[f"a{n}" + "x" * 8, "b" * 8] for n in range(14)]
        blocks = [para("Intro sentence for the table."), data_table(rows)]
        chunks = chunk_article(article([section(1, ["A"], blocks)]), ROOMY)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(c["token_estimate"] <= ROOMY.max_tokens for c in chunks), [c["token_estimate"] for c in chunks])

    def test_faq_pairs_are_never_separated(self):
        blocks = []
        for n in range(6):
            blocks += [para(f"**Q: question {n}?**"), para(f"**A:** answer {n} " + "x" * 12)]
        chunks = chunk_article(article([section(1, ["FAQ"], blocks)]), CFG)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertEqual(chunk["text"].count("**Q:"), chunk["text"].count("**A:**"))
            self.assertNotRegex(chunk["text"], r"^## FAQ\n\n\*\*A:\*\*")
        self.assertEqual(texts_of(chunks).count("**Q:"), 6)

    def test_text_pieces_overlap_by_one_small_unit(self):
        paragraphs = [para(f"u{n}" + "x" * 8) for n in range(9)]
        chunks = chunk_article(article([section(1, ["A"], paragraphs)]), CFG)
        last_unit_of_first = chunks[0]["text"].split("\n\n")[-1]
        self.assertIn(last_unit_of_first, chunks[1]["text"])

    def test_a_single_oversized_paragraph_is_split_at_sentences(self):
        sentences = [f"Sentence number {n} is here." for n in range(10)]
        chunks = chunk_article(article([section(1, ["A"], [para(" ".join(sentences))])]), CFG)
        self.assertGreater(len(chunks), 1)
        for sentence in sentences:
            self.assertIn(sentence, texts_of(chunks))


class MediaCarryTests(unittest.TestCase):
    def test_a_media_only_section_attaches_to_the_next_chunk(self):
        sections = [section(1, ["Video"], [{"type": "video"}]), section(2, ["Next"], [para("x" * 30)])]
        chunks = chunk_article(article(sections), CFG)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["section_ids"], ["1:s2"])
        self.assertEqual(chunks[0]["media_section_ids"], ["1:s1", "1:s2"])

    def test_a_trailing_media_only_section_attaches_to_the_last_chunk(self):
        sections = [section(1, ["A"], [para("x" * 30)]), section(2, ["Video"], [{"type": "video"}])]
        chunks = chunk_article(article(sections), CFG)
        self.assertEqual(chunks[-1]["media_section_ids"], ["1:s1", "1:s2"])


class IdentityTests(unittest.TestCase):
    def test_chunking_is_deterministic_and_hash_follows_the_embedded_text(self):
        art = article([section(1, ["A"], [para("x" * 30)])])
        first, second = chunk_article(art, CFG), chunk_article(art, CFG)
        self.assertEqual(first, second)
        changed = chunk_article(article([section(1, ["A"], [para("y" * 30)])]), CFG)
        self.assertNotEqual(first[0]["content_hash"], changed[0]["content_hash"])
        self.assertEqual(first[0]["chunk_id"], changed[0]["chunk_id"])

    def test_embedding_text_is_the_header_then_the_text(self):
        chunk = chunk_article(article([section(1, ["A"], [para("x" * 30)])]), CFG)[0]
        self.assertEqual(embedding_text(chunk), "Title › A\n\n" + chunk["text"])


@unittest.skipUnless(config.PROCESSED_ARTICLES_JSONL.exists(), "cleaned corpus not generated; run scripts/normalize.py")
class RealCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.articles = read_jsonl(config.PROCESSED_ARTICLES_JSONL)
        cls.chunks = chunk_corpus(cls.articles)

    def test_chunk_ids_are_unique(self):
        ids = [c["chunk_id"] for c in self.chunks]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_section_with_text_is_covered_by_a_chunk(self):
        covered = {sid for c in self.chunks for sid in c["section_ids"]}
        for art in self.articles:
            for sec in art["sections"]:
                if render_blocks(sec["blocks"]).strip():
                    self.assertIn(sec["section_id"], covered)

    def test_no_chunk_is_empty_or_far_over_the_maximum(self):
        limit = ChunkingConfig().max_tokens * 1.3
        for chunk in self.chunks:
            self.assertTrue(chunk["text"].strip())
            self.assertLessEqual(chunk["token_estimate"], limit, chunk["chunk_id"])


if __name__ == "__main__":
    unittest.main()
