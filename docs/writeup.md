# Design write-up

## What it is

A chat assistant that answers questions about the IQM platform using only the 200 articles of the IQM Help Center, with a link to the
source of every answer and a clear "not in the Help Center" reply when the articles do not cover a question. It scrapes and cleans the
articles, indexes them, retrieves the most relevant sections for a question, and has an LLM write an answer that is checked before it is
shown. Architecture: `docs/architecture.md`. Each choice below has a longer record in `docs/decisions/`.

## The design choices that mattered

**Keep the structure of the articles.** The pages are short how-to guides with numbered steps, tables, FAQs and screenshots. The cleaner
parses them into sections (paragraphs, list items, table rows, question and answer pairs, media) instead of one block of text, because a
step or a table row is only useful with its heading.

**Chunk by section, not by token count.** The median section is about 140 tokens and only 3 percent exceed 500, so 500 to 700 token chunks
would glue unrelated sections together. A chunk is one section (short siblings merged to about 150 tokens, long ones split at row or item
boundaries, 700 token ceiling), with the article title and heading path in the embedded text so near-identical sections ("from the
Creatives app" and "from the Campaigns app") stay distinguishable. Result: 2,131 chunks, median about 200 tokens.

**Dense baseline first, then measured upgrades.** `text-embedding-3-large` in Chroma, top 8, so later changes could be measured against it.
After the first test run showed where it failed, we added hybrid search (BM25 plus vectors, merged by rank fusion), an LLM reranker behind a
swappable interface and neighbour expansion, each as a switch, and compared four configurations once each on 16 questions written before the
changes. The reranker helped; the other two did not show a gain. The app ships with hybrid plus rerank.

**Never let the model write a URL.** The model sees numbered documents without URLs and returns a status, an answer and the numbers of the
documents it used; the application maps the numbers to stored article URLs. Unknown numbers are dropped, and an answer without a valid
source is shown as "not covered".

**Decide whether to answer from the evidence, not the similarity score.** In an early check the best match for an unanswerable question
(distance 0.50) fell inside the range of answerable ones (0.20 to 0.55), so no threshold separated them. The model returns `answered`,
`not_covered` or `clarification` (a vague question such as "what are the settings?"), and treats documents as evidence, not instructions.

**Follow-ups by rewriting.** From the second turn a small model turns the latest message into a standalone search query using the last
three exchanges, falling back to the raw question on failure. This beat concatenating earlier questions, which drags the old topic into
a new question. Greetings and thanks get a fixed reply without a search or a model call.

**Evaluation that can fail.** 28 questions in 8 categories (6 follow-ups, 4 that should be declined) split into dev and test, plus 16
held-out questions. Retrieval is scored by whether a retrieved chunk contains the evidence quote; abstention and citations are checked
deterministically; correctness and faithfulness use a strict LLM judge. Test and held-out splits run once per configuration.
The interface is Streamlit with a distinct look for the three outcomes and a Developer mode; tracing is LangSmith (one run per request,
a step per stage).

## Trade-offs

- **Small chunks vs context.** Section-sized chunks keep answers precise, but a question spanning sections needs several of them in the top 8.
- **One call vs a verifier.** Deciding "answered, not covered or clarify" in the answer call is cheap and simple; a separate evidence check would be more careful and cost more.
- **Reranker cost.** The LLM rerank doubled cost per question (to about $0.006) and added about a second; it is also not perfectly repeatable.
- **Same model family as judge.** Cheap, but can share the answerer's blind spots.
- **Hosted APIs.** Questions go to OpenAI (and LangSmith if tracing is on); the corpus is public, the questions are the user's.

## What failed or surprised us

- **Navigation chunks crowd out content.** In the worst test failure (a Nurse Level Data report) three of the top 8 chunks were "Locate
  additional resources" link lists, the steps were missing, and the answer looked complete. Dropping 182 such sections fixed it.
- **The first judge gave a false positive.** It called eight supported claims "unsupported" by comparing with key facts instead of documents.
  The fixed judge names a supporting document for every claim and matched a hand check.
- **Citations are still generous.** A prompt asking for the fewest supporting documents raised precision (0.70 to 0.77 on test) but about
  half of the held-out questions still cite an article outside the expected list.
- **A cross-reference was repeated, not followed.** One held-out answer said "follow the steps from step 7" of another workflow although the
  section was in its context. Left unfixed so the held-out numbers stay clean.
- A script that Streamlit's sanitizer silently removed had disabled scrolling and focus; testing in a real browser found it.

## Results (caveats in the evaluation report)

Baseline, 19 test questions: 19 right responses (16 answered, 3 correctly declined); 13 of 16 answers covered every key fact; all 108
checked claims supported; Recall@8 15 of 19 evidence items; median 2.5 s per question.

Held-out, 16 questions (19 evidence items), one run per configuration:

| Configuration | Recall@1 | Recall@8 | MRR | Every key fact (of 14) | Median s | Cost per question |
|---|---|---|---|---|---|---|
| dense | 6/19 | 16/19 | 0.63 | 13 | 2.2 | $0.0031 |
| hybrid | 7/19 | 16/19 | 0.69 | 12 | 2.3 | $0.0031 |
| hybrid + LLM rerank (shipped) | 11/19 | 19/19 | 0.83 | 13 | 3.3 | $0.0059 |
| hybrid + rerank + neighbours | 11/19 | 19/19 | 0.83 | 13 | 3.3 | $0.0061 |

This shows better retrieval, not proven better answers: the baseline already answered most of these questions. The sets are small, the first
was not reviewed question by question, and the judge is a model.

## With more time

1. Follow cross-references inside procedures; cite only the documents behind an answer's claims.
2. A cheaper, repeatable reranker (cross-encoder or hosted) behind the existing interface; a different-provider judge, a hand check of its
   verdicts, and larger human-reviewed question sets.
3. Show the images and videos tied to a section, stream answers, log user feedback against the trace ID, save past chats.
