"""Page-bounded chunking for Arabic text.

Two rules drive the design:

1. **A chunk never crosses a page boundary.** Spec §5.2 requires that practice is
   only generated from material the learner has actually reached. That gate is
   ``page_end <= position_value``, which is unanswerable for a chunk spanning
   pages 40-41 while the learner is on page 40. Ragged chunks at page breaks are
   the price, and it is worth paying.

2. **Sentence splitting must know Arabic punctuation.** Arabic ends questions with
   ``؟`` (U+061F) and separates clauses with ``،`` (U+060C). A ``[.!?]`` splitter
   finds almost no boundaries in Arabic prose and silently degrades to splitting
   mid-sentence on whitespace — which yields incoherent practice passages.

Sizes are in characters, not tokens. At ~700 characters the token variance does
not justify an API round trip per chunk, and Arabic runs roughly 0.45-0.6 tokens
per character, putting a chunk near 350-420 tokens: one or two paragraphs, the
right size for a comprehension question.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TARGET_CHARS = 700
MAX_CHARS = 1000
OVERLAP_CHARS = 120
MIN_CHARS = 80  # below this a trailing fragment is merged back, not emitted

# Sentence terminators: ASCII, Arabic question mark, Arabic full stop (U+06D4),
# and Arabic semicolon (U+061B).
_SENTENCE_END = re.compile(r"(?<=[.!?؟۔؛])\s+")

# Clause separators, used only when a "sentence" still exceeds MAX_CHARS.
# Includes the Arabic comma U+060C.
_CLAUSE_SPLIT = re.compile(r"(?<=[,،:;])\s+")

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")


@dataclass
class Chunk:
    """One retrievable unit. Offsets are relative to the page, not the document."""

    chunk_index: int
    text: str
    page_start: int
    page_end: int
    char_start: int
    char_end: int

    @property
    def token_estimate(self) -> int:
        """Rough token count. Arabic averages ~0.5 tokens/char."""
        return max(1, round(len(self.text) * 0.5))


def _split_paragraph(paragraph: str) -> list[str]:
    """Break one paragraph into pieces no longer than MAX_CHARS.

    Tries paragraph -> sentence -> clause -> whitespace, in that order, so a split
    lands on the most natural boundary available.
    """
    if len(paragraph) <= MAX_CHARS:
        return [paragraph]

    pieces: list[str] = []
    for sentence in _SENTENCE_END.split(paragraph):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) <= MAX_CHARS:
            pieces.append(sentence)
            continue

        # A single sentence over the limit: fall back to clause boundaries.
        for clause in _CLAUSE_SPLIT.split(sentence):
            clause = clause.strip()
            if not clause:
                continue
            if len(clause) <= MAX_CHARS:
                pieces.append(clause)
                continue

            # Last resort: hard-wrap on whitespace.
            words = clause.split()
            buf = ""
            for word in words:
                candidate = f"{buf} {word}".strip()
                if len(candidate) > MAX_CHARS and buf:
                    pieces.append(buf)
                    buf = word
                else:
                    buf = candidate
            if buf:
                pieces.append(buf)
    return pieces


def _accumulate(pieces: list[str]) -> list[str]:
    """Greedily pack pieces up to TARGET_CHARS, then apply overlap."""
    packed: list[str] = []
    buf = ""
    for piece in pieces:
        candidate = f"{buf} {piece}".strip() if buf else piece
        if len(candidate) > TARGET_CHARS and buf:
            packed.append(buf)
            buf = piece
        else:
            buf = candidate
    if buf:
        # Avoid emitting a sliver: merge it into the previous chunk when that
        # keeps the result under the hard cap.
        if packed and len(buf) < MIN_CHARS and len(packed[-1]) + len(buf) + 1 <= MAX_CHARS:
            packed[-1] = f"{packed[-1]} {buf}".strip()
        else:
            packed.append(buf)
    if not packed:
        return []

    # Prepend a tail of the previous chunk so a sentence straddling a boundary is
    # retrievable from both sides.
    if OVERLAP_CHARS <= 0 or len(packed) == 1:
        return packed

    with_overlap = [packed[0]]
    for prev, current in zip(packed, packed[1:]):
        tail = prev[-OVERLAP_CHARS:]
        # Start the overlap at a word boundary so it reads cleanly.
        space = tail.find(" ")
        if space != -1:
            tail = tail[space + 1 :]
        merged = f"{tail} {current}".strip() if tail else current
        with_overlap.append(merged)
    return with_overlap


def chunk_page(page_number: int, text: str, start_index: int = 0) -> list[Chunk]:
    """Chunk a single page. Never emits a chunk spanning pages by construction."""
    text = text.strip()
    if not text:
        return []

    pieces: list[str] = []
    for paragraph in _PARAGRAPH_SPLIT.split(text):
        paragraph = paragraph.strip()
        if paragraph:
            pieces.extend(_split_paragraph(paragraph))

    chunks: list[Chunk] = []
    for offset, body in enumerate(_accumulate(pieces)):
        # Locate the chunk within the page for UI highlighting. Overlap means the
        # prepended tail may not match here; fall back to the unique remainder.
        char_start = text.find(body)
        if char_start == -1:
            probe = body[OVERLAP_CHARS:] if len(body) > OVERLAP_CHARS else body
            char_start = max(text.find(probe), 0)
        chunks.append(
            Chunk(
                chunk_index=start_index + offset,
                text=body,
                page_start=page_number,
                page_end=page_number,
                char_start=char_start,
                char_end=char_start + len(body),
            )
        )
    return chunks


def chunk_pages(pages: dict[int, str]) -> list[Chunk]:
    """Chunk a whole document, page by page, with a document-wide index.

    ``pages`` maps 1-based page number to that page's normalized text.
    """
    chunks: list[Chunk] = []
    for page_number in sorted(pages):
        chunks.extend(chunk_page(page_number, pages[page_number], start_index=len(chunks)))
    return chunks
