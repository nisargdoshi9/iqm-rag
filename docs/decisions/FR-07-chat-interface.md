# FR-7: Chat interface

Status: decided and implemented (2026-10-31). Start it with `streamlit run app.py`. Saved past chats were considered and
deferred on 2026-10-31 (see Open items).

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

## Revisions after a second review (2026-10-31)

- **Empty chat screen**: the input sits in the middle of the page under the greeting (a chat input placed inside a
  container is inline), with the keyboard hint, three example question cards and the trust points below. After the first
  question it moves to the bottom.
- **Widths**: input 640 px (it matches the answer cards), content column 800 px, sidebar 340 px.
- **Auto-scroll**: when a question is sent the loading card is brought into view. When the answer arrives the page waits
  for its layout and Streamlit's own scroll-to-bottom to settle, then keeps the question and its answer together on screen,
  or, for a long answer, puts the question at the top so the answer starts right below it. Checked three times in a
  browser (an earlier version lost a race against Streamlit's own scroll).
- **Cursor in the box**: focused on landing, after every answer, after New chat and after Copy. It is not taken from the
  user if they are typing in another field, have text selected, or are using the sidebar controls. The placeholder says
  what to type (first question, follow-up, or "Writing your answer…" while locked).
- **Small extras**: `/` jumps to the input from anywhere, and scrolling is smooth. A Copy button, a keyboard hint under the
  empty-state input and a 2,000-character limit on the input were tried and removed on review (the hint was confusing,
  the limit showed a character counter, and the Copy button was not wanted). A question over the search limit still gets a
  friendly explanation instead of an error.
- **User avatar** recoloured from coral to a soft indigo with an indigo person icon, to sit within the theme.

## Revisions after a third review (2026-10-31)

- **Loading messages** are all general; none names a product area (campaigns, creatives, reports and so on), because the
  user may not have asked about them. A test enforces this.
- **Message cards**: each speaker has a distinct card shape (user bubbles right-aligned with a pointed corner and a
  maximum width of 78 percent, assistant cards left with a pointed corner), a consistent spacing rhythm inside cards, and
  sources set off by a divider like a card footer. Found and fixed a clipped bottom edge: Streamlit pulls markdown blocks up
  by 1 rem to cancel its own paragraph margin, which cut the last line of long messages once our own margins were used.

## Revisions after a fourth review (2026-10-31)

- **Source tooltip** no longer repeats the article title the pill already shows. It shows the cited section(s), a short
  extract of the text each one contributed (so a source says what it was used for), and where the click goes ("Opens
  help.iqm.com in a new tab"). The full title appears only when the pill had to cut it short.
- **"+N more"** now expands the extra pills inline, after the visible ones, and the toggle changes to "Show less". Before, the
  extra pills appeared on a new row and the button kept its label, so it looked as if nothing had happened.

## Chat UI best-practice pass (2026-10-31)

Triggered by review feedback on the composer and spacing, and widened to a checklist from published chat-UI guidance (mostly
developer guides, issue threads and design-system docs, not controlled studies). Sources: Stream chat SDK docs (scroll-to-bottom
button), the Zoom chat SDK developer forum, a Jitsi issue on scrolling for one's own messages, a ChatLayout issue on a
bottom tolerance, a Jupyter AI issue on a "new message" indicator, the Nord Health chat component docs (reduced motion,
optional timestamps) and a UXPin chat-UI guide (live regions, retry on failure).

| Guidance | Applied |
|---|---|
| The composer is a fixed region that never hides the newest message and that messages do not show through | The composer is a solid band with a soft fade above it; its padding was cut (it had 56 px of empty space below the box); the gap under the last message went from 177 px to 58 px |
| Always scroll for the user's own send; scroll for a reply only if the reader has not scrolled up | The send scrolls to the loading card. A reply scrolls only if the reader did not scroll up while waiting (checked: the scroll position did not move) |
| Show a jump-to-latest control only when away from the bottom | A "Latest" pill appears when more than 160 px from the bottom, above the composer; clicking it also returns the cursor to the input |
| Timestamps as small optional metadata | A small grey time on every message, shown in the reader's own time zone (with the date if not today) |
| Announce new messages to screen readers; mark the loading state | The transcript is a polite live region; the loading card has role status |
| Clear error with a retry on the failed message | "Try again" on the latest error card; it re-asks the same question without repeating the user's message |
| Respect reduced-motion preferences | Animations, transitions and smooth scrolling are switched off under prefers-reduced-motion |
| Visible keyboard focus, sufficient contrast, phone ergonomics | Focus rings on pills and buttons; muted text darkened to about 5.2:1; 16 px input text (no iOS zoom); safe-area padding; wider bubbles on phones |

Not applied: a stop-generating control (the call is short and cannot be cancelled cleanly), streaming, and human hand-off
(not applicable to a documentation assistant).

Bugs found while verifying in a real browser:
- The "Latest" button was first built from an HTML string inside the script. Streamlit's sanitizer (DOMPurify) removes a
  script whose text contains "<" before a letter, so the whole script silently did nothing (no focus, no scroll). It is now
  built with DOM calls and a test fails if the script text contains such a sequence.
- Collapsing the sidebar left a 40 px strip visible: Streamlit slides it 300 px but ours is 340 px wide. A collapsed sidebar
  now slides fully out (checked on desktop and phone widths).

## Limits

- Light theme only; no dark mode design.
- No streaming: the answer appears when complete (typically 2 to 6 seconds).
- Transcripts live in memory for the browser session and are lost on refresh.
- The default chat avatars are Streamlit's own icons, recoloured.

## Open items

- Saved past chats that can be continued: deferred by decision (2026-10-31). Proposed design for later: local JSON files in
  `data/chats/` (git-ignored), a sidebar list by first question and date, reopen to continue, delete; no accounts. Caveat: if the
  app were ever hosted publicly, every visitor would see every chat, so it would need per-visitor separation first.
- Feedback controls (with tracing), media from matched sections, streaming, dark mode.
