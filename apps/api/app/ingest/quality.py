"""Arabic extraction quality gate.

The highest-risk failure in the whole system is a PDF that extracts as garbage,
gets chunked and embedded anyway, and then produces comprehension questions about
text that is not what the book says. The learner answers correctly from the page
and is marked wrong. Spec §5.2 calls this out: hallucinated questions are worse
than no questions.

So ingestion is gated. A resource lands in one of three states:

- ``ok``       — extraction is trustworthy; practice is generated normally.
- ``degraded`` — usable but suspect; the UI warns and the user decides.
- ``failed``   — do not chunk, do not embed, generate nothing.

No OCR in Phase 1. A scanned PDF fails with ``needs_ocr`` recorded, and that is
a deliberate deferral rather than a silent half-ingest.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from app.ingest.arabic_text import (
    arabic_ratio,
    mean_token_length,
    presentation_form_ratio,
)


class IngestStatus(StrEnum):
    PENDING = "pending"
    EXTRACTING = "extracting"
    OK = "ok"
    DEGRADED = "degraded"
    FAILED = "failed"


# --- Thresholds -------------------------------------------------------------
# Tuned to be permissive: a false "failed" blocks a legitimate book, which the
# user notices immediately. A false "ok" poisons practice quietly, which they
# may never trace back. When uncertain, prefer `degraded` over `ok`.

MIN_ARABIC_RATIO = 0.15          # below -> scan, empty page, or Latin junk
MAX_PRESENTATION_RATIO = 0.02    # above -> broken encoding NFKC couldn't repair
MAX_MEAN_TOKEN_LENGTH = 25.0     # above -> spaces were not recovered
MAX_REVERSED_RATIO = 0.40        # above -> visual-order (word order mirrored)
MAX_MIRRORED_RATIO = 0.50        # above -> character-level mirroring
MIN_CHARS_PER_PAGE = 40          # below -> effectively no text layer

# Intra-word fragmentation. Calibrated against a real bilingual poetry PDF that
# measured 11% single-letter tokens and 0.16 orphaned diacritics per token while
# passing every other check. Clean Arabic prose sits near 2-4% / ~0.0.
#
# `degraded` rather than `failed`: the text is still broadly readable and the
# learner may want to keep the resource, but generated practice will quote
# broken words, so they must be told.
DEGRADED_FRAGMENTATION_RATIO = 0.08
FAILED_FRAGMENTATION_RATIO = 0.20
DEGRADED_ORPHAN_HARAKAT_RATIO = 0.05
FAILED_ORPHAN_HARAKAT_RATIO = 0.30

# Words that begin an Arabic phrase. Under correct logical-order extraction they
# appear at the START of a line far more often than at the end. If they keep
# landing at the end, the extractor emitted the line mirrored.
#
# Deliberately conservative: only unambiguous proclitics and prepositions.
_LEADING_WORDS = {"و", "ال", "في", "من", "على", "إلى", "عن", "أن", "إن", "ثم", "أو", "لا"}

_WORD_RE = re.compile(r"[^\s]+")

# --- Character-level mirroring -------------------------------------------
# Some PDFs extract every run fully reversed: both word order AND the letters
# inside each word. Word-position heuristics cannot see this, because reversing
# the line also reverses the particles they look for ("في" arrives as "يف").
#
# The detector is morphological. Arabic words are overwhelmingly *prefixed* by
# the definite article ال and *suffixed* by ة / ي / ا. Reversal inverts that:
# ال lands at the end (as لا) and ة lands at the start. Comparing how often each
# pattern holds in the text versus in its reverse is a reliable discriminator
# that needs no dictionary.

# Letters that frequently END a word but essentially never begin one.
_TERMINAL_ONLY = ("ة", "ى")  # ta marbuta, alef maqsura


def _forward_score(words: list[str]) -> int:
    """Count morphological cues that the text runs in the correct direction."""
    score = 0
    for w in words:
        if len(w) < 3:
            continue
        if w.startswith("ال"):  # ال definite article, word-initial
            score += 1
        if w.endswith(_TERMINAL_ONLY):  # ة / ى word-final
            score += 1
    return score


# --- Intra-word fragmentation --------------------------------------------
# A subtler failure than mirroring: the glyphs and their order are right, but
# spaces are inserted INSIDE words and diacritics are detached from the letters
# they belong to. "فَقُلْتُ" arrives as "فَق لْت", and "نعمة" as "ن عْمَة".
#
# Every earlier check passes on such text — the letters are Arabic, the order is
# logical, word length looks normal — so it reads as clean while actually being
# a bag of fragments. Questions generated from it would quote words that do not
# exist, which is the §5.2 failure mode wearing a different hat.
#
# Two independent signals, because either alone has false positives: Arabic has
# genuine one-letter words (و، ل، ب as proclitics), and a leading harakat can
# legitimately appear after a line break in poetry.

_HARAKAT_CLASS = "ً-ْٰ"
_ORPHAN_HARAKAT = re.compile(f"(?:^|\\s)[{_HARAKAT_CLASS}]")
_ARABIC_LETTER = re.compile("[ؠ-ي]")


def _strip_harakat(text: str) -> str:
    return re.sub(f"[{_HARAKAT_CLASS}]", "", text)


def fragmentation_ratio(text: str) -> float:
    """Share of Arabic tokens that are a single letter once harakat are removed.

    Real Arabic prose runs about 2-4%; anything approaching 10% means spaces were
    inserted inside words.
    """
    tokens = [t for t in text.split() if _ARABIC_LETTER.search(t)]
    if len(tokens) < 20:
        return 0.0
    singles = sum(1 for t in tokens if len(_strip_harakat(t)) == 1)
    return singles / len(tokens)


def orphan_diacritic_ratio(text: str) -> float:
    """Diacritics that follow whitespace instead of a letter, per Arabic token.

    A harakat is a combining mark; it cannot begin a word. Finding them adrift
    means the extractor separated them from their base letter.
    """
    tokens = [t for t in text.split() if _ARABIC_LETTER.search(t)]
    if len(tokens) < 20:
        return 0.0
    return len(_ORPHAN_HARAKAT.findall(text)) / len(tokens)


def mirrored_text_ratio(text: str) -> float:
    """How much more 'Arabic-shaped' the text is when reversed.

    Returns 0.0 when the text reads correctly, and approaches 1.0 when the
    reversed form is clearly the real one. Compares morphological cue counts in
    the text against the same counts in its character-reversed form.
    """
    words = [w for w in _WORD_RE.findall(text) if len(w) >= 3]
    if len(words) < 5:
        return 0.0

    forward = _forward_score(words)
    backward = _forward_score([w[::-1] for w in words])

    total = forward + backward
    if total == 0:
        return 0.0
    if backward <= forward:
        return 0.0
    return (backward - forward) / total


@dataclass
class PageQuality:
    page_number: int
    char_count: int
    arabic_ratio: float
    presentation_ratio: float
    mean_token_length: float
    reversed_ratio: float
    mirrored_ratio: float = 0.0
    fragmentation_ratio: float = 0.0
    orphan_harakat_ratio: float = 0.0

    @property
    def is_empty(self) -> bool:
        return self.char_count < MIN_CHARS_PER_PAGE


@dataclass
class QualityReport:
    """Aggregate verdict across sampled pages. Serialized to `ingest_report`."""

    status: IngestStatus
    reasons: list[str] = field(default_factory=list)
    pages_sampled: int = 0
    pages_empty: int = 0
    mean_arabic_ratio: float = 0.0
    max_presentation_ratio: float = 0.0
    mean_token_length: float = 0.0
    mean_reversed_ratio: float = 0.0
    mean_mirrored_ratio: float = 0.0
    mean_fragmentation_ratio: float = 0.0
    mean_orphan_harakat_ratio: float = 0.0
    needs_ocr: bool = False

    def to_dict(self) -> dict:
        return {
            "status": str(self.status),
            "reasons": self.reasons,
            "pages_sampled": self.pages_sampled,
            "pages_empty": self.pages_empty,
            "mean_arabic_ratio": round(self.mean_arabic_ratio, 4),
            "max_presentation_ratio": round(self.max_presentation_ratio, 4),
            "mean_token_length": round(self.mean_token_length, 2),
            "mean_reversed_ratio": round(self.mean_reversed_ratio, 4),
            "mean_mirrored_ratio": round(self.mean_mirrored_ratio, 4),
            "mean_fragmentation_ratio": round(self.mean_fragmentation_ratio, 4),
            "mean_orphan_harakat_ratio": round(self.mean_orphan_harakat_ratio, 4),
            "needs_ocr": self.needs_ocr,
        }


def reversed_order_ratio(text: str, sample_lines: int = 20) -> float:
    """Fraction of lines ENDING with a word that normally begins a phrase.

    This detects visual-order extraction, where a right-to-left line is emitted
    left-to-right so its first word lands last.

    Important: the remedy is to reject the document, never to reverse it here.
    Extractors generally return logical order, and "helpfully" reversing produces
    double-reversed text that looks plausible and is wrong.
    """
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return 0.0
    lines = lines[:sample_lines]

    hits = 0
    counted = 0
    for line in lines:
        words = _WORD_RE.findall(line)
        if len(words) < 3:
            continue
        counted += 1
        if words[-1] in _LEADING_WORDS:
            hits += 1
    if counted == 0:
        return 0.0
    return hits / counted


def assess_page(page_number: int, text: str) -> PageQuality:
    """Measure one already-normalized page."""
    return PageQuality(
        page_number=page_number,
        char_count=len("".join(text.split())),
        arabic_ratio=arabic_ratio(text),
        presentation_ratio=presentation_form_ratio(text),
        mean_token_length=mean_token_length(text),
        reversed_ratio=reversed_order_ratio(text),
        mirrored_ratio=mirrored_text_ratio(text),
        fragmentation_ratio=fragmentation_ratio(text),
        orphan_harakat_ratio=orphan_diacritic_ratio(text),
    )


def assess_document(pages: list[PageQuality]) -> QualityReport:
    """Aggregate page measurements into an ingest verdict."""
    if not pages:
        return QualityReport(
            status=IngestStatus.FAILED,
            reasons=["no pages could be read from the PDF"],
            needs_ocr=True,
        )

    non_empty = [p for p in pages if not p.is_empty]
    empty_count = len(pages) - len(non_empty)

    report = QualityReport(
        status=IngestStatus.OK,
        pages_sampled=len(pages),
        pages_empty=empty_count,
    )

    # No text layer anywhere: a scan. Defer to OCR (Phase 3), do not half-ingest.
    if not non_empty:
        report.status = IngestStatus.FAILED
        report.needs_ocr = True
        report.reasons.append(
            "no page contains a usable text layer — the PDF is most likely a scan; "
            "OCR is not supported in Phase 1"
        )
        return report

    n = len(non_empty)
    report.mean_arabic_ratio = sum(p.arabic_ratio for p in non_empty) / n
    report.max_presentation_ratio = max(p.presentation_ratio for p in non_empty)
    report.mean_token_length = sum(p.mean_token_length for p in non_empty) / n
    report.mean_reversed_ratio = sum(p.reversed_ratio for p in non_empty) / n
    report.mean_mirrored_ratio = sum(p.mirrored_ratio for p in non_empty) / n
    report.mean_fragmentation_ratio = sum(p.fragmentation_ratio for p in non_empty) / n
    report.mean_orphan_harakat_ratio = sum(p.orphan_harakat_ratio for p in non_empty) / n

    fatal: list[str] = []
    warnings: list[str] = []

    if report.mean_arabic_ratio < MIN_ARABIC_RATIO:
        fatal.append(
            f"only {report.mean_arabic_ratio:.1%} of extracted characters are Arabic "
            f"(minimum {MIN_ARABIC_RATIO:.0%}) — the text layer is missing or not Arabic"
        )
        report.needs_ocr = True

    if report.max_presentation_ratio > MAX_PRESENTATION_RATIO:
        fatal.append(
            f"{report.max_presentation_ratio:.1%} of characters remain Arabic presentation "
            "forms after NFKC — the PDF embeds a broken encoding that cannot be repaired"
        )

    if report.mean_token_length > MAX_MEAN_TOKEN_LENGTH:
        fatal.append(
            f"mean word length is {report.mean_token_length:.0f} characters — "
            "word spacing was not recovered during extraction"
        )

    if report.mean_reversed_ratio > MAX_REVERSED_RATIO:
        fatal.append(
            f"{report.mean_reversed_ratio:.0%} of lines end with a word that should begin "
            "a phrase — the text appears to be in visual rather than logical order"
        )

    if report.mean_mirrored_ratio > MAX_MIRRORED_RATIO:
        fatal.append(
            f"the text reads {report.mean_mirrored_ratio:.0%} more like Arabic when "
            "reversed — the extractor emitted mirrored (visual-order) character runs"
        )

    # Intra-word fragmentation. Severe cases are unusable; milder ones are
    # readable but will make generated practice quote broken words, so the
    # learner is warned rather than silently served bad questions.
    if report.mean_fragmentation_ratio > FAILED_FRAGMENTATION_RATIO:
        fatal.append(
            f"{report.mean_fragmentation_ratio:.0%} of Arabic words extracted as single "
            "letters — word spacing inside words is badly broken"
        )
    elif report.mean_fragmentation_ratio > DEGRADED_FRAGMENTATION_RATIO:
        warnings.append(
            f"{report.mean_fragmentation_ratio:.0%} of Arabic words extracted as single "
            "letters — some words are split mid-word, so questions may quote them oddly"
        )

    if report.mean_orphan_harakat_ratio > FAILED_ORPHAN_HARAKAT_RATIO:
        fatal.append(
            f"{report.mean_orphan_harakat_ratio:.2f} detached diacritics per word — "
            "harakat were separated from their letters"
        )
    elif report.mean_orphan_harakat_ratio > DEGRADED_ORPHAN_HARAKAT_RATIO:
        warnings.append(
            f"{report.mean_orphan_harakat_ratio:.2f} detached diacritics per word — "
            "some vowel marks lost their letter during extraction"
        )

    # Partial damage: enough pages are empty that coverage is unreliable.
    empty_share = empty_count / len(pages)
    if 0.25 < empty_share <= 0.9:
        warnings.append(
            f"{empty_share:.0%} of pages have no usable text layer — "
            "practice will only be drawn from the pages that extracted"
        )
    elif empty_share > 0.9:
        fatal.append(f"{empty_share:.0%} of pages have no usable text layer")
        report.needs_ocr = True

    # Near-threshold values: usable, but worth telling the user about.
    if not fatal:
        if report.mean_arabic_ratio < MIN_ARABIC_RATIO * 2:
            warnings.append(
                f"Arabic character ratio is low ({report.mean_arabic_ratio:.0%}); "
                "extraction quality may be poor"
            )
        if report.mean_reversed_ratio > MAX_REVERSED_RATIO / 2:
            warnings.append("some lines may have extracted in the wrong word order")

    if fatal:
        report.status = IngestStatus.FAILED
        report.reasons = fatal + warnings
    elif warnings:
        report.status = IngestStatus.DEGRADED
        report.reasons = warnings
    else:
        report.reasons = ["extraction looks clean"]

    return report
