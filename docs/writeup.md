# Design write-up

## What it is

A chat assistant that answers questions about the IQM platform using only the 200 articles of the IQM Help Center, with a link to
the source of every answer and a clear "not in the Help Center" reply when the articles do not cover a question. It scrapes and
cleans the articles, indexes them, retrieves the most relevant sections for a question, and has an LLM write an answer that is
checked before it is shown. Architecture: `docs/architecture.md`. Each choice below has a longer record in `docs/decisions/`.

## The design choices that mattered

**Keep the structure of the articles.** The pages are short how-to guides with numbered steps, tables, FAQs and screenshots. The
cleaner parses them into a tree of sections (paragraphs, list items, table rows, question and answer pairs, media) instead of one
block of text, because a step list or a table row is only useful with its heading and its neighbours.

**Chunk by section, not by token count.** The median section is about 140 tokens and only 3 percent exceed 500, so the usual
500 to 700 token chunks would have meant gluing unrelated sections together. A chunk is one section (short siblings merged up to about
150 tokens, long ones split at row or item boundaries with a 700 token ceiling), and the article title and heading path are put in the
embedded text so near-identical sections ("from the Creatives app" and "from the Campaigns app") stay distinguishable. The result is
2,310 chunks, median about 190 tokens. The first version of the chunker produced chunks of up to 905 tokens because repeated headers and
overlap were not counted; the ceiling is now a real limit.

**Plain dense retrieval as the baseline.** `text-embedding-3-large` vectors in Chroma, top 8, no reranking or keyword search, so that
any later improvement can be measured against it. Eight rather than five because a multi-section question had its second evidence section
at rank 7 in early tests.

**Never let the model write a URL.** Retrieved chunks are shown to the model as numbered documents without URLs. The model returns a
status, an answer and the numbers of the documents it used, and the application maps those numbers to the stored article URLs. Numbers
the model was never given are dropped, and an answer without a valid source is shown as "not covered" rather than uncited.

**Decide whether to answer from the evidence, not the similarity score.** In a small early check (8 questions) the best match for an unanswerable
question (distance 0.50) fell inside the range of answerable ones (0.20 to 0.55), so a threshold could not separate them. The model returns
`answered`, `not_covered` or `clarification` (for a question too vague to answer, such as "what are the settings?"), and the prompt tells
it to treat the documents as evidence and not as instructions.

**Follow-ups by rewriting.** From the second turn a small model turns the latest message into a standalone search query using the last
three exchanges, and falls back to the raw question if that fails. We chose this over concatenating earlier questions, which drags the old
topic into a new question. The answer model sees the user's own message and the history, labelled as context and not as evidence.

**An interface that shows where answers come from.** A Streamlit chat page with source links on every answer, a distinct look for the
three outcomes, a loading state, and a Developer mode with the search query, retrieved passages and scores, tokens, timings and the trace
ID. **Tracing** is LangSmith (only when a key is set) with one run per request and a step per stage.

**Evaluation that can fail.** 28 questions in 8 categories (including 6 follow-ups and 4 that should be declined), split into 9 dev and
19 test questions. Retrieval is scored by whether a retrieved chunk contains the evidence quote; abstention and citations are checked
deterministically; answer correctness and faithfulness use an LLM judge told to be strict. The test split was run once.

## Trade-offs

- **Small, structured chunks vs context.** Section-sized chunks match how the articles are written and keep answers precise, but a
  question that spans sections needs several of them in the top 8, and sometimes they do not all make it (see below).
- **One model call vs a verifier.** Deciding "answered, not covered or clarify" in the same call as the answer is cheap (about
  $0.003 per question) and simple; a separate evidence check would be more careful and cost more.
- **Same model family as judge.** The judge is `gpt-4.1-mini`, like the answerer, which keeps cost low but can share its blind spots.
- **Embeddings sent to a hosted API.** Questions go to OpenAI for embedding and answering (and to LangSmith if tracing is on); the
  corpus is public but questions are the user's.

## What failed or surprised us

- **Navigation chunks crowd out content.** 201 of the 2,310 chunks are mostly links ("Locate additional ... resources"). In the worst
  test failure (generating a Nurse Level Data report) three of the top 8 chunks were such lists, the steps section was missing, and the
  answer looked complete while starting mid-procedure.
- **The first judge gave a false positive.** It called eight supported claims "unsupported" because it compared the answer with the key
  facts instead of the documents. The fixed judge must name a supporting document for every claim; on the same answers it matched a hand check.
- **Citations are over-generous.** For 10 of 19 test questions the answer cited an article outside the expected list; for about half of
  those extras no claim in the answer relied on them.
- Smaller surprises: a collapsed sidebar left a visible strip, and a script that Streamlit's sanitizer silently removed had disabled
  scrolling and focus. Both were found by testing in a real browser.

## Results (baseline, with the caveats in the evaluation report)

On the 19 test questions: 19 right responses (16 answered, 3 correctly declined); 13 of 16 answers covered every key fact; every one of
108 checked claims was supported by the retrieved documents; Recall@8 was 15 of 19 evidence items (Recall@1: 9 of 19); median 2.5 seconds
per question. The set is small, the questions were not reviewed one by one, and the judge is a model, so these numbers show where the
system stands, not how it would score on a new set.

## With more time

1. Filter or down-weight navigation chunks; add reranking or keyword search for multi-section questions; compare against this baseline.
2. Cite only the documents behind the answer's claims, and flag a procedure that appears to start mid-way.
3. A stronger or different-provider judge, a hand check of its verdicts, and a larger, human-reviewed question set.
4. Show the images and videos tied to a section, stream answers, save past chats, and re-scrape only changed articles (the hashes for
   this already exist).
