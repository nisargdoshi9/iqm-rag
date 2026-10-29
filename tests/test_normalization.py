"""Tests for FR-2 cleaning. Uses small hand-built pages and one saved real article; never calls the live site."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from iqm_rag.scraping.blocks import parse_article_body
from iqm_rag.scraping.normalization import (
    ProcessedPaths,
    normalize_article,
    read_jsonl,
    run_normalization,
)

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://help.iqm.com/en/articles/100-test"


# --- Page builders (Intercom block markup) -----------------------------------------------------------


def para(text: str) -> str:
    return f'<div class="intercom-interblocks-paragraph no-margin"><p>{text}</p></div>'


def h1(text: str) -> str:
    return f'<div class="intercom-interblocks-heading"><h1>{text}</h1></div>'


def h2(text: str) -> str:
    return f'<div class="intercom-interblocks-subheading"><h2>{text}</h2></div>'


def h4(text: str) -> str:
    return f'<div class="intercom-interblocks-subheading4"><h4>{text}</h4></div>'


def image(url: str = "https://cdn.example/a.png") -> str:
    return f'<div class="intercom-interblocks-image"><a href="{url}"><img src="{url}"></a></div>'


def video(vid: str = "A5Xzz7IpH1E") -> str:
    return (f'<div class="intercom-interblocks-video"><iframe src="https://www.youtube.com/embed/{vid}" '
            'title="Embedded youtube video"></iframe></div>')


def bullets(*items: str) -> str:
    lis = "".join(f"<li>{item}</li>" for item in items)
    return f'<div class="intercom-interblocks-unordered-nested-list"><ul>{lis}</ul></div>'


def steps(*items: str) -> str:
    lis = "".join(f"<li>{item}</li>" for item in items)
    return f'<div class="intercom-interblocks-ordered-nested-list"><ol>{lis}</ol></div>'


def table(*rows: list) -> str:
    trs = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f'<div class="intercom-interblocks-table"><table><tbody>{trs}</tbody></table></div>'


def page(*blocks: str) -> bytes:
    return ('<div class="article_body"><article>' + "".join(blocks) + "</article></div>").encode()


def raw(title: str = "Test article", article_id: str = "100") -> dict:
    return {"article_id": article_id, "title": title, "url": BASE, "canonical_url": BASE,
            "collection": "C", "collections": ["C"], "last_updated": "2026-01-01T00:00:00Z",
            "raw_html_path": "x.html", "raw_html_sha256": "abc", "scraped_at": "t", "scrape_status": "success"}


def run(html: bytes, title: str = "Test article"):
    return normalize_article(raw(title), html)


# --- Furniture ---------------------------------------------------------------------------------------


class FurnitureTests(unittest.TestCase):
    def test_toc_and_back_to_top_are_removed(self):
        html = page(h4("On this page:"), bullets("One", "Two"), h1("Real heading"), para("Body text."),
                    para("Return to the top of this article"), para("<i>Return to the top of this page</i>"))
        record, _, _ = run(html)
        self.assertNotIn("On this page", record["cleaned_markdown"])
        self.assertNotIn("Return to the top", record["cleaned_markdown"])
        self.assertIn("Body text.", record["cleaned_markdown"])
        self.assertEqual(record["cleaning"]["removed"], {"toc": 1, "back_to_top": 2})

    def test_toc_removal_does_not_touch_a_later_heading_with_similar_words(self):
        html = page(h1("Intro"), para("Text."), h1("On this page you can see"), para("More."))
        record, _, _ = run(html)
        self.assertEqual(record["cleaning"]["removed"]["toc"], 0)

    def test_invisible_characters_are_removed(self):
        record, _, _ = run(page(h1("A"), para("Hello​ world\xa0again")))
        self.assertIn("Hello world again", record["cleaned_markdown"])


# --- Structure, IDs and hashes -----------------------------------------------------------------------


class StructureTests(unittest.TestCase):
    def test_sections_have_ordinal_ids_and_heading_paths(self):
        record, _, _ = run(page(para("Intro."), h1("A"), para("a"), h2("B"), para("b"), h1("C"), para("c")))
        sections = record["sections"]
        self.assertEqual([s["section_id"] for s in sections], ["100:s1", "100:s2", "100:s3", "100:s4"])
        self.assertEqual([s["heading"] for s in sections], [None, "A", "B", "C"])
        self.assertEqual(sections[2]["heading_path"], ["A", "B"])
        self.assertEqual(sections[3]["heading_path"], ["C"])

    def test_headings_render_one_level_below_the_title(self):
        record, _, _ = run(page(h1("A"), para("a"), h2("B"), para("b")))
        self.assertTrue(record["cleaned_markdown"].startswith("# Test article"))
        self.assertIn("\n## A\n", record["cleaned_markdown"])
        self.assertIn("\n### B\n", record["cleaned_markdown"])

    def test_nested_lists_get_ids_and_render_indented(self):
        inner = steps("Inner one")
        record, _, _ = run(page(h1("A"), bullets(f"Outer one{inner}", "Outer two")))
        lst = record["sections"][0]["blocks"][0]
        self.assertEqual(lst["id"], "100:s1:l1")
        self.assertEqual([item["id"] for item in lst["items"]], ["100:s1:l1:i1", "100:s1:l1:i2"])
        self.assertIn("- Outer one\n  1. Inner one\n- Outer two", record["cleaned_markdown"])

    def test_output_is_deterministic(self):
        html = page(h1("A"), para("a"), table(["H1", "H2"], ["x", "y"]))
        self.assertEqual(run(html)[0], run(html)[0])

    def test_only_the_edited_section_hash_changes(self):
        before, _, _ = run(page(h1("A"), para("a"), h1("B"), para("b")))
        after, _, _ = run(page(h1("A"), para("a"), h1("B"), para("b edited")))
        hashes_before = [s["content_hash"] for s in before["sections"]]
        hashes_after = [s["content_hash"] for s in after["sections"]]
        self.assertEqual(hashes_before[0], hashes_after[0])
        self.assertNotEqual(hashes_before[1], hashes_after[1])
        self.assertNotEqual(before["content_hash"], after["content_hash"])

    def test_collapsible_summary_becomes_a_heading(self):
        faq = ('<div class="intercom-interblocks-collapsible-section"><details><summary>' + h4("Q: Why?") +
               "</summary>" + para("<b>A:</b> Because.") + "</details></div>")
        record, _, _ = run(page(h1("FAQ"), faq))
        self.assertEqual([s["heading"] for s in record["sections"]], ["FAQ", "Q: Why?"])
        self.assertIn("**A:** Because.", record["cleaned_markdown"])

    def test_unrecognised_markup_is_kept_and_counted(self):
        weird = '<div class="intercom-interblocks-hologram"><span>3D</span></div>'
        record, _, _ = run(page(h1("A"), weird))
        self.assertEqual(record["cleaning"]["block_counts"]["unknown"], 1)
        self.assertIn("hologram", record["sections"][0]["blocks"][0]["html"])

    def test_links_keep_their_target_and_in_page_anchors_keep_only_text(self):
        record, _, _ = run(page(h1("A"), para('See <a href="/en/articles/5-x">Guide</a> and <a href="#h_1">below</a>.')))
        self.assertIn("[Guide](https://help.iqm.com/en/articles/5-x)", record["cleaned_markdown"])
        self.assertIn("and below.", record["cleaned_markdown"])


# --- Tables ------------------------------------------------------------------------------------------


class TableTests(unittest.TestCase):
    def _classes(self, html: bytes) -> list:
        record, _, audit = run(html)
        blocks = [b for s in record["sections"] for b in s["blocks"] if b["type"] == "table"]
        return [b["table_class"] for b in blocks], audit

    def test_single_cell_box_is_a_callout_with_or_without_label(self):
        classes, _ = self._classes(page(h1("A"),
                                        table(["<b>Note: </b>Be careful."]),
                                        table(["Organization admins can add funds."])))
        self.assertEqual(classes, ["callout", "callout"])

    def test_label_cell_plus_text_cell_is_a_callout(self):
        classes, _ = self._classes(page(h1("A"), table(["<b>Notice:</b>", "Something to know."])))
        self.assertEqual(classes, ["callout"])

    def test_callout_renders_as_a_quote_with_the_label_kept(self):
        record, _, _ = run(page(h1("A"), table(["<b>Note: </b>Be careful."])))
        self.assertIn("> **Note:** Be careful.", record["cleaned_markdown"])

    def test_header_plus_rows_is_data_and_renders_as_a_pipe_table(self):
        record, _, _ = run(page(h1("A"), table(["Metric", "Meaning"], ["CTR", "Click rate"], ["VCR", "Video rate"])))
        self.assertIn("| Metric | Meaning |\n| --- | --- |\n| CTR | Click rate |\n| VCR | Video rate |",
                      record["cleaned_markdown"])

    def test_row_count_alone_does_not_make_a_data_table(self):
        classes, audit = self._classes(page(h1("A"), table(["", ""], ["x", "y"])))
        self.assertEqual(classes, ["unknown"])
        self.assertEqual(len(audit), 1)

    def test_image_only_cells_are_a_media_layout_and_text_is_kept(self):
        record, media, _ = run(page(h1("A"), table([image(), "Caption text next to the image"])))
        block = record["sections"][0]["blocks"][0]
        self.assertEqual(block["table_class"], "media_layout")
        self.assertIn("Caption text next to the image", record["cleaned_markdown"])
        self.assertEqual(media[0]["association"], "table_layout")

    def test_unknown_table_keeps_its_html_and_cells_in_the_audit(self):
        html = page(h1("A"), table(["left text", "right text"]))
        record, _, audit = run(html)
        self.assertEqual(audit[0]["table_id"], "100:s1:t1")
        self.assertIn("left text", audit[0]["html"])
        self.assertEqual(audit[0]["rows"][0]["cells"][1]["blocks"][0]["text"], "right text")
        self.assertIn("left text | right text", record["cleaned_markdown"])  # nothing is dropped from the output

    def test_list_in_cell_is_joined_with_semicolons_and_structure_is_kept(self):
        cell = bullets("alpha", "beta")
        record, _, _ = run(page(h1("A"), table(["Name", "Parts"], ["Kit", cell])))
        self.assertIn("| Kit | alpha; beta |", record["cleaned_markdown"])
        stored = record["sections"][0]["blocks"][0]["rows"][1]["cells"][1]["blocks"][0]
        self.assertEqual(stored["type"], "list")
        self.assertEqual(len(stored["items"]), 2)

    def test_pipes_in_cells_are_escaped(self):
        record, _, _ = run(page(h1("A"), table(["K", "V"], ["a|b", "c"])))
        self.assertIn("| a\\|b | c |", record["cleaned_markdown"])

    def test_rows_have_ids_and_hashes(self):
        record, _, _ = run(page(h1("A"), table(["K", "V"], ["a", "b"])))
        rows = record["sections"][0]["blocks"][0]["rows"]
        self.assertEqual([r["id"] for r in rows], ["100:s1:t1:r1", "100:s1:t1:r2"])
        self.assertTrue(all(len(r["content_hash"]) == 64 for r in rows))


# --- Media -------------------------------------------------------------------------------------------


class MediaTests(unittest.TestCase):
    def test_images_are_not_in_the_markdown_but_in_the_sidecar(self):
        record, media, _ = run(page(h1("A"), para("Text."), image()))
        self.assertNotIn("cdn.example", record["cleaned_markdown"])
        self.assertEqual(len(media), 1)
        self.assertEqual(media[0]["media_id"], "100:m1")
        self.assertEqual(media[0]["section_id"], "100:s1")

    def test_association_types(self):
        html = page(
            h1("A"), image("https://cdn.example/1.png"),                                  # directly after heading
            para("Intro:"), image("https://cdn.example/2.png"), para("Follow-up."),      # after heading and text
            para("Steps:"), image("https://cdn.example/3.png"), steps("Do it"),          # before a list
            bullets(f"Click{image('https://cdn.example/4.png')}"),                       # inside a list item
        )
        _, media, _ = run(html)
        by_url = {m["url"].rsplit("/", 1)[1]: m for m in media}
        self.assertEqual(by_url["1.png"]["association"], "after_heading")
        self.assertEqual(by_url["2.png"]["association"], "after_heading_text")
        self.assertEqual(by_url["3.png"]["association"], "before_list")
        self.assertEqual(by_url["3.png"]["container_id"], "100:s1:l1")
        self.assertEqual(by_url["4.png"]["association"], "list_item")
        self.assertEqual(by_url["4.png"]["container_id"], "100:s1:l2:i1")

    def test_table_row_image_in_a_data_table(self):
        html = page(h1("A"), table(["Mockup", "Size"], [image(), "300 x 50"], [image("https://cdn.example/b.png"), "320 x 50"]))
        _, media, _ = run(html)
        self.assertEqual([m["association"] for m in media], ["table_row", "table_row"])
        self.assertEqual(media[1]["container_id"], "100:s1:t1:r3")
        self.assertEqual(media[1]["table_class"], "data")

    def test_the_row_keeps_its_text_when_it_has_an_image(self):
        record, _, _ = run(page(h1("A"), table(["Mockup", "Size"], [image(), "300 x 50"])))
        self.assertIn("| | 300 x 50 |", record["cleaned_markdown"].replace("|  |", "| |"))

    def test_video_embed_records_the_youtube_id(self):
        _, media, _ = run(page(h1("A"), video("A5Xzz7IpH1E")))
        self.assertEqual((media[0]["type"], media[0]["video_id"]), ("video_embed", "A5Xzz7IpH1E"))

    def test_image_inside_a_paragraph_is_still_media(self):
        _, media, _ = run(page(h1("A"), para('Look <img src="https://cdn.example/in.png"> here')))
        self.assertEqual(len(media), 1)

    def test_app_label_images_are_excluded_by_template_only(self):
        labels = table([image("https://cdn.example/l1.png"), image("https://cdn.example/l2.png")])
        overview = page(h1("Primary app(s)"), labels, h1("Other section"), image("https://cdn.example/x.png"))
        _, media, _ = run(overview, title='"Reporting" collection overview')
        by_url = {m["url"].rsplit("/", 1)[1]: m for m in media}
        self.assertTrue(by_url["l1.png"]["excluded"])
        self.assertEqual(by_url["l1.png"]["exclusion_reason"], "app_label")
        self.assertIsNone(by_url["l1.png"]["app_name"])
        self.assertEqual(by_url["l1.png"]["app_name_source"], "image_only")
        self.assertFalse(by_url["x.png"]["excluded"])  # same article, different section
        _, other, _ = run(overview, title="Create or manage a campaign")
        self.assertFalse(any(m["excluded"] for m in other))  # same section name, but not an overview article


# --- Whole dataset and the real article --------------------------------------------------------------


class RealArticleTests(unittest.TestCase):
    def test_saved_article_is_cleaned(self):
        html = (FIXTURES / "article_upload_image_creative.html").read_bytes()
        record, media, _ = normalize_article(raw("Upload an image creative", "5651450"), html)
        markdown = record["cleaned_markdown"]
        self.assertNotIn("On this page", markdown)
        self.assertNotIn("Return to the top", markdown)
        self.assertIn("Image creative overview", markdown)
        self.assertGreater(len(record["sections"]), 3)
        self.assertTrue(any(m["type"] == "video_embed" for m in media))
        self.assertTrue(any(m["association"] == "before_list" for m in media))

    def test_parse_rejects_a_page_without_a_body(self):
        with self.assertRaises(ValueError):
            parse_article_body(b"<html><p>nothing</p></html>", BASE)


class RunTests(unittest.TestCase):
    def test_run_writes_outputs_reports_problems_and_leaves_raw_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "html").mkdir()
            good = page(h1("A"), para("Body."), image())
            (root / "html" / "100.html").write_bytes(good)
            records = [
                {**raw(article_id="100"), "raw_html_path": "html/100.html"},
                {**raw(article_id="101"), "raw_html_path": "html/101.html"},          # file missing
                {**raw(article_id="102"), "scrape_status": "failed", "raw_html_path": None},
            ]
            raw_jsonl = root / "raw.jsonl"
            raw_jsonl.write_text("".join(json.dumps(r) + "\n" for r in records))
            before = hashlib.sha256((root / "html" / "100.html").read_bytes()).hexdigest()
            paths = ProcessedPaths(raw_jsonl, root, root / "p" / "articles.jsonl", root / "p" / "media.jsonl",
                                   root / "p" / "audit.jsonl", root / "p" / "report.json")
            report = run_normalization(paths)
            self.assertEqual(report["articles_processed"], 1)
            self.assertEqual(report["failed"][0]["article_id"], "101")
            self.assertEqual(report["skipped"][0]["article_id"], "102")
            self.assertEqual(len(read_jsonl(paths.articles)), 1)
            self.assertEqual(report["media"]["total"], 1)
            after = hashlib.sha256((root / "html" / "100.html").read_bytes()).hexdigest()
            self.assertEqual(before, after)
            self.assertEqual(run_normalization(paths)["articles_processed"], 1)  # rerun needs no crawl


if __name__ == "__main__":
    unittest.main()
