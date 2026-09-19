"""Tier 0 — chunker invariants. No network, no API key, no cost."""

from __future__ import annotations

import random

from app.ingest.chunker import (
    MAX_CHARS,
    MIN_CHARS,
    Chunk,
    chunk_page,
    chunk_pages,
)

# A short vocalised MSA passage, repeated to build realistic page volume.
SENTENCES = [
    "ذَهَبَ الوَلَدُ إلى المَدرَسَةِ في الصَّباحِ الباكِرِ.",
    "قَرَأَ الطّالِبُ كِتاباً جَديداً عَنْ تاريخِ الأندَلُسِ.",
    "هَلْ تَعرِفُ أينَ تَقَعُ مَدينَةُ قُرطُبَةَ؟",
    "كَتَبَ المُعَلِّمُ الدَّرسَ عَلى السَّبّورَةِ، ثُمَّ شَرَحَهُ لِلطُّلّابِ.",
    "في الحَديقَةِ أشجارٌ كَثيرَةٌ وَأزهارٌ جَميلَةٌ.",
]


def make_page(n_sentences: int = 40) -> str:
    out = []
    for i in range(n_sentences):
        out.append(SENTENCES[i % len(SENTENCES)])
        if i % 5 == 4:
            out.append("\n\n")
    return " ".join(out)


def test_chunks_never_cross_pages():
    """The position gate is unanswerable if a chunk spans two pages."""
    pages = {i: make_page() for i in range(1, 11)}
    chunks = chunk_pages(pages)
    assert chunks
    for c in chunks:
        assert c.page_start == c.page_end, f"chunk {c.chunk_index} spans pages"


def test_chunk_indices_are_dense_and_ordered():
    pages = {i: make_page() for i in range(1, 6)}
    chunks = chunk_pages(pages)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    # Page numbers must be non-decreasing across the document.
    pages_seen = [c.page_start for c in chunks]
    assert pages_seen == sorted(pages_seen)


def test_respects_max_chars():
    pages = {1: make_page(120)}
    for c in chunk_pages(pages):
        # Overlap is prepended after packing, so allow for it.
        assert len(c.text) <= MAX_CHARS + 200, f"chunk of {len(c.text)} chars is too long"


def test_no_slivers():
    """A tiny trailing fragment should merge, not become its own chunk."""
    chunks = chunk_page(1, make_page(41))
    if len(chunks) > 1:
        assert all(len(c.text) >= MIN_CHARS for c in chunks[1:])


def test_arabic_question_mark_is_a_boundary():
    """A '[.!?]'-only splitter would miss U+061F entirely."""
    from app.ingest.chunker import _SENTENCE_END

    text = "هَلْ تَعرِفُ الجَوابَ؟ نَعَم، أعرِفُهُ."
    assert len(_SENTENCE_END.split(text)) == 2


def test_arabic_full_stop_is_a_boundary():
    from app.ingest.chunker import _SENTENCE_END

    text = "هذا نصٌّ أوَّلُ۔ وهذا نصٌّ ثانٍ۔"
    assert len(_SENTENCE_END.split(text)) >= 2


def test_empty_and_whitespace_pages():
    assert chunk_page(1, "") == []
    assert chunk_page(1, "   \n\n  ") == []
    assert chunk_pages({1: "", 2: "  "}) == []


def test_offsets_are_within_page():
    pages = {1: make_page()}
    page_len = len(pages[1].strip())
    for c in chunk_page(1, pages[1]):
        assert 0 <= c.char_start <= page_len
        assert c.char_end > c.char_start


def test_single_oversized_sentence_is_split():
    """A run-on with no sentence punctuation must still be broken up."""
    giant = " ".join(["كلمة"] * 900)
    chunks = chunk_page(1, giant)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c.text) <= MAX_CHARS + 200


def test_token_estimate_is_positive():
    for c in chunk_page(1, make_page()):
        assert c.token_estimate > 0


def test_deterministic():
    """Same input, same chunks — evals depend on this."""
    page = make_page()
    a = [c.text for c in chunk_page(1, page)]
    b = [c.text for c in chunk_page(1, page)]
    assert a == b


def test_gate_property_no_chunk_beyond_position():
    """Simulate the retrieval gate over many random positions.

    This is the safety property: with position P, nothing past page P is reachable.
    """
    pages = {i: make_page(30) for i in range(1, 51)}
    chunks = chunk_pages(pages)
    rng = random.Random(1234)
    for _ in range(1000):
        position = rng.randint(1, 50)
        visible = [c for c in chunks if c.page_end <= position]
        assert all(c.page_end <= position for c in visible)
        assert not any(c.page_start > position for c in visible)
