"""Embedding model access (FR-3). The model name is configuration; changing it requires rebuilding the index."""

from dataclasses import dataclass
from typing import Iterator, Optional, Protocol, Sequence, TypeVar

from openai import OpenAI, OpenAIError

from iqm_rag import config

BATCH_SIZE = 100  # chunks per request: one batch is at most about 70k tokens, far below the request limit
MAX_RETRIES = 3  # the OpenAI client retries rate limits, timeouts and 5xx errors with backoff
REQUEST_TIMEOUT_SECONDS = 60.0

T = TypeVar("T")


class EmbeddingError(RuntimeError):
    """An embedding request failed. Batches already stored are kept; re-running resumes."""


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    tokens: int  # tokens billed for the request, as reported by the provider


class Embedder(Protocol):
    model: str

    def embed(self, texts: list[str]) -> EmbeddingResult: ...


def batched(items: Sequence[T], size: int) -> Iterator[list[T]]:
    for start in range(0, len(items), size):
        yield list(items[start:start + size])


class OpenAIEmbedder:
    def __init__(self, api_key: str, model: str, client: Optional[OpenAI] = None) -> None:
        self.model = model
        self._client = client or OpenAI(api_key=api_key, max_retries=MAX_RETRIES, timeout=REQUEST_TIMEOUT_SECONDS)

    def embed(self, texts: list[str]) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult(vectors=[], tokens=0)
        if any(not text.strip() for text in texts):
            raise ValueError("Cannot embed an empty text; the provider rejects it.")
        try:
            response = self._client.embeddings.create(model=self.model, input=texts)
        except OpenAIError as exc:
            raise EmbeddingError(
                f"Embedding request failed ({len(texts)} texts, model {self.model}): {type(exc).__name__}: {exc}"
            ) from exc
        data = sorted(response.data, key=lambda item: item.index)
        if len(data) != len(texts):
            raise EmbeddingError(f"Asked for {len(texts)} embeddings but received {len(data)}.")
        return EmbeddingResult(vectors=[item.embedding for item in data], tokens=response.usage.total_tokens)


def default_embedder() -> OpenAIEmbedder:
    """The embedder configured in the environment (OPENAI_API_KEY, EMBEDDING_MODEL)."""
    return OpenAIEmbedder(config.openai_api_key(), config.embedding_model())
