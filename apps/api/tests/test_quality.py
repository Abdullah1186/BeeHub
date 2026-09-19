"""Tier 0 — extraction quality gate. No network, no API key, no cost.

Each test synthesises one real-world failure mode. If these pass and a real PDF
still ingests as garbage, a threshold is wrong — not the structure.
"""

from __future__ import annotations

from app.ingest.arabic_text import normalize_for_display
from app.ingest.quality import (
    IngestStatus,
    assess_document,
    assess_page,
    mirrored_text_ratio,
    reversed_order_ratio,
)

GOOD_PAGE = (
    "ذَهَبَ الوَلَدُ إلى المَدرَسَةِ في الصَّباحِ الباكِرِ، وَكانَ الطَّقسُ جَميلاً.\n"
    "قَرَأَ الطّالِبُ كِتاباً جَديداً عَنْ تاريخِ الأندَلُسِ وَحَضارَتِها.\n"
    "كَتَبَ المُعَلِّمُ الدَّرسَ عَلى السَّبّورَةِ ثُمَّ شَرَحَهُ لِلطُّلّابِ بِوُضوحٍ.\n"
    "في الحَديقَةِ أشجارٌ كَثيرَةٌ وَأزهارٌ جَميلَةٌ تَنمو في كُلِّ مَكانٍ.\n"
)


def pages_of(text: str, count: int = 5):
    return [assess_page(i, normalize_for_display(text)) for i in range(1, count + 1)]


def test_clean_document_passes():
    report = assess_document(pages_of(GOOD_PAGE))
    assert report.status is IngestStatus.OK
    assert report.needs_ocr is False


def test_scanned_pdf_fails_and_flags_ocr():
    """No text layer at all — the classic scanned book."""
    report = assess_document(pages_of("", 5))
    assert report.status is IngestStatus.FAILED
    assert report.needs_ocr is True
    assert any("scan" in r.lower() or "text layer" in r.lower() for r in report.reasons)


def test_no_pages_fails():
    report = assess_document([])
    assert report.status is IngestStatus.FAILED
    assert report.needs_ocr is True


def test_latin_only_document_fails():
    """A non-Arabic PDF, or an extractor that produced mojibake."""
    latin = "The quick brown fox jumps over the lazy dog. " * 20
    report = assess_document(pages_of(latin))
    assert report.status is IngestStatus.FAILED
    assert any("Arabic" in r for r in report.reasons)


def test_broken_encoding_fails():
    """Presentation forms surviving NFKC mean an unrepairable custom encoding.

    Uses U+FDFF, which has no NFKC decomposition, unlike the lam-alef ligatures.
    """
    broken = "﷿" * 200
    pages = [assess_page(i, broken) for i in range(1, 4)]
    report = assess_document(pages)
    assert report.status is IngestStatus.FAILED
    assert any("presentation form" in r.lower() for r in report.reasons)


def test_missing_spaces_fails():
    """Extractor recovered glyphs but no word spacing."""
    run_on = "كتابمدرسةطالبمعلمدرسجديدقراءةكتابةحديقةشجرةزهرةجميلةكبيرة" * 6
    pages = [assess_page(i, run_on) for i in range(1, 4)]
    report = assess_document(pages)
    assert report.status is IngestStatus.FAILED
    assert any("word length" in r.lower() or "spacing" in r.lower() for r in report.reasons)


def test_visual_order_extraction_is_detected():
    """Mirrored lines put leading particles at the end."""
    mirrored = "\n".join(["المدرسة إلى الولد ذهب و"] * 12)
    assert reversed_order_ratio(mirrored) > 0.9
    pages = [assess_page(i, mirrored) for i in range(1, 4)]
    report = assess_document(pages)
    assert report.status is IngestStatus.FAILED
    assert any("order" in r.lower() for r in report.reasons)


def test_good_text_is_not_flagged_as_reversed():
    """Guard against a false positive that would block legitimate books."""
    assert reversed_order_ratio(normalize_for_display(GOOD_PAGE)) < 0.4


# --- Character-level mirroring ------------------------------------------
# Regression tests for a real bug: a PDF built with an Arabic font extracted
# fully reversed (word order AND letters within each word). The word-position
# heuristic could not see it, because reversing the line also reverses the
# particles it looks for ("في" arrives as "يف"), so the gate passed garbage.


def test_mirrored_extraction_is_detected():
    mirrored = normalize_for_display(GOOD_PAGE)[::-1]
    assert mirrored_text_ratio(mirrored) > 0.5


def test_correct_text_is_not_flagged_as_mirrored():
    assert mirrored_text_ratio(normalize_for_display(GOOD_PAGE)) == 0.0


def test_mirrored_document_fails_the_gate():
    mirrored = normalize_for_display(GOOD_PAGE)[::-1]
    report = assess_document([assess_page(i, mirrored) for i in range(1, 4)])
    assert report.status is IngestStatus.FAILED
    assert any("reversed" in r.lower() or "mirrored" in r.lower() for r in report.reasons)


def test_mirrored_ratio_ignores_tiny_samples():
    """Too few words to judge — must not guess."""
    assert mirrored_text_ratio("كتاب جديد") == 0.0


def test_mirrored_ratio_handles_latin():
    assert mirrored_text_ratio("the quick brown fox jumps over a lazy dog") == 0.0


def test_partially_empty_document_is_degraded_not_failed():
    """Half the pages are images; the rest are fine. Usable with a warning."""
    pages = [assess_page(i, normalize_for_display(GOOD_PAGE)) for i in range(1, 6)]
    pages += [assess_page(i, "") for i in range(6, 10)]
    report = assess_document(pages)
    assert report.status is IngestStatus.DEGRADED
    assert report.pages_empty == 4


def test_mostly_empty_document_fails():
    pages = [assess_page(1, normalize_for_display(GOOD_PAGE))]
    pages += [assess_page(i, "") for i in range(2, 22)]
    report = assess_document(pages)
    assert report.status is IngestStatus.FAILED


def test_report_serializes():
    report = assess_document(pages_of(GOOD_PAGE))
    d = report.to_dict()
    assert d["status"] == "ok"
    assert isinstance(d["reasons"], list)
    assert isinstance(d["needs_ocr"], bool)
    import json

    json.dumps(d)  # must be JSONB-safe


def test_short_lines_do_not_skew_reversed_ratio():
    """Headings and page numbers have <3 words and must not be counted."""
    assert reversed_order_ratio("و\nال\nفي\n") == 0.0
