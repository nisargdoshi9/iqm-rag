"""The look of the chat interface (FR-7): one stylesheet injected into the Streamlit page.

Design: calm light surface, one indigo accent, soft cards, generous spacing, status colours that mean something
(green = from the Help Center, amber = not covered, blue = we ask a question, orange = error). The design is built for
the light theme set in .streamlit/config.toml.
"""

CSS = """
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600;9..40,700;9..40,800&display=swap');

:root {
  --bg: #F5F6FB; --card: #FFFFFF; --ink: #1E2140; --muted: #6A7094; --line: #E4E6F3;
  --accent: #4F46E5; --accent-2: #7C3AED; --accent-soft: #EEF0FF; --accent-line: #DCDFFB;
  --ok: #0F8F66; --ok-soft: #E4F6EE; --warn: #A8650B; --warn-soft: #FFF3D9;
  --info: #2457D6; --info-soft: #E7EFFF; --err: #C2410C; --err-soft: #FFEDE3;
  --shadow: 0 1px 2px rgba(30,33,64,.04), 0 10px 28px -14px rgba(30,33,64,.16);
}

html, body, .stApp, .stApp p, .stApp li, .stApp h1, .stApp h2, .stApp h3, .stApp label, .stApp button,
.stApp input, .stApp textarea, .stApp a, .stApp div[data-testid="stMarkdownContainer"] {
  font-family: 'DM Sans', ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif;
}
.stApp { background: radial-gradient(1200px 500px at 50% -120px, #E9EAFE 0%, rgba(245,246,251,0) 70%), var(--bg); }
header[data-testid="stHeader"] { background: transparent; }
#MainMenu, footer, [data-testid="stToolbar"] { visibility: hidden; }
.block-container { max-width: 860px; padding-top: 2.2rem; padding-bottom: 7rem; }

/* sidebar */
section[data-testid="stSidebar"] { background: var(--card); border-right: 1px solid var(--line); }
section[data-testid="stSidebar"] > div { padding-top: 1.4rem; }
.brand { display: flex; gap: .75rem; align-items: center; margin-bottom: 1.2rem; }
.logo { width: 42px; height: 42px; border-radius: 13px; display: grid; place-items: center; flex: none;
  background: linear-gradient(135deg, var(--accent), var(--accent-2)); box-shadow: 0 8px 18px -8px rgba(79,70,229,.7); }
.brand-name { font-weight: 800; letter-spacing: -.01em; line-height: 1.15; }
.brand-sub { font-size: .76rem; color: var(--muted); margin-top: 2px; }
.how { margin-top: 1.4rem; padding: 1rem 1rem .6rem; border: 1px solid var(--line); border-radius: 14px; background: #FAFAFE; }
.how-title { font-size: .72rem; font-weight: 700; letter-spacing: .09em; text-transform: uppercase; color: var(--muted); margin-bottom: .6rem; }
.how ol { list-style: none; padding: 0; margin: 0; }
.how li { display: flex; gap: .6rem; font-size: .82rem; line-height: 1.4; color: #3A3F66; margin-bottom: .7rem; }
.step { flex: none; width: 20px; height: 20px; border-radius: 50%; background: var(--accent-soft); color: var(--accent);
  font-size: .7rem; font-weight: 700; display: grid; place-items: center; margin-top: 1px; }
section[data-testid="stSidebar"] .stButton > button { width: 100%; border-radius: 12px; font-weight: 600; padding: .6rem 1rem;
  border: 1px solid var(--accent-line); background: var(--accent-soft); color: var(--accent); transition: all .15s ease; }
section[data-testid="stSidebar"] .stButton > button:hover { background: var(--accent); color: #fff; border-color: var(--accent); }

/* hero */
.hero { text-align: center; padding: 2.4rem 0 1.4rem; }
.eyebrow { display: inline-block; font-size: .72rem; font-weight: 700; letter-spacing: .1em; text-transform: uppercase;
  color: var(--accent); background: var(--accent-soft); border: 1px solid var(--accent-line); padding: .3rem .8rem; border-radius: 999px; }
.hero h1 { font-size: 2.7rem; line-height: 1.1; font-weight: 800; letter-spacing: -.025em; margin: 1rem 0 .7rem; padding: 0;
  background: linear-gradient(120deg, #1E2140 20%, var(--accent) 70%, var(--accent-2)); -webkit-background-clip: text;
  background-clip: text; color: transparent; }
.hero p { color: var(--muted); font-size: 1.02rem; line-height: 1.6; max-width: 560px; margin: 0 auto; }
.trust { display: flex; flex-wrap: wrap; gap: .5rem; justify-content: center; margin-top: 1.2rem; }
.trust-chip { font-size: .78rem; font-weight: 600; color: #3A3F66; background: var(--card); border: 1px solid var(--line);
  padding: .35rem .8rem; border-radius: 999px; }
.trust-chip::before { content: "✓"; color: var(--ok); margin-right: .4rem; font-weight: 800; }
.try-label { text-align: center; font-size: .72rem; font-weight: 700; letter-spacing: .09em; text-transform: uppercase;
  color: var(--muted); margin: 1.6rem 0 .8rem; }
[class*="st-key-example_"] button { height: 100%; min-height: 96px; text-align: left; justify-content: flex-start; align-items: flex-start;
  padding: 1rem 1.1rem; border-radius: 16px; background: var(--card); border: 1px solid var(--line); box-shadow: var(--shadow);
  color: var(--ink); font-weight: 600; line-height: 1.4; transition: transform .15s ease, border-color .15s ease, box-shadow .15s ease; }
[class*="st-key-example_"] button:hover { transform: translateY(-3px); border-color: var(--accent); color: var(--accent);
  box-shadow: 0 14px 30px -14px rgba(79,70,229,.45); }
[class*="st-key-example_"] button p { text-align: left; white-space: normal; overflow: visible; text-overflow: clip; }
[class*="st-key-example_"] button div, [class*="st-key-example_"] button span { white-space: normal; overflow: visible; text-overflow: clip; }

/* chat messages */
[data-testid="stChatMessage"] { background: var(--card); border: 1px solid var(--line); border-radius: 20px;
  padding: 1.05rem 1.3rem; box-shadow: var(--shadow); margin-bottom: 1rem; gap: 1rem; animation: rise .35s ease both; }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) { flex-direction: row-reverse; margin-left: auto;
  width: fit-content; max-width: 82%; background: var(--accent-soft); border-color: var(--accent-line); box-shadow: none; }
[data-testid="stChatMessageAvatarUser"] { background: linear-gradient(135deg, var(--accent), var(--accent-2)); color: #fff; }
[data-testid="stChatMessageAvatarAssistant"] { background: linear-gradient(135deg, #0EA5E9, var(--accent)); color: #fff; }
[data-testid="stChatMessage"] p, [data-testid="stChatMessage"] li { line-height: 1.65; }
[data-testid="stChatMessage"] ol, [data-testid="stChatMessage"] ul { padding-left: 1.3rem; }
[data-testid="stChatMessage"] li { margin-bottom: .25rem; }
@keyframes rise { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }

/* status badge */
.badge { display: inline-flex; align-items: center; gap: .45rem; font-size: .72rem; font-weight: 700; letter-spacing: .02em;
  padding: .28rem .7rem; border-radius: 999px; margin-bottom: .6rem; }
.badge i { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.badge-answered { color: var(--ok); background: var(--ok-soft); }
.badge-not_covered { color: var(--warn); background: var(--warn-soft); }
.badge-clarification { color: var(--info); background: var(--info-soft); }
.badge-error { color: var(--err); background: var(--err-soft); }

/* sources */
.sources-label { font-size: .7rem; font-weight: 700; letter-spacing: .09em; text-transform: uppercase; color: var(--muted); margin: 1.1rem 0 .5rem; }
.chips { display: flex; flex-wrap: wrap; gap: .55rem; }
a.chip { display: flex; gap: .6rem; align-items: flex-start; text-decoration: none; color: var(--ink); background: #FAFAFE;
  border: 1px solid var(--line); border-radius: 14px; padding: .6rem .85rem; max-width: 100%; transition: all .15s ease; }
a.chip:hover { border-color: var(--accent); background: var(--accent-soft); transform: translateY(-2px);
  box-shadow: 0 10px 22px -14px rgba(79,70,229,.6); }
.chip-icon { color: var(--accent); font-weight: 800; margin-top: 1px; }
.chip-body { display: flex; flex-direction: column; min-width: 0; }
.chip-title { font-weight: 700; font-size: .84rem; line-height: 1.3; }
.chip-sub { font-size: .75rem; color: var(--muted); line-height: 1.35; margin-top: 2px; }

/* expanders (evidence, developer details) */
[data-testid="stExpander"] { border: 1px solid var(--line); border-radius: 14px; background: #FAFAFE; margin-top: .9rem; overflow: hidden; }
[data-testid="stExpander"] summary { font-weight: 600; font-size: .85rem; color: #3A3F66; }
.ev { display: flex; gap: .8rem; padding: .85rem .2rem; border-top: 1px solid var(--line); }
.ev:first-child { border-top: 0; }
.ev-rank { flex: none; width: 24px; height: 24px; border-radius: 8px; background: #ECEEF8; color: var(--muted); font-size: .75rem;
  font-weight: 700; display: grid; place-items: center; }
.ev-used .ev-rank { background: var(--ok-soft); color: var(--ok); }
.ev-main { min-width: 0; flex: 1; }
.ev-head { display: flex; gap: .5rem; align-items: center; flex-wrap: wrap; }
.ev-title { font-weight: 700; font-size: .84rem; }
.pill { font-size: .66rem; font-weight: 700; color: var(--ok); background: var(--ok-soft); padding: .12rem .5rem; border-radius: 999px; }
.ev-snippet { font-size: .8rem; color: #4A4F75; line-height: 1.5; margin: .3rem 0 .45rem; }
.ev-meta { display: flex; gap: .5rem; align-items: center; font-size: .72rem; color: var(--muted); }
.ev-meta a { color: var(--accent); text-decoration: none; font-weight: 600; }
.bar { width: 70px; height: 5px; border-radius: 4px; background: #E8EAF6; overflow: hidden; display: inline-block; }
.bar i { display: block; height: 100%; background: linear-gradient(90deg, var(--accent), var(--accent-2)); border-radius: 4px; }
dl.dev { display: grid; grid-template-columns: max-content 1fr; gap: .45rem 1rem; margin: 0; font-size: .78rem; }
dl.dev dt { color: var(--muted); font-weight: 600; }
dl.dev dd { margin: 0; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; word-break: break-word; color: #2D3158; }

/* loading */
.thinking { display: flex; align-items: center; gap: .8rem; color: var(--muted); font-weight: 500; padding: .35rem 0; }
.dots { display: inline-flex; gap: 5px; }
.dots i { width: 8px; height: 8px; border-radius: 50%; background: linear-gradient(135deg, var(--accent), var(--accent-2));
  animation: bounce 1.1s infinite ease-in-out; }
.dots i:nth-child(2) { animation-delay: .15s; } .dots i:nth-child(3) { animation-delay: .3s; }
.phrase { animation: fade .5s ease both; }
@keyframes bounce { 0%, 80%, 100% { transform: scale(.55); opacity: .5; } 40% { transform: scale(1); opacity: 1; } }
@keyframes fade { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }

/* input */
[data-testid="stChatInput"] { border-radius: 18px; border: 1px solid var(--line); background: var(--card);
  box-shadow: 0 12px 34px -14px rgba(30,33,64,.28); }
[data-testid="stChatInput"]:focus-within { border-color: var(--accent); box-shadow: 0 0 0 4px rgba(79,70,229,.12), 0 12px 34px -14px rgba(30,33,64,.28); }
[data-testid="stBottom"] > div { background: transparent; }
"""
