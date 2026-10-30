"""Chat in the terminal with follow-up questions (FR-6). Each line you type makes one embedding call and one or two
model calls. Type /new to start a fresh conversation and /quit to leave.

    python scripts/chat.py
    python scripts/chat.py --evidence   # also list the chunks the model was shown for each answer
"""

import argparse
import sys
from typing import Optional

from ask import format_answer
from iqm_rag.generation.chain import GenerationError, default_chain
from iqm_rag.generation.conversation import Conversation
from iqm_rag.ingestion.embeddings import EmbeddingError
from iqm_rag.ingestion.indexing import IndexMismatchError, IndexNotBuiltError
from iqm_rag.retrieval.retriever import RetrievalError

PROMPT = "\nYou: "


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--evidence", action="store_true", help="also list the context documents shown to the model")
    args = parser.parse_args(argv)
    try:
        chain = default_chain()
    except (IndexNotBuiltError, IndexMismatchError, RuntimeError) as exc:
        print(f"Could not start: {exc}", file=sys.stderr)
        return 1
    conversation = Conversation()
    print("Ask about the IQM Help Center. /new starts a new conversation, /quit leaves.")
    while True:
        try:
            line = input(PROMPT).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if line == "/quit":
            return 0
        if line == "/new":
            conversation.reset()
            print("Started a new conversation.")
        elif line:
            try:
                print("\n" + format_answer(conversation.ask(chain, line), args.evidence))
            except (EmbeddingError, RetrievalError, GenerationError, ValueError) as exc:
                print(f"\nSomething went wrong: {exc}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
