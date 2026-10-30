"""The Streamlit chat page (FR-7).

One `Conversation` and one transcript per browser session, kept in session state. The model call runs in a worker
thread while the page cycles through friendly status messages; the worker never touches Streamlit.
"""

import random
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Callable, Optional

import streamlit as st

from iqm_rag.generation.chain import AnswerChain
from iqm_rag.generation.conversation import Conversation
from iqm_rag.ui.render import (badge_html, brand_html, details_html, evidence_section_html, hero_html, how_it_works_html,
                               loading_html, sources_html)
from iqm_rag.ui.styles import CSS
from iqm_rag.ui.view import (LOADING_INTERVAL_SECONDS, LOADING_MESSAGES, AnswerView, build_answer_view,
                             build_error_view, loading_message, pick_examples)

PAGE_TITLE = "Help Center Assistant"
INPUT_PLACEHOLDER = "Ask about the IQM Help Center…"
SETUP_HELP = ("The assistant could not start. Check that the index is built (scripts/index.py) and that OPENAI_API_KEY "
              "is set in .env.")


@dataclass
class ChatMessage:
    role: str  # "user" or "assistant"
    text: str = ""
    view: Optional[AnswerView] = None


def _init_state(chain_factory: Callable[[], AnswerChain]) -> None:
    state = st.session_state
    if "chain" not in state:
        state.chain = chain_factory()
    if "conversation" not in state:
        _new_chat()


def _new_chat() -> None:
    state = st.session_state
    state.conversation = Conversation()
    state.messages = []
    state.pending_question = None
    state.examples = pick_examples()


def _submit(question: str) -> None:
    """Show the question and rerun with the page locked, so a second submit cannot interrupt the answer being written."""
    st.session_state.messages.append(ChatMessage("user", question))
    st.session_state.pending_question = question
    st.rerun()


def _sidebar(locked: bool) -> bool:
    with st.sidebar:
        st.markdown(brand_html(), unsafe_allow_html=True)
        if st.button("＋  New chat", key="new_chat", disabled=locked):
            _new_chat()
        developer = st.toggle("Developer mode", key="developer_mode", disabled=locked,
                              help="Show the search query, scores, tokens and timings.")
        st.markdown(how_it_works_html(), unsafe_allow_html=True)
    return developer


def _hero() -> None:
    st.markdown(hero_html(), unsafe_allow_html=True)
    st.markdown('<div class="try-label">Try asking</div>', unsafe_allow_html=True)
    for column, (index, question) in zip(st.columns(len(st.session_state.examples)), enumerate(st.session_state.examples)):
        if column.button(question, key=f"example_{index}", width="stretch"):
            _submit(question)


def _render_assistant(view: AnswerView, developer: bool) -> None:
    st.markdown(badge_html(view.status), unsafe_allow_html=True)
    st.markdown(view.text)
    st.markdown(sources_html(view.sources), unsafe_allow_html=True)
    if developer:
        with st.expander("Developer details"):
            st.markdown(details_html(view), unsafe_allow_html=True)
            st.markdown(evidence_section_html(view.evidence), unsafe_allow_html=True)


def _render_message(message: ChatMessage, developer: bool) -> None:
    with st.chat_message(message.role):
        if message.view is None:
            st.markdown(message.text)
        else:
            _render_assistant(message.view, developer)


def _ask_with_loader(question: str, placeholder) -> AnswerView:
    """Run the chain in a worker thread, cycling the loading message until it finishes. The turn is recorded here, on
    the page's own thread, only once the answer has arrived."""
    state = st.session_state
    start, tick = random.randrange(len(LOADING_MESSAGES)), 0
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(state.chain.answer, question, state.conversation.history())
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
    typed = st.chat_input(INPUT_PLACEHOLDER, disabled=locked)
    if typed and not locked:
        _submit(typed)
    hero_slot = st.empty()  # a slot, so the welcome content disappears the moment a question is asked
    if not state.messages:
        with hero_slot.container():
            _hero()
    for message in state.messages:
        _render_message(message, developer)
    if locked:
        with st.chat_message("assistant"):
            placeholder = st.empty()
            view = _ask_with_loader(state.pending_question, placeholder)
            _render_assistant(view, developer)
        state.messages.append(ChatMessage("assistant", view=view))
        state.pending_question = None
        st.rerun()  # unlock the page
