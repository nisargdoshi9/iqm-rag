"""The Streamlit chat page (FR-7).

One `Conversation` and one transcript per browser session, kept in session state. The model call runs in a worker
thread while the page cycles through friendly status messages; the worker never touches Streamlit. While an answer is
written the page is locked (input and sidebar disabled) so nothing can interrupt it.
"""

import random
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

import streamlit as st

from iqm_rag import config
from iqm_rag.generation.chain import AnswerChain
from iqm_rag.generation.conversation import Conversation
from iqm_rag.ui.render import (brand_html, details_html, evidence_section_html, hero_html, how_it_works_html, loading_html,
                               meta_row_html, sources_html, trust_html, user_time_html)
from iqm_rag.ui.scripts import page_script
from iqm_rag.ui.styles import CSS
from iqm_rag.ui.view import (LOADING_INTERVAL_SECONDS, LOADING_MESSAGES, AnswerView, build_answer_view,
                             build_error_view, loading_message, pick_examples, tracing_status_text)

PAGE_TITLE = "Help Center Assistant"
PLACEHOLDER_FIRST = "Ask about campaigns, creatives, reports…"
PLACEHOLDER_FOLLOW_UP = "Ask a follow-up, or something new…"
PLACEHOLDER_LOCKED = "Writing your answer…"
SETUP_HELP = ("The assistant could not start. Check that the index is built (scripts/index.py) and that OPENAI_API_KEY "
              "is set in .env.")


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ChatMessage:
    role: str  # "user" or "assistant"
    text: str = ""
    view: Optional[AnswerView] = None
    at: datetime = field(default_factory=_now)


def _init_state(chain_factory: Callable[[], AnswerChain]) -> None:
    state = st.session_state
    if "chain" not in state:
        state.chain = chain_factory()
    if "conversation" not in state:
        _new_chat()
    state.setdefault("js_nonce", 0)


def _new_chat() -> None:
    state = st.session_state
    state.conversation = Conversation()
    state.messages = []
    state.pending_question = None
    state.examples = pick_examples()
    state.scroll = ""
    state.force_focus = True  # a fresh chat always puts the cursor in the box


def _submit(question: str) -> None:
    """Show the question and rerun with the page locked, so a second submit cannot interrupt the answer being written."""
    st.session_state.messages.append(ChatMessage("user", question))
    st.session_state.pending_question = question
    st.rerun()


def _inject_js(focus: bool, scroll: str = "", force_focus: bool = False) -> None:
    st.session_state.js_nonce += 1
    st.html(page_script(st.session_state.js_nonce, focus, force_focus, scroll), unsafe_allow_javascript=True)


def _retry() -> None:
    """Ask the failed question again without repeating the user's message: drop the error card and lock the page."""
    state = st.session_state
    if len(state.messages) >= 2 and state.messages[-1].view is not None and state.messages[-1].view.status == "error":
        state.pending_question = state.messages[-2].text
        state.messages.pop()
        st.rerun()


def _sidebar(locked: bool) -> bool:
    with st.sidebar:
        st.markdown(brand_html(), unsafe_allow_html=True)
        if st.button("＋  New chat", key="new_chat", disabled=locked):
            _new_chat()
        developer = st.toggle("Developer mode", key="developer_mode", disabled=locked,
                              help="Show the search query, scores, tokens and timings.")
        if developer:
            st.caption(tracing_status_text(getattr(st.session_state.get("chain"), "tracing_enabled", False), config.langsmith_project()))
        st.markdown(how_it_works_html(), unsafe_allow_html=True)
    return developer


def _welcome() -> Optional[str]:
    """The empty-chat screen: greeting, the input in the middle of the page, example questions underneath."""
    st.markdown(hero_html(), unsafe_allow_html=True)
    typed = st.chat_input(PLACEHOLDER_FIRST, key="chat_box")  # inline: it sits inside a container
    st.markdown('<div class="try-label">Try asking</div>', unsafe_allow_html=True)
    for column, (index, question) in zip(st.columns(len(st.session_state.examples)), enumerate(st.session_state.examples)):
        if column.button(question, key=f"example_{index}", width="stretch"):
            _submit(question)
    st.markdown(trust_html(), unsafe_allow_html=True)
    return typed


def _render_assistant(view: AnswerView, developer: bool, at: datetime, retry: bool = False, locked: bool = False) -> None:
    st.markdown(meta_row_html(view.status, at), unsafe_allow_html=True)
    st.markdown(view.text)
    st.markdown(sources_html(view.sources), unsafe_allow_html=True)
    if retry and view.status == "error" and st.button("Try again", key="retry", disabled=locked):
        _retry()
    if developer:
        with st.expander("Developer details"):
            st.markdown(details_html(view), unsafe_allow_html=True)
            st.markdown(evidence_section_html(view.evidence), unsafe_allow_html=True)


def _render_message(message: ChatMessage, developer: bool, latest: bool = False, locked: bool = False) -> None:
    with st.chat_message(message.role):
        if message.view is None:
            st.markdown(message.text)
            st.markdown(user_time_html(message.at), unsafe_allow_html=True)
        else:
            _render_assistant(message.view, developer, message.at, retry=latest, locked=locked)


def _ask_with_loader(question: str, placeholder) -> AnswerView:
    """Run the chain in a worker thread, cycling the loading message until it finishes. The turn is recorded here, on
    the page's own thread, only once the answer has arrived."""
    state = st.session_state
    start, tick = random.randrange(len(LOADING_MESSAGES)), 0
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(state.chain.answer, question, state.conversation.history(), session_id=state.conversation.session_id)
        while True:
            placeholder.markdown(loading_html(loading_message(start, tick)), unsafe_allow_html=True)
            done, _ = wait([future], timeout=LOADING_INTERVAL_SECONDS)
            if done:
                break
            tick += 1
        placeholder.empty()
        try:
            answer = future.result()
            state.conversation.record(answer)
            return build_answer_view(answer)
        except Exception as exc:  # the page boundary: any failure becomes a friendly message, detail in developer mode
            return build_error_view(exc)


def _answer_pending(developer: bool) -> None:
    state = st.session_state
    with st.chat_message("assistant"):
        placeholder = st.empty()
        _inject_js(focus=False, scroll="end")  # bring the loading card into view straight away
        view = _ask_with_loader(state.pending_question, placeholder)
        answered_at = _now()
        _render_assistant(view, developer, answered_at)
    state.messages.append(ChatMessage("assistant", view=view, at=answered_at))
    state.pending_question = None
    state.scroll = "start"  # the next run shows the top of the new answer and returns the cursor to the box
    st.rerun()


def run(chain_factory: Callable[[], AnswerChain]) -> None:
    st.set_page_config(page_title=PAGE_TITLE, page_icon="💬", layout="wide", initial_sidebar_state="auto")
    st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)
    try:
        _init_state(chain_factory)
    except Exception as exc:  # startup problems (missing index, no API key) get a plain explanation, not a traceback
        st.error(f"{SETUP_HELP}\n\nDetail: {exc}")
        st.stop()
    state = st.session_state
    locked = state.pending_question is not None  # an answer is being written: nothing may interrupt it
    developer = _sidebar(locked)
    welcome_slot = st.empty()  # a slot, so the welcome content disappears the moment a question is asked
    typed = None
    if state.messages:
        placeholder = PLACEHOLDER_LOCKED if locked else PLACEHOLDER_FOLLOW_UP
        typed = st.chat_input(placeholder, key="chat_box", disabled=locked)
    else:
        with welcome_slot.container():
            typed = _welcome()
    if typed and not locked:
        _submit(typed)
    for index, message in enumerate(state.messages):
        _render_message(message, developer, latest=index == len(state.messages) - 1, locked=locked)
    if locked:
        _answer_pending(developer)
    scroll, force = state.scroll, state.force_focus
    state.scroll, state.force_focus = "", False
    _inject_js(focus=True, scroll=scroll, force_focus=force)
