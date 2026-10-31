"""Build and persist the Chroma vector index from chunks (FR-3).

Ingestion is separate from query time. Chunk IDs are deterministic and each record stores the content hash of the
embedded text, so a re-run embeds only new or changed chunks and deletes chunks that no longer exist. Every batch is
stored as soon as it is embedded, so a failure keeps earlier progress and a re-run resumes.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings

from iqm_rag.ingestion.chunking import embedding_text, estimate_tokens, ChunkingConfig
from iqm_rag.ingestion.embeddings import BATCH_SIZE, Embedder, EmbeddingError, batched

COLLECTION_NAME = "iqm_help_center"
CHROMA_SETTINGS = Settings(anonymized_telemetry=False)
LIST_FIELDS = ("section_path", "section_ids", "media_section_ids")  # stored as JSON strings: portable scalar metadata
NULLABLE_FIELDS = ("collection", "last_updated")  # stored as "" because metadata values cannot be None
PLAIN_FIELDS = ("article_id", "article_title", "article_url", "chunk_index", "part", "parts", "context_header",
                "token_estimate", "content_hash")


class IndexMismatchError(RuntimeError):
    """The existing index was built with a different embedding model or dimension. Re-run with rebuild."""


class IndexNotBuiltError(RuntimeError):
    """There is no usable index to query. Build it with scripts/index.py."""


@dataclass
class IndexPlan:
    to_embed: list[dict]
    unchanged: int
    updated: int
    stale_ids: list[str]


# --- Planning and metadata ---------------------------------------------------------------------------


def plan_index(chunks: list[dict], existing: dict[str, str]) -> IndexPlan:
    """Compare chunks with the stored {chunk_id: content_hash} to find what must be embedded or deleted."""
    ids = [chunk["chunk_id"] for chunk in chunks]
    if len(ids) != len(set(ids)):
        raise ValueError("Chunks contain duplicate chunk_id values; the index would silently overwrite records.")
    to_embed, unchanged, updated = [], 0, 0
    for chunk in chunks:
        stored_hash = existing.get(chunk["chunk_id"])
        if stored_hash == chunk["content_hash"]:
            unchanged += 1
            continue
        updated += stored_hash is not None
        to_embed.append(chunk)
    return IndexPlan(to_embed, unchanged, updated, sorted(set(existing) - set(ids)))


def chunk_metadata(chunk: dict) -> dict:
    metadata = {name: chunk[name] for name in PLAIN_FIELDS}
    metadata.update({f"{name}_json": json.dumps(chunk[name], ensure_ascii=False) for name in LIST_FIELDS})
    metadata.update({name: chunk.get(name) or "" for name in NULLABLE_FIELDS})
    return metadata


def record_to_chunk(chunk_id: str, document: str, metadata: dict) -> dict:
    """Rebuild a chunk from a stored record (used by retrieval)."""
    chunk = {name: metadata[name] for name in PLAIN_FIELDS}
    chunk.update({name: json.loads(metadata[f"{name}_json"]) for name in LIST_FIELDS})
    chunk.update({name: metadata[name] or None for name in NULLABLE_FIELDS})
    chunk.update({"chunk_id": chunk_id, "text": document})
    return chunk


# --- Chroma access -----------------------------------------------------------------------------------


def _client(path: Path) -> chromadb.ClientAPI:
    return chromadb.PersistentClient(path=str(path), settings=CHROMA_SETTINGS)


def _get_collection(client: chromadb.ClientAPI, model: str) -> Optional[chromadb.Collection]:
    try:
        collection = client.get_collection(COLLECTION_NAME, embedding_function=None)
    except (chromadb.errors.NotFoundError, ValueError):
        return None
    stored = (collection.metadata or {}).get("embedding_model")
    if stored != model:
        raise IndexMismatchError(
            f"The index was built with embedding model {stored!r} but the configured model is {model!r}. "
            "Vectors from different models are not comparable; re-run with --rebuild to re-embed everything."
        )
    return collection


def _create_collection(client: chromadb.ClientAPI, model: str) -> chromadb.Collection:
    return client.create_collection(
        COLLECTION_NAME,
        metadata={"embedding_model": model},
        configuration={"hnsw": {"space": "cosine"}},
        embedding_function=None,
    )


def _delete_collection(client: chromadb.ClientAPI) -> None:
    try:
        client.delete_collection(COLLECTION_NAME)
    except (chromadb.errors.NotFoundError, ValueError):
        pass


def _stored_hashes(collection: chromadb.Collection) -> dict[str, str]:
    records = collection.get(include=["metadatas"])
    return {chunk_id: meta["content_hash"] for chunk_id, meta in zip(records["ids"], records["metadatas"])}


def stored_dimension(collection: chromadb.Collection) -> Optional[int]:
    records = collection.get(limit=1, include=["embeddings"])
    return len(records["embeddings"][0]) if len(records["ids"]) else None


def _check_dimension(vectors: list[list[float]], expected: Optional[int], model: str) -> int:
    sizes = {len(vector) for vector in vectors}
    if len(sizes) != 1:
        raise EmbeddingError(f"Model {model} returned vectors of inconsistent sizes: {sorted(sizes)}.")
    size = sizes.pop()
    if expected is not None and size != expected:
        raise IndexMismatchError(
            f"Model {model} returned dimension {size} but the index holds dimension {expected}. Re-run with --rebuild."
        )
    return size


def _embed_and_store(collection: chromadb.Collection, chunks: list[dict], embedder: Embedder) -> tuple[int, Optional[int], int]:
    tokens, batches = 0, 0
    dimension = stored_dimension(collection)
    for batch in batched(chunks, BATCH_SIZE):
        result = embedder.embed([embedding_text(chunk) for chunk in batch])
        if len(result.vectors) != len(batch):
            raise EmbeddingError(f"Asked for {len(batch)} embeddings but received {len(result.vectors)}.")
        dimension = _check_dimension(result.vectors, dimension, embedder.model)
        collection.upsert(
            ids=[chunk["chunk_id"] for chunk in batch],
            embeddings=result.vectors,
            documents=[chunk["text"] for chunk in batch],
            metadatas=[chunk_metadata(chunk) for chunk in batch],
        )
        tokens += result.tokens
        batches += 1
    return tokens, dimension, batches


def open_index(path: Path, model: str) -> chromadb.Collection:
    """The existing collection for querying. Refuses a missing or empty index and one built with another model."""
    if not path.exists():
        raise IndexNotBuiltError(f"No index found at {path}. Build it with scripts/chunk.py then scripts/index.py.")
    collection = _get_collection(_client(path), model)
    if collection is None:
        raise IndexNotBuiltError(f"The index at {path} has no collection {COLLECTION_NAME!r}. Run scripts/index.py.")
    if collection.count() == 0:
        raise IndexNotBuiltError(f"The index at {path} is empty. Run scripts/index.py.")
    return collection


# --- Running -----------------------------------------------------------------------------------------


def _open_for_update(path: Path, model: str, rebuild: bool, dry_run: bool) -> Optional[chromadb.Collection]:
    """The existing collection, or None if there is none (or it is being rebuilt). A dry run never writes."""
    if not path.exists():
        return None
    client = _client(path)
    if rebuild:
        if not dry_run:
            _delete_collection(client)
        return None
    return _get_collection(client, model)


def _dry_run_report(plan: IndexPlan, chunks: list[dict], model: str, path: Path) -> dict:
    cfg = ChunkingConfig()
    estimated = sum(estimate_tokens(embedding_text(chunk), cfg) for chunk in plan.to_embed)
    return {"dry_run": True, "embedding_model": model, "chunks": len(chunks), "would_embed": len(plan.to_embed),
            "unchanged": plan.unchanged, "would_delete": len(plan.stale_ids), "estimated_tokens": estimated,
            "index_path": str(path)}


def run_indexing(chunks: list[dict], embedder: Embedder, path: Path, rebuild: bool = False, dry_run: bool = False) -> dict:
    """Embed new or changed chunks into the Chroma index at `path` and delete chunks that no longer exist."""
    collection = _open_for_update(path, embedder.model, rebuild, dry_run)
    plan = plan_index(chunks, _stored_hashes(collection) if collection else {})
    if dry_run:
        return _dry_run_report(plan, chunks, embedder.model, path)
    if collection is None:
        path.mkdir(parents=True, exist_ok=True)
        collection = _create_collection(_client(path), embedder.model)
    tokens, dimension, batches = _embed_and_store(collection, plan.to_embed, embedder)
    if plan.stale_ids:
        collection.delete(ids=plan.stale_ids)
    return {
        "collection": COLLECTION_NAME, "embedding_model": embedder.model, "dimension": dimension or stored_dimension(collection),
        "chunks": len(chunks), "added": len(plan.to_embed) - plan.updated, "updated": plan.updated,
        "unchanged": plan.unchanged, "deleted": len(plan.stale_ids), "embedded_tokens": tokens, "batches": batches,
        "index_path": str(path),
    }
