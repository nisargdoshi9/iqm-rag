"""HTML snippets for the parts Streamlit has no widget for (FR-7). Every dynamic value is escaped here.

Titles and section names come from the corpus and the question text comes from the user, so nothing is interpolated
into HTML without `html.escape`, and links are only emitted for http(s) URLs.
"""

from html import escape
from typing import Sequence

from iqm_rag.ui.view import STATUS_LABELS, AnswerView, EvidenceItem, SourceLink, evidence_counts

PERCENT = 100


def _safe_url(url: str) -> str:
    return escape(url, quote=True) if url.startswith(("https://", "http://")) else ""


def badge_html(status: str) -> str:
    return f'<span class="badge badge-{escape(status)}"><i></i>{escape(STATUS_LABELS[status])}</span>'


MAX_VISIBLE_SOURCES = 3  # the rest sit behind a "+N more" toggle so a long list never takes over the answer


def _source_pill(link: SourceLink) -> str:
    url = _safe_url(link.url)
    sections = "".join(f'<span class="tip-sec">{escape(section)}</span>' for section in link.sections)
    tip = (f'<span class="tip"><span class="tip-title">{escape(link.title)}</span>{sections}'
           f'<span class="tip-hint">Click to open this article in the Help Center ↗</span></span>')
    body = f'<span class="src-icon">↗</span><span class="src-text">{escape(link.title)}</span>{tip}'
    if not url:
        return f'<span class="src">{body}</span>'
    return f'<a class="src" href="{url}" target="_blank" rel="noopener noreferrer">{body}</a>'


def sources_html(sources: Sequence[SourceLink]) -> str:
    """Compact source pills: the title on one line, the section(s) and an "opens the article" hint in a hover tooltip."""
    if not sources:
        return ""
    pills = "".join(_source_pill(link) for link in sources[:MAX_VISIBLE_SOURCES])
    hidden = sources[MAX_VISIBLE_SOURCES:]
    more = ""
    if hidden:
        rest = "".join(_source_pill(link) for link in hidden)
        more = f'<details class="more"><summary class="src more-btn">+{len(hidden)} more</summary><div class="more-list">{rest}</div></details>'
    return ('<div class="sources-label">Sources <span>· hover for details, click to open</span></div>'
            f'<div class="chips">{pills}{more}</div>')


def _evidence_row(item: EvidenceItem) -> str:
    used = '<span class="pill">used</span>' if item.cited else ""
    width = max(0.0, min(1.0, item.similarity)) * PERCENT
    link = f'<a href="{_safe_url(item.url)}" target="_blank" rel="noopener noreferrer">open ↗</a>' if _safe_url(item.url) else ""
    return (
        f'<div class="ev{" ev-used" if item.cited else ""}"><div class="ev-rank">{item.rank}</div><div class="ev-main">'
        f'<div class="ev-head"><span class="ev-title">{escape(item.header)}</span>{used}</div>'
        f'<div class="ev-snippet">{escape(item.snippet)}</div>'
        f'<div class="ev-meta"><span class="bar"><i style="width:{width:.0f}%"></i></span>'
        f'<span>{item.similarity:.2f}</span>{link}</div></div></div>'
    )


def evidence_html(items: Sequence[EvidenceItem]) -> str:
    return "".join(_evidence_row(item) for item in items)


def evidence_title(items: Sequence[EvidenceItem]) -> str:
    retrieved, used = evidence_counts(items)
    return f"Retrieved passages · {retrieved} searched, {used} used in the answer"


def evidence_section_html(items: Sequence[EvidenceItem]) -> str:
    """The retrieved passages for developer mode: a heading and one compact row per passage."""
    if not items:
        return ""
    return f'<div class="dev-heading">{escape(evidence_title(items))}</div><div class="ev-list">{evidence_html(items)}</div>'


def details_html(view: AnswerView) -> str:
    rows = "".join(f"<dt>{escape(label)}</dt><dd>{escape(value)}</dd>" for label, value in view.details)
    return f'<dl class="dev">{rows}</dl>'


def loading_html(message: str) -> str:
    return (f'<div class="thinking"><span class="dots"><i></i><i></i><i></i></span>'
            f'<span class="phrase">{escape(message)}</span></div>')


def hero_html() -> str:
    return ('<div class="hero"><div class="eyebrow">Help Center Assistant</div><h1>What can I help you find?</h1>'
            "<p>Ask about campaigns, creatives, reports, audiences and more. I answer only from the IQM Help Center "
            "and show where every answer comes from.</p></div>")


def trust_html() -> str:
    chips = "".join(f'<span class="trust-chip">{escape(text)}</span>' for text in
                    ("Grounded in help.iqm.com", "Sources on every answer", "Says so when it isn't sure"))
    return f'<div class="trust">{chips}</div>'


def brand_html() -> str:
    return ('<div class="brand"><div class="logo"><svg viewBox="0 0 24 24" width="22" height="22" fill="none" '
            'stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a8 8 0 0 1-11.6 '
            '7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/><path d="M9 11h6M9 14h4"/></svg></div><div><div class="brand-name">'
            'Help Center Assistant</div><div class="brand-sub">Answers only from help.iqm.com</div></div></div>')


def how_it_works_html() -> str:
    steps = ("Your question is matched to the most relevant Help Center sections.",
             "The answer is written only from those sections.",
             "If the Help Center doesn't cover it, I say so instead of guessing.")
    items = "".join(f'<li><span class="step">{i}</span><span>{escape(text)}</span></li>' for i, text in enumerate(steps, 1))
    return f'<div class="how"><div class="how-title">How it works</div><ol>{items}</ol></div>'
