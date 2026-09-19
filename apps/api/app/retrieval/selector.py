"""Chunk selection for generation and search.

Everything here delegates the §5.2 position gate to the SQL functions in
``supabase/migrations/0003_functions.sql``. The gate is not reimplemented in
Python, because two implementations drift and one of them eventually leaks.

The important design point (plan §6): **question generation does not use vector
search.** There is no query — the task is "give me a coherent passage the
learner has read". Top-k similarity returns semantically related but
narratively disconnected fragments, which is exactly the input that produces
incoherent comprehension questions. Generation samples a *contiguous* run of
chunks instead; similarity search is for vocab context and Phase 2 thematic
practice.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

log = structlog.get_logger()

DEFAULT_WINDOW = 3


@dataclass(frozen=True)
class RetrievedChunk:
    id: str
    chunk_index: int
    text: str
    page_start: int
    page_end: int
    similarity: float | None = None


@dataclass(frozen=True)
class RetrievalSet:
    """Everything a generation call is allowed to see.

    ``chunk_ids`` is the whitelist the grounding validator checks against: an
    item citing anything outside this set is rejected.
    """

    chunks: list[RetrievedChunk]
    resource_id: str
    max_page: int

    @property
    def chunk_ids(self) -> set[str]:
        return {c.id for c in self.chunks}

    @property
    def text(self) -> str:
        """Concatenated passage, in reading order."""
        return "\n\n".join(c.text for c in sorted(self.chunks, key=lambda c: c.chunk_index))

    @property
    def is_empty(self) -> bool:
        return not self.chunks


def resolve_max_page(client, resource_id: str, user_id: str) -> int:
    """The learner's current ceiling. -1 means no access."""
    result = client.rpc(
        "resolve_max_page", {"p_resource_id": resource_id, "p_user_id": user_id}
    ).execute()
    return int(result.data) if result.data is not None else -1


def select_window(
    client,
    resource_id: str,
    user_id: str,
    window: int = DEFAULT_WINDOW,
    recency_bias: bool = True,
) -> RetrievalSet:
    """Pick a contiguous, in-range passage to generate a question from."""
    result = client.rpc(
        "select_chunk_window",
        {
            "p_resource_id": resource_id,
            "p_user_id": user_id,
            "p_window": window,
            "p_recency_bias": recency_bias,
        },
    ).execute()

    chunks = [
        RetrievedChunk(
            id=row["id"],
            chunk_index=row["chunk_index"],
            text=row["text"],
            page_start=row["page_start"],
            page_end=row["page_end"],
        )
        for row in (result.data or [])
    ]
    max_page = max((c.page_end for c in chunks), default=0)

    if not chunks:
        log.info("no_chunks_available", resource_id=resource_id)

    return RetrievalSet(chunks=chunks, resource_id=resource_id, max_page=max_page)


def search(
    client,
    resource_id: str,
    user_id: str,
    query: str,
    limit: int = 5,
) -> RetrievalSet:
    """Semantic search within what the learner has read.

    For vocab context and Phase 2 thematic practice — not for generating
    comprehension questions (see the module docstring).
    """
    from app.embeddings.provider import get_provider

    embedding = get_provider().embed_query(query)
    result = client.rpc(
        "match_chunks",
        {
            "p_resource_id": resource_id,
            "p_user_id": user_id,
            "p_query_embedding": embedding,
            "p_limit": limit,
        },
    ).execute()

    chunks = [
        RetrievedChunk(
            id=row["id"],
            chunk_index=row["chunk_index"],
            text=row["text"],
            page_start=row["page_start"],
            page_end=row["page_end"],
            similarity=row.get("similarity"),
        )
        for row in (result.data or [])
    ]
    return RetrievalSet(
        chunks=chunks,
        resource_id=resource_id,
        max_page=max((c.page_end for c in chunks), default=0),
    )


def embed_pending_chunks(client, resource_id: str, batch_size: int = 128) -> int:
    """Embed a resource's chunks after ingestion. Returns how many were written.

    Runs in the worker, after the quality gate has passed — there is no point
    embedding text the gate rejected.
    """
    from app.embeddings.provider import get_provider

    provider = get_provider()
    result = (
        client.table("resource_chunks")
        .select("id, text")
        .eq("resource_id", resource_id)
        .is_("embedding", "null")
        .execute()
    )
    rows = result.data or []
    if not rows:
        return 0

    written = 0
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        vectors = provider.embed_documents([r["text"] for r in batch])
        for row, vector in zip(batch, vectors):
            client.table("resource_chunks").update(
                {"embedding": vector, "embedding_model": provider.model}
            ).eq("id", row["id"]).execute()
            written += 1

    log.info("chunks_embedded", resource_id=resource_id, count=written)
    return written
