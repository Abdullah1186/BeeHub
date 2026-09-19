"""PDF text extraction with per-page attribution.

Page numbers are captured at extraction time and never reconstructed afterwards.
Concatenating a document and mapping offsets back to pages breaks on every
hyphenation and header strip, and the position gate (spec §5.2) depends on the
page number being exactly right.

Uses ``pymupdf`` (the ``fitz`` alias is deprecated). PyMuPDF is the mainstream
Python extractor that handles Arabic best, but it is not reliable enough to
trust blindly — see ``quality.py`` for the gate every document must clear, and
PyMuPDF issue #2199 (wontfix) for the ligature bug that motivates it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf

from app.ingest.arabic_text import normalize_for_display

# Running headers/footers repeat across most pages and add nothing to practice.
HEADER_REPEAT_THRESHOLD = 0.6


@dataclass
class ExtractedDocument:
    pages: dict[int, str]  # 1-based page number -> normalized text
    page_count: int
    removed_boilerplate: list[str]


def _strip_repeating_lines(pages: dict[int, str]) -> tuple[dict[int, str], list[str]]:
    """Drop short lines that repeat on most pages (running heads, page numbers).

    Only single short lines are considered, so a repeated refrain in a poem is
    never mistaken for boilerplate.
    """
    if len(pages) < 4:
        return pages, []

    counts: dict[str, int] = {}
    for text in pages.values():
        for line in {ln.strip() for ln in text.split("\n") if ln.strip()}:
            if len(line) <= 80:
                counts[line] = counts.get(line, 0) + 1

    threshold = len(pages) * HEADER_REPEAT_THRESHOLD
    boilerplate = {line for line, count in counts.items() if count >= threshold}
    if not boilerplate:
        return pages, []

    cleaned = {
        number: "\n".join(
            ln for ln in text.split("\n") if ln.strip() not in boilerplate
        ).strip()
        for number, text in pages.items()
    }
    return cleaned, sorted(boilerplate)


def extract_pdf(path: str | Path) -> ExtractedDocument:
    """Extract and normalize every page of a PDF.

    Returns whatever came out, including empty pages — judging the result is the
    quality gate's job, not this function's.
    """
    pages: dict[int, str] = {}
    with pymupdf.open(path) as doc:
        for index, page in enumerate(doc, start=1):
            # "text" preserves reading order as PyMuPDF determines it. Do not
            # post-process direction here: reversing apparently-backwards Arabic
            # produces double-reversed text that looks plausible and is wrong.
            pages[index] = normalize_for_display(page.get_text("text"))
        page_count = doc.page_count

    pages, removed = _strip_repeating_lines(pages)
    return ExtractedDocument(
        pages=pages, page_count=page_count, removed_boilerplate=removed
    )
