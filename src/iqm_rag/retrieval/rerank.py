"""Reranking: reorder retrieval candidates so the best evidence comes first (FR-4 extension).

`Reranker` is the interface. `LLMReranker` asks a language model to pick and order the candidates in one call (a
"listwise" rerank). A local cross-encoder or a hosted rerank API can be dropped in by implementing `rerank`.
A reranker never drops the pipeline: if the model call fails or returns nothing usable, the fused order is kept and the
reason is reported.
"""

import time
from dataclasses import dataclass
from typing import Optional, Protocol, Sequence

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from openai import OpenAIError
from pydantic import BaseModel, Field

from iqm_rag import config
from iqm_rag.usage import Usage, usage_from_message

RERANK_PROMPT_VERSION = "r1"
MAX_CANDIDATE_CHARS = 1500  # a longer chunk is cut for the reranker only; the answer step still sees the full text
MAX_OUTPUT_TOKENS = 300
MS_PER_SECOND = 1000.0

SYSTEM_PROMPT = """# Role and Objective
You choose which Help Center passages best help answer a user's question about the IQM platform. You do not answer \
the question.

# Instructions
- You are given numbered passages. Return the numbers of the best passages, best first, at most {top_k}.
- Prefer passages that state the facts, steps, limits or settings the question asks for.
- Prefer the passage from the article about the exact feature, report or audience type named in the question over a \
similar one for a different feature.
- If the question has several parts, include passages for every part, even from different articles or sections.
- If a procedure is split across passages, include the passage with its first steps.
- Skip passages that only mention the topic, only list links, or repeat what a better passage already says.
- Return each number at most once. Only use numbers that appear in the passages."""

HUMAN_PROMPT = """# Question
{question}

# Passages
{passages}"""


class Ranking(BaseModel):
    ranking: list[int] = Field(description="Passage numbers, best first, without repeats.")


@dataclass(frozen=True)
class RerankOutcome:
    order: list[int]  # indexes into the candidates, best first
    model: Optional[str]
    usage: Optional[Usage]
    ms: float
    fallback_reason: Optional[str]  # set when the candidates' original order was kept
    prompt_version: str = RERANK_PROMPT_VERSION

    def to_dict(self) -> dict:
        return {"model": self.model, "ms": round(self.ms, 1), "fallback_reason": self.fallback_reason, "order": self.order,
                "prompt_version": self.prompt_version, "usage": None if self.usage is None else vars(self.usage)}


class Reranker(Protocol):
    name: str

    def rerank(self, query: str, candidates: Sequence[dict], top_k: int) -> RerankOutcome:
        """Order the candidate chunks (stored chunk dicts) for the query; return indexes into `candidates`, best first."""
        ...


def format_passages(candidates: Sequence[dict]) -> str:
    blocks = []
    for number, chunk in enumerate(candidates, start=1):
        text = chunk["text"] if len(chunk["text"]) <= MAX_CANDIDATE_CHARS else chunk["text"][:MAX_CANDIDATE_CHARS] + " …"
        blocks.append(f'<passage id="{number}" title="{chunk["context_header"].replace(chr(34), chr(39))}">\n{text}\n</passage>')
    return "\n".join(blocks)


def clean_order(numbers: Sequence[int], count: int, top_k: int) -> list[int]:
    """Candidate indexes from the model's passage numbers: unknown and repeated numbers dropped, cut to top_k, then
    padded with the remaining candidates in their original order so there are always enough."""
    chosen = list(dict.fromkeys(n - 1 for n in numbers if 1 <= n <= count))[:top_k]
    padding = [i for i in range(count) if i not in chosen]
    return chosen + padding[:max(0, top_k - len(chosen))]


class LLMReranker:
    name = "llm"

    def __init__(self, llm: Runnable, model: str) -> None:
        self.model = model
        self._chain = (ChatPromptTemplate.from_messages([("system", SYSTEM_PROMPT), ("human", HUMAN_PROMPT)]) | llm).with_config(run_name="rerank")  # one named step in a trace

    def rerank(self, query: str, candidates: Sequence[dict], top_k: int) -> RerankOutcome:
        original = list(range(min(top_k, len(candidates))))
        if len(candidates) <= 1:
            return RerankOutcome(original, None, None, 0.0, None)
        started = time.perf_counter()
        try:
            output = self._chain.invoke({"question": query, "passages": format_passages(candidates), "top_k": top_k})
        except OpenAIError as exc:
            return self._fallback(original, started, f"rerank request failed ({type(exc).__name__}: {exc})")
        parsed, error = output.get("parsed"), output.get("parsing_error")
        usage = usage_from_message(output.get("raw"))
        if parsed is None or error is not None:
            return self._fallback(original, started, f"rerank output did not match the expected format: {error}", usage)
        order = clean_order(parsed.ranking, len(candidates), top_k)
        if not any(1 <= n <= len(candidates) for n in parsed.ranking):
            return self._fallback(original, started, "the reranker returned no valid passage numbers", usage)
        return RerankOutcome(order, self.model, usage, (time.perf_counter() - started) * MS_PER_SECOND, None)

    def _fallback(self, order: list[int], started: float, reason: str, usage: Optional[Usage] = None) -> RerankOutcome:
        return RerankOutcome(order, self.model, usage, (time.perf_counter() - started) * MS_PER_SECOND, reason)


def build_rerank_llm(model: Optional[str] = None) -> Runnable:
    chat = ChatOpenAI(model=model or config.rerank_model(), temperature=0, api_key=config.openai_api_key(),
                      max_retries=config.LLM_MAX_RETRIES, timeout=config.LLM_TIMEOUT_SECONDS, max_tokens=MAX_OUTPUT_TOKENS)
    return chat.with_structured_output(Ranking, method="json_schema", strict=True, include_raw=True)


def default_reranker() -> LLMReranker:
    model = config.rerank_model()
    return LLMReranker(build_rerank_llm(model), model)
