"""Small JavaScript snippets for behaviour Streamlit cannot do on its own (FR-7): scrolling, focus, timestamps, a
jump-to-latest button, live-region announcements and a shortcut.

They are injected with `st.html(..., unsafe_allow_javascript=True)`, which runs in the page itself. The code is fixed
text; the only values interpolated are a boolean, a fixed keyword and an integer, never user input.

Scroll rules (from common chat-UI guidance): the user's own send always scrolls; a reply only scrolls if the user has not
scrolled up while waiting; otherwise a "Latest" button appears so nothing moves under their eyes.
"""

INPUT_SELECTOR = '[data-testid="stChatInput"] textarea'
MESSAGE_SELECTOR = '[data-testid="stChatMessage"]'
SCROLLER_SELECTOR = '[data-testid="stAppScrollToBottomContainer"]'
SCROLL_ALIGNMENTS = ("start", "end")
JUMP_AWAY_PIXELS = 160  # how far from the bottom before the "Latest" button appears

_INSTALL_ONCE = """
if (!window.__iqmUx) {
  window.__iqmUx = true;
  window.__iqmUserMoved = false;
  const editable = (el) => el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));
  document.addEventListener('keydown', function (event) {
    if (event.key !== '/' || event.metaKey || event.ctrlKey || event.altKey || editable(document.activeElement)) return;
    const box = document.querySelector('__INPUT__');
    if (box && !box.disabled) { event.preventDefault(); box.focus(); }
  });
  // remember that the reader scrolled up, so an arriving answer does not pull the page away from what they are reading
  let touchStart = null;
  document.addEventListener('wheel', function (event) { if (event.deltaY < 0) window.__iqmUserMoved = true; }, { passive: true });
  document.addEventListener('touchstart', function (event) { touchStart = event.touches[0].clientY; }, { passive: true });
  document.addEventListener('touchmove', function (event) {
    if (touchStart !== null && event.touches[0].clientY > touchStart + 6) window.__iqmUserMoved = true;
  }, { passive: true });
  document.addEventListener('keydown', function (event) {
    if (['PageUp', 'Home', 'ArrowUp'].indexOf(event.key) >= 0 && !editable(document.activeElement)) window.__iqmUserMoved = true;
  });
}
""".replace("__INPUT__", INPUT_SELECTOR)

_ENHANCE = """
(function () {
  const scroller = document.querySelector('__SCROLLER__') || document.scrollingElement;
  window.__iqmSmooth = function () { return window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'; };
  // times are sent as UTC; show them in the reader's own time zone, with the date when it is not today
  document.querySelectorAll('.msg-time[data-ts]').forEach(function (el) {
    const moment = new Date(el.getAttribute('data-ts'));
    if (isNaN(moment)) return;
    const clock = moment.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    const today = moment.toDateString() === new Date().toDateString();
    el.textContent = today ? clock : moment.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ', ' + clock;
    el.setAttribute('title', moment.toLocaleString());
  });
  // announce new messages to screen readers politely
  const first = document.querySelector('__MESSAGE__');
  const log = first && first.closest('[data-testid="stVerticalBlock"]');
  if (log && !log.getAttribute('role')) { log.setAttribute('role', 'log'); log.setAttribute('aria-live', 'polite'); log.setAttribute('aria-relevant', 'additions'); }
  // a "Latest" button that only shows when the reader is away from the bottom
  let button = document.querySelector('.jump-latest');
  if (!button) {
    button = document.createElement('button');
    button.type = 'button';
    button.className = 'jump-latest';
    button.setAttribute('aria-label', 'Jump to the latest message');
    // built with DOM calls, not an HTML string: st.html's sanitizer removes a script whose text contains "<" before a letter
    const arrow = document.createElement('span');
    arrow.setAttribute('aria-hidden', 'true');
    arrow.textContent = '↓';
    const label = document.createElement('span');
    label.textContent = 'Latest';
    button.appendChild(arrow);
    button.appendChild(label);
    button.addEventListener('click', function () {
      const s = document.querySelector('__SCROLLER__') || document.scrollingElement;
      window.__iqmUserMoved = false;
      s.scrollTo({ top: s.scrollHeight, behavior: window.__iqmSmooth() });
      const box = document.querySelector('__INPUT__');
      if (box && !box.disabled) box.focus({ preventScroll: true });  // the cursor goes back to the input
    });
    document.body.appendChild(button);
  }
  window.__iqmUpdateJump = function () {
    const s = document.querySelector('__SCROLLER__') || document.scrollingElement;
    const box = document.querySelector('[data-testid="stChatInput"]');
    const away = s.scrollHeight - s.scrollTop - s.clientHeight > __AWAY__;
    button.classList.toggle('visible', !!(away && box && document.querySelector('__MESSAGE__')));
    if (box) {
      const rect = box.getBoundingClientRect();
      button.style.left = (rect.left + rect.width / 2) + 'px';
      button.style.bottom = (window.innerHeight - rect.top + 14) + 'px';
    }
  };
  if (scroller && window.__iqmBound !== scroller) {
    scroller.addEventListener('scroll', function () { window.__iqmUpdateJump(); }, { passive: true });
    window.__iqmBound = scroller;
  }
  window.__iqmUpdateJump();
  setTimeout(window.__iqmUpdateJump, 500);
})();
""".replace("__SCROLLER__", SCROLLER_SELECTOR).replace("__MESSAGE__", MESSAGE_SELECTOR).replace("__AWAY__", str(JUMP_AWAY_PIXELS)).replace("__INPUT__", INPUT_SELECTOR)

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
  const scroller = function () { return document.querySelector('__SCROLLER__') || document.scrollingElement; };
  const place = function () {
    const messages = document.querySelectorAll('__MESSAGE__');
    if (!messages.length) return;
    const reply = messages[messages.length - 1];
    const question = messages.length > 1 ? messages[messages.length - 2] : reply;
    const composer = document.querySelector('[data-testid="stBottom"]');
    const room = window.innerHeight - (composer ? composer.getBoundingClientRect().height : 120) - 40;
    const exchange = reply.getBoundingClientRect().bottom - question.getBoundingClientRect().top;
    const behavior = window.__iqmSmooth ? window.__iqmSmooth() : 'smooth';
    // 'start': keep the question and its answer together when they fit; for a long answer put the question at the top
    // and let the answer begin right below it. 'end': bring the newest message (the loading card) into view.
    if (align === 'start' && exchange > room) question.scrollIntoView({ behavior: behavior, block: 'start' });
    else reply.scrollIntoView({ behavior: behavior, block: 'end' });
  };
  if (align === 'end') { window.__iqmUserMoved = false; setTimeout(place, 150); return; }
  // the reader scrolled up while waiting: leave the page where it is; the "Latest" button offers the way down
  if (window.__iqmUserMoved) { setTimeout(function () { if (window.__iqmUpdateJump) window.__iqmUpdateJump(); }, 300); return; }
  // Streamlit scrolls to the bottom by itself while new content appears. Wait until the answer's height and the scroll
  // position have both stopped changing, then choose where to scroll, so ours is the last move.
  let previous = '', steady = 0, tries = 0;
  const timer = setInterval(function () {
    tries += 1;
    const messages = document.querySelectorAll('__MESSAGE__');
    const height = messages.length ? messages[messages.length - 1].getBoundingClientRect().height : 0;
    const state = height + '|' + Math.round(scroller().scrollTop);
    steady = state === previous ? steady + 1 : 0;
    previous = state;
    if (steady >= 3 || tries > 40) { clearInterval(timer); place(); }
  }, 120);
})();
""".replace("__SCROLLER__", SCROLLER_SELECTOR).replace("__MESSAGE__", MESSAGE_SELECTOR)


def page_script(nonce: int, focus: bool, force_focus: bool = False, scroll: str = "") -> str:
    """The script block for one page run. The nonce makes each run's text different so the browser executes it again."""
    if scroll and scroll not in SCROLL_ALIGNMENTS:
        raise ValueError(f"scroll must be one of {SCROLL_ALIGNMENTS} or empty, got {scroll!r}")
    parts = [f"/* run {int(nonce)} */", _INSTALL_ONCE, _ENHANCE]
    if scroll:
        parts.append(_SCROLL.replace("__ALIGN__", scroll))
    if focus:
        parts.append(_FOCUS.replace("__FORCE__", "true" if force_focus else "false"))
    return "<script>" + "\n".join(parts) + "</script>"
