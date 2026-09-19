"""Tier 0 — embeddings and retrieval. No network, no API key, no cost."""

from __future__ import annotations

import math

import pytest

from app.embeddings.provider import (
    EMBEDDING_DIMENSIONS,
    FakeEmbeddings,
    get_provider,
)
from app.retrieval.selector import RetrievalSet, RetrievedChunk


# --- dimensions ------------------------------------------------------------


def test_dimensions_are_1024_not_1536():
    """The spec said vector(1536), which presumed OpenAI. Voyage gives 1024."""
    assert EMBEDDING_DIMENSIONS == 1024


def test_dimensions_fit_pgvector_hnsw_limit():
    """HNSW indexes cap at 2000 dims for the `vector` type."""
    assert EMBEDDING_DIMENSIONS <= 2000


def test_matches_migration_schema():
    """A mismatch here means every insert fails at runtime."""
    from pathlib import Path

    from app.config import REPO_ROOT

    sql = (REPO_ROOT / "supabase" / "migrations" / "0001_init.sql").read_text()
    assert f"vector({EMBEDDING_DIMENSIONS})" in sql


# --- fake provider ---------------------------------------------------------


def test_fake_provider_shape():
    provider = FakeEmbeddings()
    vectors = provider.embed_documents(["نص أول", "نص ثانٍ"])
    assert len(vectors) == 2
    assert all(len(v) == EMBEDDING_DIMENSIONS for v in vectors)


def test_fake_provider_is_deterministic():
    a = FakeEmbeddings().embed_documents(["كتاب"])[0]
    b = FakeEmbeddings().embed_documents(["كتاب"])[0]
    assert a == b


def test_fake_vectors_are_normalised():
    vector = FakeEmbeddings().embed_documents(["كتاب"])[0]
    assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0, rel_tol=1e-6)


def test_different_text_gives_different_vectors():
    provider = FakeEmbeddings()
    a = provider.embed_documents(["كتاب"])[0]
    b = provider.embed_documents(["مدرسة"])[0]
    assert a != b


def test_document_and_query_embeddings_differ():
    """Voyage is asymmetric; the fake mirrors that so tests catch a swapped call."""
    provider = FakeEmbeddings()
    assert provider.embed_documents(["كتاب"])[0] != provider.embed_query("كتاب")


def test_empty_list_returns_empty():
    assert FakeEmbeddings().embed_documents([]) == []


def test_provider_falls_back_without_key(monkeypatch):
    """Tier 0 must run with no credentials."""
    get_provider.cache_clear()
    monkeypatch.setattr(
        "app.embeddings.provider.get_settings",
        lambda: type("S", (), {"voyage_api_key": ""})(),
    )
    assert isinstance(get_provider(), FakeEmbeddings)
    get_provider.cache_clear()


# --- retrieval set ---------------------------------------------------------


def chunk(index: int, page: int, text: str = "نص") -> RetrievedChunk:
    return RetrievedChunk(
        id=f"c{index}", chunk_index=index, text=f"{text} {index}",
        page_start=page, page_end=page,
    )


def test_chunk_ids_is_the_grounding_whitelist():
    rs = RetrievalSet(
        chunks=[chunk(1, 1), chunk(2, 2)], resource_id="r1", max_page=2
    )
    assert rs.chunk_ids == {"c1", "c2"}


def test_text_is_joined_in_reading_order():
    """Out-of-order chunks must still read as a coherent passage."""
    rs = RetrievalSet(
        chunks=[chunk(3, 3), chunk(1, 1), chunk(2, 2)], resource_id="r1", max_page=3
    )
    assert rs.text.index("نص 1") < rs.text.index("نص 2") < rs.text.index("نص 3")


def test_empty_retrieval_set():
    rs = RetrievalSet(chunks=[], resource_id="r1", max_page=0)
    assert rs.is_empty
    assert rs.chunk_ids == set()
    assert rs.text == ""


def test_non_empty_set_is_not_empty():
    assert not RetrievalSet(chunks=[chunk(1, 1)], resource_id="r1", max_page=1).is_empty


# --- gate delegation -------------------------------------------------------


class FakeRPC:
    def __init__(self, data):
        self.data = data
        self.calls: list[tuple[str, dict]] = []

    def rpc(self, name, params):
        self.calls.append((name, params))
        outer = self

        class R:
            def execute(self_inner):
                return type("Res", (), {"data": outer.data})()

        return R()


def test_select_window_delegates_to_sql():
    """The gate lives in SQL; Python must not reimplement it."""
    from app.retrieval.selector import select_window

    client = FakeRPC(
        [{"id": "c1", "chunk_index": 1, "text": "نص", "page_start": 5, "page_end": 5}]
    )
    rs = select_window(client, "r1", "u1", window=3)

    name, params = client.calls[0]
    assert name == "select_chunk_window"
    assert params["p_resource_id"] == "r1"
    assert params["p_user_id"] == "u1"
    assert rs.max_page == 5


def test_select_window_handles_no_rows():
    """A learner on page 0, or a failed ingest, yields nothing rather than erroring."""
    from app.retrieval.selector import select_window

    rs = select_window(FakeRPC([]), "r1", "u1")
    assert rs.is_empty


def test_resolve_max_page_delegates():
    from app.retrieval.selector import resolve_max_page

    assert resolve_max_page(FakeRPC(40), "r1", "u1") == 40


def test_resolve_max_page_denies_on_null():
    from app.retrieval.selector import resolve_max_page

    assert resolve_max_page(FakeRPC(None), "r1", "u1") == -1
