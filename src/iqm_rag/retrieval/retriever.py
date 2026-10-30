"""Query the vector index and return ranked chunks with source metadata (FR-4).

Retrieval is independent of answer generation: it takes a query string and returns chunks, scores and diagnostics.
It does not decide whether a question is answerable; similarity alone is not proof of that, so the answer step
makes that call from the evidence. Turning a follow-up into a standalone query happens before this step.
"""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.errors import ChromaError

from iqm_rag import config
from iqm_rag.ingestion.embeddings import Embedder, default_embedder
from iqm_rag.ingestion.indexing import IndexMismatchError, open_index, record_to_chunk, stored_dimension

MAX_QUERY_CHARS = 2000  # far below the embedding model's input limit; a longer query is rejected, never truncated
MS_PER_SECOND = 1000.0


class RetrievalError(RuntimeError):
    """The vector search failed."""


@dataclass(frozen=True)
class RetrievedChunk:
    rank: int  # 1 is the closest
    distance: float  # cosine distance as stored by Chroma: 0 is identical
    chunk: dict  # the stored chunk: text, article title and URL, section path, media section IDs, and so on

    @property
    def similarity(self) -> float:
        return 1.0 - self.distance

    def to_dict(self) -> dict:
        return {"rank": self.rank, "distance": self.distance, "similarity": self.similarity, **self.chunk}


@dataclass(frozen=True)
class RetrievalResult:
    query: str
    top_k: int
    embedding_model: str
    embedding_tokens: int
    embed_ms: float
    search_ms: float
    hits: list[RetrievedChunk]

    def to_dict(self) -> dict:
        return {
            "query": self.query, "top_k": self.top_k, "embedding_model": self.embedding_model,
            "embedding_tokens": self.embedding_tokens, "embed_ms": self.embed_ms, "search_ms": self.search_ms,
            "hits": [hit.to_dict() for hit in self.hits],
        }


def _check_query(query: str) -> str:
    text = query.strip()
    if not text:
        raise ValueError("The query is empty.")
    if len(text) > MAX_QUERY_CHARS:
        raise ValueError(f"The query has {len(text)} characters; the limit is {MAX_QUERY_CHARS}.")
    return text


def _check_top_k(top_k: int) -> int:
    if not 1 <= top_k <= config.MAX_TOP_K:
        raise ValueError(f"top_k must be between 1 and {config.MAX_TOP_K}, got {top_k}.")
    return top_k


class Retriever:
    def __init__(self, embedder: Embedder, path: Path = config.CHROMA_DIR, top_k: int = config.DEFAULT_TOP_K) -> None:
        self.top_k = _check_top_k(top_k)
        self._embedder = embedder
        self._collection = open_index(path, embedder.model)
        self._dimension = stored_dimension(self._collection)

    def retrieve(self, query: str, top_k: Optional[int] = None) -> RetrievalResult:
        """The `top_k` chunks closest to the query, closest first."""
        text = _check_query(query)
        k = _check_top_k(self.top_k if top_k is None else top_k)
        vector, tokens, embed_ms = self._embed(text)
        hits, search_ms = self._search(text, vector, k)
        return RetrievalResult(text, k, self._embedder.model, tokens, embed_ms, search_ms, hits)

    def _embed(self, text: str) -> tuple[list[float], int, float]:
        started = time.perf_counter()
        result = self._embedder.embed([text])
        elapsed = (time.perf_counter() - started) * MS_PER_SECOND
        if len(result.vectors) != 1:
            raise RetrievalError(f"Asked for 1 query embedding but received {len(result.vectors)}.")
        vector = result.vectors[0]
        if len(vector) != self._dimension:
            raise IndexMismatchError(
                f"Model {self._embedder.model} returned dimension {len(vector)} but the index holds dimension "
                f"{self._dimension}. Rebuild the index with scripts/index.py --rebuild."
            )
        return vector, result.tokens, elapsed

    def _search(self, query: str, vector: list[float], k: int) -> tuple[list[RetrievedChunk], float]:
        started = time.perf_counter()
        try:
            found = self._collection.query(
                query_embeddings=[vector], n_results=min(k, self._collection.count()),
                include=["documents", "metadatas", "distances"],
            )
        except ChromaError as exc:
            raise RetrievalError(f"Vector search failed for a {len(query)}-character query: {exc}") from exc
        elapsed = (time.perf_counter() - started) * MS_PER_SECOND
        rows = zip(found["ids"][0], found["documents"][0], found["metadatas"][0], found["distances"][0])
        hits = [RetrievedChunk(rank, distance, record_to_chunk(chunk_id, document, metadata))
                for rank, (chunk_id, document, metadata, distance) in enumerate(rows, start=1)]
        return hits, elapsed


def default_retriever() -> Retriever:
    """The retriever configured in the environment (OPENAI_API_KEY, EMBEDDING_MODEL, RETRIEVAL_TOP_K)."""
    return Retriever(default_embedder(), config.CHROMA_DIR, config.retrieval_top_k())
