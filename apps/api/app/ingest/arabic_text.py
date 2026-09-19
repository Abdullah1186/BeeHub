"""Arabic text normalization.

Two distinct outputs, per spec §7 ("normalise for search/matching, never for display"):

- ``normalize_for_display`` keeps diacritics and the original letter forms. This is
  what gets stored in ``resource_chunks.text``, shown to the user, and embedded.
- ``normalize_for_search`` strips harakat and folds orthographic variants. This is
  ``resource_chunks.text_normalized``, used only for keyword matching.

Never send the search form to the UI: stripping harakat from a vocalised poetry
line changes what the learner is reading.
"""

from __future__ import annotations

import re
import unicodedata

# Tatweel / kashida: a pure justification glyph carrying no phonetic value.
TATWEEL = "ـ"

# Harakat and other combining marks. U+064B–U+065F covers fathatan..the extended
# marks; U+0670 is the superscript alef (dagger alef).
_HARAKAT = re.compile("[ً-ٰٟ]")

# Quranic annotation signs (U+06D6–U+06ED) — present in religious texts, never
# part of the lexical form.
_QURANIC_MARKS = re.compile("[ۖ-ۭ]")

# Arabic presentation forms. Their presence AFTER NFKC means the PDF embedded a
# broken custom encoding that NFKC could not repair — a quality-gate signal.
PRESENTATION_FORMS = re.compile("[ﭐ-﷿ﹰ-﻿]")

# Arabic script proper (U+0600–U+06FF) plus supplement/extended-A.
ARABIC_LETTERS = re.compile("[ؠ-ي٠-ٯٱ-ۿ]")

_WHITESPACE = re.compile(r"[ \t  ]+")
_BLANK_LINES = re.compile(r"\n{3,}")

# Orthographic folding for search only.
_FOLD_MAP = str.maketrans(
    {
        "أ": "ا",  # أ  alef with hamza above -> alef
        "إ": "ا",  # إ  alef with hamza below -> alef
        "آ": "ا",  # آ  alef with madda      -> alef
        "ٱ": "ا",  # ٱ  alef wasla           -> alef
        "ى": "ي",  # ى  alef maqsura         -> ya
        "ة": "ه",  # ة  ta marbuta           -> ha
        "ؤ": "و",  # ؤ  waw with hamza       -> waw
        "ئ": "ي",  # ئ  ya with hamza        -> ya
        # Arabic-Indic digits -> ASCII, so page/number matching works.
        "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
        "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
    }
)


def normalize_for_display(text: str) -> str:
    """Repair encoding damage while preserving everything a reader sees.

    NFKC is the load-bearing step: it folds Arabic presentation forms (U+FBxx,
    U+FExx) back to base letters. Many PDF extractors emit those isolated/initial/
    medial glyph codepoints instead of the base letter, which would otherwise make
    the text unsearchable, unembeddable, and wrong when copied.

    Diacritics are preserved.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace(TATWEEL, "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WHITESPACE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _BLANK_LINES.sub("\n\n", text)
    return text.strip()


def normalize_for_search(text: str) -> str:
    """Aggressive fold for keyword matching. Never display this output.

    Strips harakat and collapses orthographic variants a learner (or an extractor)
    may render inconsistently, so that e.g. ``كتب`` matches ``كَتَبَ``.
    """
    if not text:
        return ""
    text = normalize_for_display(text)
    text = _HARAKAT.sub("", text)
    text = _QURANIC_MARKS.sub("", text)
    text = text.translate(_FOLD_MAP)
    text = _WHITESPACE.sub(" ", text)
    return text.strip()


def strip_diacritics(text: str) -> str:
    """Remove harakat only, leaving letter forms intact."""
    return _QURANIC_MARKS.sub("", _HARAKAT.sub("", text))


def arabic_ratio(text: str) -> float:
    """Share of non-whitespace characters that are Arabic script.

    A low value means the page is a scan, is empty, or extracted as Latin junk.
    """
    stripped = "".join(text.split())
    if not stripped:
        return 0.0
    return len(ARABIC_LETTERS.findall(stripped)) / len(stripped)


def presentation_form_ratio(text: str) -> float:
    """Share of non-whitespace characters still in presentation-form ranges.

    Computed *after* NFKC. Anything above ~0 means the source embedded a broken
    encoding that normalization could not repair — the text is unreliable.
    """
    stripped = "".join(text.split())
    if not stripped:
        return 0.0
    return len(PRESENTATION_FORMS.findall(stripped)) / len(stripped)


def mean_token_length(text: str) -> float:
    """Mean whitespace-delimited token length.

    A large value is the classic "extractor recovered no spaces" failure, where a
    whole line arrives as one run of letters.
    """
    tokens = text.split()
    if not tokens:
        return 0.0
    return sum(len(t) for t in tokens) / len(tokens)
