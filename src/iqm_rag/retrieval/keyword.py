"""BM25 keyword search over the same chunks the vector index holds (FR-4 extension).

Dense search matches meaning but can miss exact terms such as product names and abbreviations (VLD, PMP, DAAST); BM25
matches those terms exactly. The two are combined in the pipeline. The index is built in memory from the chunks stored
in Chroma, so the keyword and vector searches always cover the same chunks.
"""

import re
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from iqm_rag.ingestion.chunking import embedding_text

TOKEN = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset(
    "a an and are as at be by can do does for from has have how i if in into is it its me my of on or our so than that the "
    "their then there these this to use used using was we what when where which who why will with you your".split()
)


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric words without stopwords. No stemming: product terms are matched as written."""
    return [word for word in TOKEN.findall(text.lower()) if word not in STOPWORDS]


@dataclass(frozen=True)
class KeywordHit:
    chunk_id: str
    score: float


class KeywordIndex:
    def __init__(self, chunks: list[dict]) -> None:
        if not chunks:
            raise ValueError("A keyword index needs at least one chunk.")
        self._ids = [chunk["chunk_id"] for chunk in chunks]
        self._bm25 = BM25Okapi([tokenize(embedding_text(chunk)) for chunk in chunks])

    def __len__(self) -> int:
        return len(self._ids)

    def search(self, query: str, limit: int) -> list[KeywordHit]:
        """The best `limit` chunks by BM25 score, best first. Chunks sharing no word with the query are left out."""
        words = tokenize(query)
        if not words:
            return []
        scores = self._bm25.get_scores(words)
        best = sorted(range(len(scores)), key=lambda i: (-scores[i], i))[:limit]  # ties keep chunk order, so results are repeatable
        return [KeywordHit(self._ids[i], float(scores[i])) for i in best if scores[i] > 0]
