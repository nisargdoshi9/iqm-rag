"""The LLM judge for answer correctness and faithfulness (FR-9).

For each answered, answerable question the judge gets the key facts, the reference answer, the documents the assistant was
shown and the assistant's answer. It marks each key fact covered or not, and lists the answer's factual claims, each with the
number of the document that supports it and a quote. A claim counts as supported only if the document number is one that was
shown; the quote is checked against that document and reported. The first version (j1) listed only unsupported claims and
compared the answer with the key facts instead of the documents, which gave a false positive on a dev question; j2 makes the
judge point to its evidence. The prompt is strict and unbiased, but the judge is still a model of the same family as the
answerer, so its verdicts are spot-checked by hand. A judge failure is recorded as an error, never turned into a score.
"""

import time
from dataclasses import dataclass
from typing import Optional

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from openai import OpenAIError
from pydantic import BaseModel, Field

from iqm_rag import config
from iqm_rag.evaluation.dataset import normalize_text
from iqm_rag.generation.context import ContextDoc, format_context
from iqm_rag.usage import Usage, usage_from_message

JUDGE_PROMPT_VERSION = "j2"
JUDGE_MAX_OUTPUT_TOKENS = 2500
MS_PER_SECOND = 1000.0

SYSTEM_PROMPT = """# Role and Objective
You are an impartial, critical evaluator of a documentation question-answering assistant. You compare the assistant's answer \
with a checklist of key facts taken from the documentation, and you check whether every claim in the answer is supported by \
the documents the assistant was shown.

# Instructions
- Judge substance only. Ignore tone, length, formatting, politeness and confidence. A longer or more fluent answer is not a \
better one.
- Do not assume the answer is correct because it sounds plausible or sure of itself. Be critical: look for what is missing, \
wrong or invented.
- For each key fact, set covered=true only if the answer states it or says something that clearly means the same. A vague, \
partial, hedged or contradicting statement is covered=false. Never give credit for a fact that appears only in the reference \
answer.
- Treat the reference answer as a guide to what is correct. Accept different wording. Do not penalise extra detail that the \
documents support.
- Check support only against the documents in the Documents section; do not use your own knowledge to decide whether a claim is \
supported, even if it is true in the real world. The key facts are a checklist for correctness only. They are NOT the list of \
claims the answer may make: a claim that a document supports is supported even if it is not a key fact and was not asked for.
- List every distinct factual claim in the answer (steps, names, conditions, numbers, outcomes); skip generic connecting phrases. \
For each claim, give the id number of the document that supports it (supporting_doc) and a short quote copied exactly from that \
document. If no document supports the claim, set supporting_doc to null and the quote to an empty string.
- If the answer contradicts a key fact, set covered=false and say so in the note.
- Keep every note to one short sentence.

# Output Format
fact_checks: one entry per key fact, in the order given (fact, covered, note). claims: every factual claim in the answer, each \
with supporting_doc and quote. comment: one or two sentences on the answer's biggest weakness, or "none"."""

HUMAN_PROMPT = """# Question
{question}

# Key facts
{key_facts}

# Reference answer
{reference}

# Documents the assistant was shown
{context}

# Assistant's answer
{answer}

# Final reminder
Be strict and critical. Judge each key fact on its own. For every claim, find its support in the documents above or mark it unsupported."""


class FactCheck(BaseModel):
    fact: str = Field(description="The key fact, copied from the list.")
    covered: bool = Field(description="True only if the answer states this fact or clearly means the same.")
    note: str = Field(description="One short sentence explaining the judgement.")


class Claim(BaseModel):
    claim: str = Field(description="One factual claim made in the answer.")
    supporting_doc: Optional[int] = Field(description="The id number of the document that supports the claim, or null if no document does.")
    quote: str = Field(description="A short passage copied exactly from that document; an empty string if supporting_doc is null.")


class JudgeVerdict(BaseModel):
    fact_checks: list[FactCheck] = Field(description="One entry per key fact, in the order given.")
    claims: list[Claim] = Field(description="Every factual claim in the answer, each with the document that supports it.")
    comment: str = Field(description="The answer's biggest weakness in one or two sentences, or 'none'.")


@dataclass(frozen=True)
class JudgeResult:
    facts_covered: Optional[int]  # None when the judge failed
    facts_total: int
    faithful: Optional[bool]
    fact_checks: list[dict]
    claims: list[dict]
    unsupported_claims: list[str]
    comment: str
    usage: Optional[Usage]
    model: str
    ms: float
    error: Optional[str]

    def to_dict(self) -> dict:
        return {"facts_covered": self.facts_covered, "facts_total": self.facts_total, "faithful": self.faithful,
                "fact_checks": self.fact_checks, "claims": self.claims, "unsupported_claims": self.unsupported_claims, "comment": self.comment,
                "usage": None if self.usage is None else vars(self.usage), "model": self.model, "ms": round(self.ms, 1),
                "error": self.error}


def should_judge(question: dict, answer) -> bool:
    """Only an answer given to an answerable question has facts to check; abstentions are scored deterministically."""
    return not question["should_abstain"] and answer.status == "answered"


def ground_claims(claims: list[Claim], docs: list[ContextDoc]) -> list[dict]:
    """A claim is supported if the judge named a document that was shown. The quote is checked against that document and
    reported (`quote_found`) so a reviewer can see how well it was grounded; it does not decide the verdict."""
    by_number = {doc.number: doc for doc in docs}
    grounded = []
    for claim in claims:
        doc = by_number.get(claim.supporting_doc) if claim.supporting_doc is not None else None
        found = bool(doc and claim.quote.strip() and normalize_text(claim.quote) in normalize_text(doc.text))
        grounded.append({"claim": claim.claim, "supporting_doc": claim.supporting_doc, "quote": claim.quote,
                         "supported": doc is not None, "quote_found": found})
    return grounded


def build_judge_llm(model: Optional[str] = None) -> Runnable:
    chat = ChatOpenAI(model=model or config.judge_model(), temperature=0, api_key=config.openai_api_key(),
                      max_retries=config.LLM_MAX_RETRIES, timeout=config.LLM_TIMEOUT_SECONDS, max_tokens=JUDGE_MAX_OUTPUT_TOKENS)
    return chat.with_structured_output(JudgeVerdict, method="json_schema", strict=True, include_raw=True)


class Judge:
    def __init__(self, llm: Runnable, model: str) -> None:
        self.model = model
        self._chain = ChatPromptTemplate.from_messages([("system", SYSTEM_PROMPT), ("human", HUMAN_PROMPT)]) | llm

    def evaluate(self, question: dict, answer, tags: tuple[str, ...] = ()) -> JudgeResult:
        facts = question["key_facts"]
        variables = {"question": question["question"], "key_facts": "\n".join(f"{i}. {fact}" for i, fact in enumerate(facts, start=1)),
                     "reference": question["expected_answer"], "context": format_context(answer.docs), "answer": answer.text}
        started = time.perf_counter()
        try:
            output = self._chain.invoke(variables, config={"run_name": "judge", "tags": ["eval", "judge", *tags]})
        except OpenAIError as exc:
            return self._failed(len(facts), f"The judge call failed: {type(exc).__name__}: {exc}", None, started)
        usage = usage_from_message(output.get("raw"))
        verdict = output.get("parsed")
        if verdict is None or output.get("parsing_error") is not None:
            return self._failed(len(facts), f"The judge's output did not match the expected format: {output.get('parsing_error')}", usage, started)
        if len(verdict.fact_checks) != len(facts):
            return self._failed(len(facts), f"The judge returned {len(verdict.fact_checks)} fact checks for {len(facts)} key facts.", usage, started)
        if not verdict.claims:
            return self._failed(len(facts), "The judge listed no claims for the answer, so its faithfulness cannot be assessed.", usage, started)
        checks = [{"fact": fact, "covered": check.covered, "note": check.note} for fact, check in zip(facts, verdict.fact_checks)]
        claims = ground_claims(verdict.claims, answer.docs)
        unsupported = [c["claim"] for c in claims if not c["supported"]]
        return JudgeResult(sum(1 for c in checks if c["covered"]), len(facts), not unsupported, checks, claims, unsupported, verdict.comment,
                           usage, self.model, (time.perf_counter() - started) * MS_PER_SECOND, None)

    def _failed(self, total: int, error: str, usage: Optional[Usage], started: float) -> JudgeResult:
        return JudgeResult(None, total, None, [], [], [], "", usage, self.model, (time.perf_counter() - started) * MS_PER_SECOND, error)


def default_judge() -> Judge:
    model = config.judge_model()
    return Judge(build_judge_llm(model), model)
