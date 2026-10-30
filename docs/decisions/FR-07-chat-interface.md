# FR-7: Chat interface

Status: decided and implemented (2026-10-31). Start it with `streamlit run app.py`. Saved past chats are not built yet
(see Open items).

## What it does

A Streamlit chat page over the answer chain: text input, transcript, source links on every answer, a clear label for each
kind of outcome, loading and error states, a new-chat button, and an evidence view plus a developer mode for
demonstrations. It adds no new retrieval or answering logic; it shows what the chain returns.

## Decisions

| # | Decision | Options considered | Value |
|---|---|---|---|
| 1 | Technology | Streamlit, Gradio, FastAPI with a page, REST only | Streamlit: built-in chat widgets and per-tab session state that maps onto `Conversation`. Considerable effort on the look (see Design) |
| 2 | Outcomes | Three-way status in the model output; two states with a neutral style; guess from a trailing "?" | Three-way `status` (`answered`, `not_covered`, `clarification`) plus `error` in the page. A clarifying question is never labelled "not in the Help Center". Replaced the earlier `answerable` flag (prompt v4) |
| 3 | Under an answer | Sources only; sources plus an evidence view; everything | Sources only for the user, as compact pills (see Revisions). The retrieved passages (match score, snippet, link, "used" mark) and the search query, rewrite, models, prompt version, tokens, timings and warnings are in the sidebar Developer mode. The first version showed an Evidence expander to everyone; feedback was that it is too much for a user |
| 4 | Loading | Spinner; streamed answer | A loading card that cycles 12 friendly messages every 1.8 s from a random starting point, while the chain runs in a worker thread. Streaming was not done: the output is structured JSON with the answer inside |
| 5 | Sessions | Session state; saved chats | One `Conversation` and transcript per browser session, in session state; the screen keeps the whole transcript, the model gets the last 3 exchanges. Saved past chats: see Open items |
| 6 | Feedback controls | None, local file, tracing service | Skipped; logged for later (best fit is the tracing tool's feedback feature) |
| 7 | Images and videos | Skip, video links, inline images | Skipped; logged for later (chunks carry `media_section_ids`) |
| 8 | Welcome screen | None, example questions | Hero with three trust points and three example question cards drawn at random from five that were checked to be answerable |
| 9 | Testing | Logic tests, Streamlit's test runner, manual checklist | All three |

## Behaviour that matters

- **The page locks while an answer is written.** Submitting sets a pending question and reruns the page with the input
  and sidebar controls disabled; when the answer is shown the page reruns and unlocks. Found by a test run: a second
  question submitted during an answer interrupts Streamlit's script run, which dropped the first answer from the
  transcript and the history. A turn is only recorded on the page's own thread once its answer has arrived, and a
  failed question is never added to the history.
- **Errors never show a stack trace.** A service failure says the search or language service is unavailable; an unusable
  question (empty, too long) says why; anything else is generic. The technical detail appears only in Developer mode.
  A startup failure (missing index or key) shows a plain explanation of what to check.
- **Every dynamic value in the HTML pieces is escaped**, and links are only emitted for http(s) URLs. Answer text is
  rendered as Markdown without raw HTML.

## Design

- Calm light surface with one indigo accent, soft shadowed cards, DM Sans, generous spacing. Locked to the light theme
  in `.streamlit/config.toml`.
- Status colours carry meaning: green "From the Help Center", amber "Not in the Help Center", blue "A quick question",
  orange "Something went wrong".
- User messages sit right in a tinted bubble; assistant answers are white cards with the status badge, text, source
  chips (article title, one line per cited section) and the expanders. The new-chat button and Developer mode are in the
  sidebar next to a short "how it works" card.
- The loading card has animated dots and the rotating message. The messages describe what the app does in general terms
  and never claim a specific step that did not happen.
- Verified by screenshots of every state with a canned chain (welcome, loading, answer, evidence, not covered,
  clarification, error, developer details, phone width) and by two real turns end to end. Checked in one browser engine
  only.

## Revisions after review (2026-10-31)

- **Sidebar could not be reopened.** The "show sidebar" arrow lives inside Streamlit's toolbar, and the stylesheet hid the
  whole toolbar. Now only the menu and deploy button are hidden and the arrow is styled as a visible button.
- **Evidence moved to developer mode** and made compact (two-line snippets, small score bar, one row per passage).
- **Sources are compact pills**: article title on one line (shortened if long); the cited sections and a "Click to open
  this article in the Help Center" hint appear in a hover tooltip; the label says "hover for details, click to open".
  More than three sources show the first three and a "+N more" toggle.
- **Friendlier avatars**: a smiling chat bubble for the assistant and a simple person on a warm background for the user,
  drawn as SVG (replacing Streamlit's robot and face icons).

## Limits

- Light theme only; no dark mode design.
- No streaming: the answer appears when complete (typically 2 to 6 seconds).
- Transcripts live in memory for the browser session and are lost on refresh.
- The default chat avatars are Streamlit's own icons, recoloured.

## Open items

- Saved past chats that can be continued (proposed: local JSON files, git-ignored, a sidebar list; no accounts).
- Feedback controls (with tracing), media from matched sections, streaming, dark mode.
