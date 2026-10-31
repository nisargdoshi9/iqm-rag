"""The retrieval pipeline: vector search, optional keyword search and fusion, optional reranking, optional neighbours.

Every stage after plain vector search is a switch, so the same questions can be run with and without it and the
difference measured. The pipeline has the same interface as `Retriever` (`retrieve`, `top_k`, `embedding_model`,
`chunk_count`), so the answer chain does not know which configuration it is running.

    dense                      vector search, top k
    hybrid                     vector + BM25 search (candidates each), fused with reciprocal rank fusion, top k
    + rerank llm               the fused (or dense) candidates are reordered by a language model, top k
    + neighbours               the adjacent parts of any split section among the top k are added to the context
"""

import time
from dataclasses import dataclass, replace
from typing import Optional

from langsmith import traceable

from iqm_rag import config
from iqm_rag.observability.tracing import retrieval_documents
from iqm_rag.retrieval.fusion import reciprocal_rank_fusion
from iqm_rag.retrieval.keyword import KeywordIndex
from iqm_rag.retrieval.rerank import Reranker, default_reranker
from iqm_rag.retrieval.retriever import RetrievedChunk, RetrievalResult, Retriever, default_retriever

MAX_NEIGHBOURS = 8  # at most this many neighbouring parts are added to the context
MS_PER_SECOND = 1000.0


@dataclass(frozen=True)
class RetrievalSettings:
    mode: str = "dense"
    rerank: str = "off"
    neighbours: bool = False
    candidates: int = config.DEFAULT_CANDIDATES

    def __post_init__(self) -> None:
        if self.mode not in config.RETRIEVAL_MODES:
            raise ValueError(f"mode must be one of {config.RETRIEVAL_MODES}, got {self.mode!r}")
        if self.rerank not in config.RERANKERS:
            raise ValueError(f"rerank must be one of {config.RERANKERS}, got {self.rerank!r}")
        if not 1 <= self.candidates <= config.MAX_CANDIDATES:
            raise ValueError(f"candidates must be between 1 and {config.MAX_CANDIDATES}, got {self.candidates}")

    @classmethod
    def from_env(cls) -> "RetrievalSettings":
        return cls(config.retrieval_mode(), config.rerank_mode(), config.neighbour_expansion(), config.retrieval_candidates())

    @property
    def label(self) -> str:
        """A short name for tables and run folders, such as dense, hybrid, hybrid+llm or hybrid+llm+neighbours."""
        parts = [self.mode] + ([] if self.rerank == "off" else [self.rerank]) + (["neighbours"] if self.neighbours else [])
        return "+".join(parts)

    def to_dict(self) -> dict:
        return {"mode": self.mode, "rerank": self.rerank, "neighbours": self.neighbours, "candidates": self.candidates, "label": self.label}


def neighbour_ids(hits: list[RetrievedChunk], limit: int = MAX_NEIGHBOURS) -> list[str]:
    """IDs of the parts next to each hit that belongs to a split section and are not already hits, in hit order."""
    have = {hit.chunk["chunk_id"] for hit in hits}
    wanted: list[str] = []
    for hit in hits:
        chunk = hit.chunk
        if chunk["parts"] <= 1:
            continue
        section = chunk["chunk_id"].rsplit(":p", 1)[0]
        for part in (chunk["part"] - 1, chunk["part"] + 1):
            chunk_id = f"{section}:p{part}"
            if 1 <= part <= chunk["parts"] and chunk_id not in have and chunk_id not in wanted:
                wanted.append(chunk_id)
    return wanted[:limit]


class RetrievalPipeline:
    def __init__(self, retriever: Retriever, settings: Optional[RetrievalSettings] = None, reranker: Optional[Reranker] = None,
                 keyword_index: Optional[KeywordIndex] = None) -> None:
        self.settings = settings or RetrievalSettings()
        self._retriever = retriever
        self._reranker = reranker
        self._keyword = keyword_index
        if self.settings.rerank != "off" and reranker is None:
            raise ValueError("A reranker is needed when reranking is switched on.")

    @property
    def top_k(self) -> int:
        return self._retriever.top_k

    @property
    def embedding_model(self) -> str:
        return self._retriever.embedding_model

    @property
    def chunk_count(self) -> int:
        return self._retriever.chunk_count

    def describe(self) -> dict:
        return {**self.settings.to_dict(), "reranker": getattr(self._reranker, "model", None)}

    def _keyword_index(self) -> KeywordIndex:
        if self._keyword is None:
            self._keyword = KeywordIndex(self._retriever.all_chunks())
        return self._keyword

    @traceable(run_type="chain", name="retrieval_pipeline", process_inputs=lambda inputs: {"query": inputs.get("query"), "settings": inputs["self"].settings.to_dict()},
               process_outputs=retrieval_documents)
    def retrieve(self, query: str, top_k: Optional[int] = None) -> RetrievalResult:
        k = self.top_k if top_k is None else top_k
        plain = self.settings.mode == "dense" and self.settings.rerank == "off"
        depth = k if plain else max(self.settings.candidates, k)
        dense = self._retriever.retrieve(query, top_k=depth)
        steps: dict = {"settings": self.settings.to_dict()}
        if plain:
            ranked, extras = dense.hits[:k], []
        else:
            candidates = self._candidates(dense, steps)
            ranked = self._rerank(dense.query, candidates, k, steps)
            extras = []
        if self.settings.neighbours:
            extras = self._neighbours(ranked, dense.vector, steps)
        return replace(dense, top_k=k, hits=ranked, extra_hits=extras, steps=steps)

    def _candidates(self, dense: RetrievalResult, steps: dict) -> list[RetrievedChunk]:
        """The candidate chunks in order: the dense ranking, or the dense and BM25 rankings fused."""
        if self.settings.mode == "dense":
            steps["candidates"] = len(dense.hits)
            return [replace(hit, scores={"dense_rank": hit.rank}) for hit in dense.hits]
        started = time.perf_counter()
        keyword_hits = self._keyword_index().search(dense.query, self.settings.candidates)
        steps["keyword_ms"] = round((time.perf_counter() - started) * MS_PER_SECOND, 1)
        dense_ids = [hit.chunk["chunk_id"] for hit in dense.hits[:self.settings.candidates]]
        keyword_ids = [hit.chunk_id for hit in keyword_hits]
        fused = reciprocal_rank_fusion([dense_ids, keyword_ids])
        by_id = {hit.chunk["chunk_id"]: hit for hit in dense.hits}
        missing = [chunk_id for chunk_id, _ in fused if chunk_id not in by_id]
        chunks, distances = self._retriever.chunks_by_id(missing), self._retriever.distances(dense.vector, missing)
        dense_rank = {chunk_id: rank for rank, chunk_id in enumerate(dense_ids, start=1)}
        keyword_rank = {chunk_id: rank for rank, chunk_id in enumerate(keyword_ids, start=1)}
        candidates = []
        for rank, (chunk_id, score) in enumerate(fused, start=1):
            known = by_id.get(chunk_id)
            chunk, distance = (known.chunk, known.distance) if known else (chunks[chunk_id], distances[chunk_id])
            candidates.append(RetrievedChunk(rank, distance, chunk, {"dense_rank": dense_rank.get(chunk_id), "keyword_rank": keyword_rank.get(chunk_id), "fused": round(score, 5)}))
        steps.update({"candidates": len(candidates), "keyword_only": sum(1 for c in candidates if c.scores["dense_rank"] is None),
                      "dense_only": sum(1 for c in candidates if c.scores["keyword_rank"] is None)})
        return candidates

    def _rerank(self, query: str, candidates: list[RetrievedChunk], k: int, steps: dict) -> list[RetrievedChunk]:
        pool = candidates[:max(self.settings.candidates, k)]
        if self.settings.rerank == "off":
            order = list(range(min(k, len(pool))))
        else:
            outcome = self._reranker.rerank(query, [hit.chunk for hit in pool], k)
            steps["rerank"] = outcome.to_dict()
            order = outcome.order
        return [replace(pool[i], rank=position, scores={**pool[i].scores, "candidate_rank": pool[i].rank}) for position, i in enumerate(order, start=1)]

    def _neighbours(self, ranked: list[RetrievedChunk], vector: Optional[list[float]], steps: dict) -> list[RetrievedChunk]:
        wanted = neighbour_ids(ranked)
        chunks = self._retriever.chunks_by_id(wanted)
        distances = self._retriever.distances(vector, list(chunks)) if vector is not None else {}
        extras = [RetrievedChunk(len(ranked) + n, distances.get(chunk_id, 1.0), chunks[chunk_id], {"neighbour": True})
                  for n, chunk_id in enumerate((i for i in wanted if i in chunks), start=1)]
        steps["neighbours_added"] = [hit.chunk["chunk_id"] for hit in extras]
        return extras


def default_pipeline(settings: Optional[RetrievalSettings] = None) -> RetrievalPipeline:
    """The pipeline configured in the environment (RETRIEVAL_MODE, RERANK, NEIGHBOURS, RETRIEVAL_CANDIDATES, RERANK_MODEL)."""
    settings = settings or RetrievalSettings.from_env()
    return RetrievalPipeline(default_retriever(), settings, default_reranker() if settings.rerank != "off" else None)
