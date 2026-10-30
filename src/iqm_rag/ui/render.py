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


def sources_html(sources: Sequence[SourceLink]) -> str:
    if not sources:
        return ""
    chips = "".join(
        f'<a class="chip" href="{_safe_url(link.url)}" target="_blank" rel="noopener noreferrer">'
        f'<span class="chip-icon">↗</span><span class="chip-body"><span class="chip-title">{escape(link.title)}</span>'
        + "".join(f'<span class="chip-sub">{escape(section)}</span>' for section in link.sections) + "</span></a>"
        for link in sources
    )
    return f'<div class="sources-label">Sources</div><div class="chips">{chips}</div>'


def _evidence_row(item: EvidenceItem) -> str:
    used = '<span class="pill">used in answer</span>' if item.cited else ""
    width = max(0.0, min(1.0, item.similarity)) * PERCENT
    link = f' · <a href="{_safe_url(item.url)}" target="_blank" rel="noopener noreferrer">open article ↗</a>' if _safe_url(item.url) else ""
    return (
        f'<div class="ev{" ev-used" if item.cited else ""}"><div class="ev-rank">{item.rank}</div><div class="ev-main">'
        f'<div class="ev-head"><span class="ev-title">{escape(item.header)}</span>{used}</div>'
        f'<div class="ev-snippet">{escape(item.snippet)}</div>'
        f'<div class="ev-meta"><span class="bar"><i style="width:{width:.0f}%"></i></span>'
        f'<span>{item.similarity:.2f} match</span>{link}</div></div></div>'
    )


def evidence_html(items: Sequence[EvidenceItem]) -> str:
    return "".join(_evidence_row(item) for item in items)


def evidence_title(items: Sequence[EvidenceItem]) -> str:
    retrieved, used = evidence_counts(items)
    return f"Evidence · {retrieved} passages searched, {used} used" if used else f"Evidence · {retrieved} passages searched"


def details_html(view: AnswerView) -> str:
    rows = "".join(f"<dt>{escape(label)}</dt><dd>{escape(value)}</dd>" for label, value in view.details)
    return f'<dl class="dev">{rows}</dl>'


def loading_html(message: str) -> str:
    return (f'<div class="thinking"><span class="dots"><i></i><i></i><i></i></span>'
            f'<span class="phrase">{escape(message)}</span></div>')


def hero_html() -> str:
    trust = "".join(f'<span class="trust-chip">{escape(text)}</span>' for text in
                    ("Grounded in help.iqm.com", "Sources on every answer", "Says so when it isn't sure"))
    return ('<div class="hero"><div class="eyebrow">Help Center Assistant</div><h1>What can I help you find?</h1>'
            "<p>Ask about campaigns, creatives, reports, audiences and more. I answer only from the IQM Help Center "
            f'and show where every answer comes from.</p><div class="trust">{trust}</div></div>')


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
