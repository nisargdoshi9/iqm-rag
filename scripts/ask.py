"""Ask one question and print the grounded answer with its sources (FR-5). Makes one embedding call and one model call.

    python scripts/ask.py "How do I schedule a report?"
    python scripts/ask.py "How do I schedule a report?" --evidence   # also list the chunks the model was shown
    python scripts/ask.py "How do I schedule a report?" --json       # full result, including the unchecked model draft
"""

import argparse
import json
import sys
from typing import Optional

from iqm_rag.generation.chain import Answer, GenerationError, default_chain
from iqm_rag.ingestion.embeddings import EmbeddingError
from iqm_rag.ingestion.indexing import IndexMismatchError, IndexNotBuiltError
from iqm_rag.retrieval.retriever import RetrievalError


def format_answer(answer: Answer, evidence: bool) -> str:
    usage = answer.usage
    tokens = "tokens unknown" if usage is None else f"tokens in {usage.input_tokens} / out {usage.output_tokens}"
    lines = [f"Question: {answer.question}",
             f"Answerable: {'yes' if answer.answerable else 'no'}  ({answer.model}, prompt {answer.prompt_version}, "
             f"{tokens}, model {answer.llm_ms:.0f} ms, retrieval {answer.retrieval.embed_ms + answer.retrieval.search_ms:.0f} ms)",
             "", answer.text, ""]
    if answer.citations:
        lines.append("Sources:")
        lines += [f"  - {c.article_title}: {'; '.join(c.sections)}\n    {c.url}" for c in answer.citations]
    lines += [f"Warning: {warning}" for warning in answer.warnings]
    if answer.rewrite.rewritten:
        lines += ["", f"Searched for: {answer.rewrite.query}"]
    if evidence:
        lines += ["", "Chunks shown to the model:"]
        lines += [f"  [{d.number}] similarity {d.best_similarity:.3f}  {d.header}" for d in answer.docs]
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question", help="the question to answer")
    parser.add_argument("--evidence", action="store_true", help="also list the context documents shown to the model")
    parser.add_argument("--json", action="store_true", help="print the full result as JSON")
    args = parser.parse_args(argv)
    try:
        answer = default_chain().answer(args.question)
    except (IndexNotBuiltError, IndexMismatchError, EmbeddingError, RetrievalError, GenerationError, ValueError, RuntimeError) as exc:
        print(f"Answering stopped: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(answer.to_dict(), indent=2, ensure_ascii=False) if args.json else format_answer(answer, args.evidence))
    return 0


if __name__ == "__main__":
    sys.exit(main())
