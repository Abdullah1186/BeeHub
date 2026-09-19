"""Tier 0 — full ingestion pipeline against real generated PDFs.

These build actual PDF files rather than mocking extraction, because the bugs
that matter here live in the extractor's interaction with Arabic fonts, not in
our own code. A mocked extractor would have passed the mirrored-text bug that
this suite now guards against.
"""

from __future__ import annotations

import os

import pymupdf
import pytest

from app.ingest.pipeline import ingest_pdf
from app.ingest.quality import IngestStatus

ARABIC_FONTS = [
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
]
FONT = next((f for f in ARABIC_FONTS if os.path.exists(f)), None)

PARAGRAPHS = [
    "ذهب الولد إلى المدرسة في الصباح الباكر وكان الطقس جميلا صافيا.",
    "قرأ الطالب كتابا جديدا عن تاريخ الأندلس وحضارتها العريقة الواسعة.",
    "كتب المعلم الدرس على السبورة ثم شرحه للطلاب بوضوح تام وصبر كبير.",
    "في الحديقة أشجار كثيرة وأزهار جميلة تنمو في كل مكان حول البيت.",
    "سافر التاجر إلى دمشق وحلب لبيع البضائع وشراء الحرير والتوابل.",
]


def _write_pdf(path, lines_per_page, pages=3, font=None, fontsize=13):
    doc = pymupdf.open()
    for p in range(pages):
        page = doc.new_page()
        y = 80
        for i, line in enumerate(lines_per_page):
            if font:
                page.insert_text(
                    (60, y), f"{line} ({p + 1}-{i + 1})",
                    fontfile=font, fontname="ar", fontsize=fontsize,
                )
            else:
                page.insert_text((60, y), f"{line} ({p + 1}-{i + 1})", fontsize=fontsize)
            y += 34
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def blank_pdf(tmp_path):
    """A PDF with pages but no text layer — i.e. a scan."""
    path = tmp_path / "blank.pdf"
    doc = pymupdf.open()
    for _ in range(4):
        doc.new_page()
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def latin_pdf(tmp_path):
    return _write_pdf(
        tmp_path / "latin.pdf",
        ["The quick brown fox jumps over the lazy dog every morning."] * 5,
    )


def test_scanned_pdf_fails_and_requests_ocr(blank_pdf):
    result = ingest_pdf(blank_pdf)
    assert result.status is IngestStatus.FAILED
    assert result.report.needs_ocr is True
    assert result.chunks == []
    assert result.can_generate_practice is False


def test_latin_pdf_fails(latin_pdf):
    result = ingest_pdf(latin_pdf)
    assert result.status is IngestStatus.FAILED
    assert result.chunks == []


def test_failed_document_yields_no_chunks(blank_pdf):
    """The core guarantee: a failed gate cannot leak material into practice."""
    assert ingest_pdf(blank_pdf).chunks == []


@pytest.mark.skipif(FONT is None, reason="no Arabic-capable system font available")
def test_arabic_pdf_extraction_is_checked(tmp_path):
    """Regression guard for the mirrored-extraction bug.

    Writing Arabic with this font produces text that extracts fully reversed.
    The gate must reject it. If a future PyMuPDF extracts it correctly, the
    document passes and must then chunk cleanly — both outcomes are acceptable,
    silently ingesting mirrored text is not.
    """
    path = _write_pdf(tmp_path / "arabic.pdf", PARAGRAPHS, font=FONT)
    result = ingest_pdf(path)

    if result.status is IngestStatus.FAILED:
        assert result.chunks == []
        assert result.report.reasons
    else:
        assert result.chunks
        assert all(c.page_start == c.page_end for c in result.chunks)
        assert result.report.mean_mirrored_ratio <= 0.5


def test_page_count_reported(latin_pdf):
    assert ingest_pdf(latin_pdf).page_count == 3


def test_chunks_carry_valid_page_numbers(latin_pdf):
    result = ingest_pdf(latin_pdf)
    for chunk in result.chunks:
        assert 1 <= chunk.page_start <= result.page_count
        assert chunk.page_start == chunk.page_end
