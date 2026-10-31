"""Replies to greetings, thanks and similar messages that are not questions (FR-5).

Searching the Help Center for "hi" returns unrelated chunks, and the user would be told the Help Center cannot answer
it. These messages are matched by exact, whole-message rules, so no model call is made and a real question is never
mistaken for small talk: anything that does not match completely goes through the normal RAG chain.
"""

import re
from typing import Optional

MAX_WORDS = 6
NOT_WORD = re.compile(r"[^a-z' ]+")

GREETING = "greeting"
THANKS = "thanks"
GOODBYE = "goodbye"
ACKNOWLEDGEMENT = "acknowledgement"
CAPABILITIES = "capabilities"

PATTERNS = {
    GREETING: re.compile(r"^(hi|hello|hey|hiya|howdy|yo|greetings|good (morning|afternoon|evening))( (there|team|bot|assistant|iqm))?$"),
    THANKS: re.compile(r"^((ok|okay|great|perfect|awesome|cool|got it|nice)[ ,]+)?(thanks|thank you|thx|ty|cheers|many thanks)( (a lot|so much|very much|again))?( (that helps|that helped))?$"),
    GOODBYE: re.compile(r"^(bye|goodbye|see you|see ya|cya|good night|that's all|that is all|nothing else|i'm done|im done)( (for now|thanks))?$"),
    ACKNOWLEDGEMENT: re.compile(r"^(ok|okay|got it|cool|great|nice|perfect|awesome|understood|alright|sounds good|makes sense|i see|noted)$"),
    CAPABILITIES: re.compile(r"^(who are you|what are you|what can you do|what do you do|what can i ask( you)?|how does this work|how do you work|help|help me)$"),
}

REPLIES = {
    GREETING: "Hi! I'm the IQM Help Center assistant. Ask me how something works in the IQM platform and I'll answer from "
              "the Help Center, with links to the articles I used.",
    THANKS: "You're welcome! Let me know if there's anything else you'd like to know about the IQM platform.",
    GOODBYE: "Goodbye! Come back any time you have a question about the IQM platform.",
    ACKNOWLEDGEMENT: "Glad that helps. Ask me anything else about the IQM platform whenever you're ready.",
    CAPABILITIES: "I answer questions about the IQM platform using only the IQM Help Center, and I show which articles each "
                  "answer came from. If the Help Center doesn't cover something, I'll say so rather than guess. Try asking "
                  "how to do a task or what a setting means.",
}


def _normalise(message: str) -> str:
    return " ".join(NOT_WORD.sub(" ", message.lower().replace("’", "'")).split())


def kind_of(message: str) -> Optional[str]:
    """The kind of small talk the whole message is, or None if it should be treated as a question."""
    text = _normalise(message)
    if not text or len(text.split()) > MAX_WORDS:
        return None
    return next((kind for kind, pattern in PATTERNS.items() if pattern.match(text)), None)


def reply_to(message: str) -> Optional[str]:
    kind = kind_of(message)
    return None if kind is None else REPLIES[kind]
