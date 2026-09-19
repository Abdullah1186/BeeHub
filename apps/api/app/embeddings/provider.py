"""Embedding provider.

Anthropic has no embeddings API, so this is a separate vendor. Voyage's
``voyage-4-lite`` is multilingual with a 32k context, costs $0.02/MTok, and
ships 200M free tokens — enough for all of Phase 1.

**Dimensions: 1024, not the spec's 1536.** 1536 presumed OpenAI. 1024 is a
native Voyage output size and sits safely under pgvector's 2000-dim ceiling for
HNSW indexes (2048 would exceed it and force `halfvec`).

**The asymmetric input_type is the important detail.** Voyage embeds documents
and queries differently — it prepends a different instruction to each — and a
query embedded as a document retrieves measurably worse. That asymmetry is baked
into the interface as two methods rather than left as a keyword argument someone
will eventually forget.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from functools import lru_cache

import structlog

from app.config import get_settings

log = structlog.get_logger()

EMBEDDING_DIMENSIONS = 1024
DEFAULT_MODEL = "voyage-4-lite"

# Voyage accepts up to 1000 texts per call; stay well under to bound latency
# and keep a failed batch cheap to retry.
MAX_BATCH = 128


class EmbeddingProvider(ABC):
    """Two methods, because indexing and searching are not symmetric."""

    model: str
    dimensions: int

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed text being stored and searched over."""

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Embed a search query."""


class VoyageEmbeddings(EmbeddingProvider):
    def __init__(self, model: str = DEFAULT_MODEL, dimensions: int = EMBEDDING_DIMENSIONS):
        import voyageai

        settings = get_settings()
        if not settings.voyage_api_key:
            raise RuntimeError("VOYAGE_API_KEY is not set; see .env.example")

        self.model = model
        self.dimensions = dimensions
        self._client = voyageai.Client(api_key=settings.voyage_api_key)

    def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), MAX_BATCH):
            batch = texts[start : start + MAX_BATCH]
            result = self._client.embed(
                batch,
                model=self.model,
                input_type=input_type,
                output_dimension=self.dimensions,
            )
            vectors.extend(result.embeddings)

        log.info(
            "embedded",
            model=self.model,
            input_type=input_type,
            count=len(texts),
            dimensions=self.dimensions,
        )
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._embed(texts, "document")

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "query")[0]


class FakeEmbeddings(EmbeddingProvider):
    """Deterministic stand-in for tests. Never calls out.

    Vectors are derived from a hash of the text, so identical text embeds
    identically and different text does not collide — enough to exercise storage
    and retrieval plumbing without spending anything or needing a key.
    """

    def __init__(self, dimensions: int = EMBEDDING_DIMENSIONS):
        self.model = "fake"
        self.dimensions = dimensions

    def _vector(self, text: str, salt: str) -> list[float]:
        import hashlib
        import math

        digest = hashlib.sha256(f"{salt}:{text}".encode()).digest()
        raw = [
            (digest[i % len(digest)] / 255.0) - 0.5 for i in range(self.dimensions)
        ]
        norm = math.sqrt(sum(v * v for v in raw)) or 1.0
        return [v / norm for v in raw]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t, "doc") for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text, "query")


@lru_cache
def get_provider() -> EmbeddingProvider:
    """The configured provider, or the fake when no key is present.

    Falling back rather than raising keeps Tier 0 tests runnable with no
    credentials; anything that genuinely needs real vectors fails loudly at the
    point of use instead.
    """
    settings = get_settings()
    if not settings.voyage_api_key:
        log.warning("no VOYAGE_API_KEY set — using deterministic fake embeddings")
        return FakeEmbeddings()
    return VoyageEmbeddings()
