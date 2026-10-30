"""Small JavaScript snippets for behaviour Streamlit cannot do on its own (FR-7): scrolling, focus, copy and a shortcut.

They are injected with `st.html(..., unsafe_allow_javascript=True)`, which runs in the page itself. The code is fixed
text; the only value interpolated is a boolean or a fixed keyword, never user input.
"""

INPUT_SELECTOR = '[data-testid="stChatInput"] textarea'
MESSAGE_SELECTOR = '[data-testid="stChatMessage"]'
SCROLL_ALIGNMENTS = ("start", "end")

_INSTALL_ONCE = """
if (!window.__iqmUx) {
  window.__iqmUx = true;
  const editable = (el) => el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));
  const copy = function (button) {
    if (!navigator.clipboard) return;
    navigator.clipboard.writeText(button.getAttribute('data-copy')).then(function () {
      const label = button.querySelector('.copy-label');
      const original = label.textContent;
      button.classList.add('copied');
      label.textContent = 'Copied';
      setTimeout(function () { button.classList.remove('copied'); label.textContent = original; }, 1600);
      const box = document.querySelector('__INPUT__');
      if (box && !box.disabled) box.focus({ preventScroll: true });
    });
  };
  document.addEventListener('click', function (event) {
    const button = event.target.closest('[data-copy]');
    if (button) copy(button);
  });
  document.addEventListener('keydown', function (event) {
    const button = event.target.closest && event.target.closest('[data-copy]');
    if (button && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); copy(button); }
  });
  document.addEventListener('keydown', function (event) {
    if (event.key !== '/' || event.metaKey || event.ctrlKey || event.altKey || editable(document.activeElement)) return;
    const box = document.querySelector('__INPUT__');
    if (box && !box.disabled) { event.preventDefault(); box.focus(); }
  });
}
""".replace("__INPUT__", INPUT_SELECTOR)

_FOCUS = """
(function (force) {
  let tries = 0;
  const timer = setInterval(function () {
    tries += 1;
    const box = document.querySelector('__INPUT__');
    if (box && !box.disabled) {
      clearInterval(timer);
      const active = document.activeElement;
      const inSidebar = active && active.closest && active.closest('[data-testid="stSidebar"]');
      const typingElsewhere = active && active !== box && !inSidebar &&
        (active.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(active.tagName));
      const selecting = String(window.getSelection()).length > 0;
      if (force || (!typingElsewhere && !inSidebar && !selecting)) box.focus({ preventScroll: true });
    } else if (tries > 30) { clearInterval(timer); }
  }, 100);
})(__FORCE__);
""".replace("__INPUT__", INPUT_SELECTOR)

_SCROLL = """
(function () {
  const align = '__ALIGN__';
  const place = function () {
    const messages = document.querySelectorAll('__MESSAGE__');
    if (!messages.length) return;
    const reply = messages[messages.length - 1];
    const question = messages.length > 1 ? messages[messages.length - 2] : reply;
    const room = window.innerHeight - 170;  // the visible area above the input box
    const exchange = reply.getBoundingClientRect().bottom - question.getBoundingClientRect().top;
    // 'start': keep the question and its answer together when they fit; for a long answer put the question at the top
    // and let the answer begin right below it. 'end': bring the newest message (the loading card) into view.
    if (align === 'start' && exchange > room) question.scrollIntoView({ behavior: 'smooth', block: 'start' });
    else reply.scrollIntoView({ behavior: 'smooth', block: 'end' });
  };
  if (align === 'end') { setTimeout(place, 150); return; }
  // Streamlit scrolls to the bottom by itself while new content appears. Wait until the answer's height and the scroll
  // position have both stopped changing, then choose where to scroll, so ours is the last move.
  const scroller = document.querySelector('[data-testid="stAppScrollToBottomContainer"]') || document.scrollingElement;
  let previous = '', steady = 0, tries = 0;
  const timer = setInterval(function () {
    tries += 1;
    const messages = document.querySelectorAll('__MESSAGE__');
    const height = messages.length ? messages[messages.length - 1].getBoundingClientRect().height : 0;
    const state = height + '|' + (scroller ? Math.round(scroller.scrollTop) : 0);
    steady = state === previous ? steady + 1 : 0;
    previous = state;
    if (steady >= 3 || tries > 40) { clearInterval(timer); place(); }
  }, 120);
})();
"""
_SCROLL = _SCROLL.replace("__MESSAGE__", MESSAGE_SELECTOR)


def page_script(nonce: int, focus: bool, force_focus: bool = False, scroll: str = "") -> str:
    """The script block for one page run. The nonce makes each run's text different so the browser executes it again."""
    if scroll and scroll not in SCROLL_ALIGNMENTS:
        raise ValueError(f"scroll must be one of {SCROLL_ALIGNMENTS} or empty, got {scroll!r}")
    parts = [f"/* run {int(nonce)} */", _INSTALL_ONCE]
    if scroll:
        parts.append(_SCROLL.replace("__ALIGN__", scroll))
    if focus:
        parts.append(_FOCUS.replace("__FORCE__", "true" if force_focus else "false"))
    return "<script>" + "\n".join(parts) + "</script>"
