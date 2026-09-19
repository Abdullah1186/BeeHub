"""Tier 0 — Arabic normalization. No network, no API key, no cost."""

from __future__ import annotations

import pytest

from app.ingest.arabic_text import (
    arabic_ratio,
    mean_token_length,
    normalize_for_display,
    normalize_for_search,
    presentation_form_ratio,
    strip_diacritics,
)

VOCALISED = "كَتَبَ الوَلَدُ الدَّرْسَ"


def test_display_preserves_diacritics():
    """Spec §7: store what the source has; never normalise for display."""
    out = normalize_for_display(VOCALISED)
    assert "َ" in out  # fatha survives


def test_search_strips_diacritics():
    out = normalize_for_search(VOCALISED)
    assert "َ" not in out
    assert out == "كتب الولد الدرس"


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("أحمد", "احمد"),   # hamza above
        ("إسلام", "اسلام"),  # hamza below
        ("آمن", "امن"),      # madda
        ("على", "علي"),      # alef maqsura -> ya
        ("مدرسة", "مدرسه"),  # ta marbuta -> ha
        ("مسؤول", "مسوول"),  # hamza on waw
    ],
)
def test_search_folds_orthographic_variants(a: str, b: str):
    assert normalize_for_search(a) == normalize_for_search(b)


def test_nfkc_repairs_presentation_forms():
    """The load-bearing repair: U+FExx glyph codepoints fold to base letters."""
    broken = "ﻟﺎ"  # lam + alef presentation forms
    assert presentation_form_ratio(broken) == 1.0
    fixed = normalize_for_display(broken)
    assert presentation_form_ratio(fixed) == 0.0
    assert fixed == "لا"


def test_tatweel_removed():
    assert normalize_for_display("كــــتاب") == "كتاب"


def test_arabic_indic_digits_folded_for_search():
    # ta-marbuta also folds to ha here; assert the digits specifically.
    assert normalize_for_search("صفحة ٤٢") == "صفحه 42"
    assert normalize_for_search("١٢٣٤٥٦٧٨٩٠") == "1234567890"


def test_empty_input():
    assert normalize_for_display("") == ""
    assert normalize_for_search("") == ""
    assert arabic_ratio("") == 0.0
    assert presentation_form_ratio("") == 0.0
    assert mean_token_length("") == 0.0


def test_arabic_ratio():
    assert arabic_ratio("كتاب") == 1.0
    assert arabic_ratio("hello") == 0.0
    assert 0.0 < arabic_ratio("كتاب book") < 1.0


def test_mean_token_length_detects_missing_spaces():
    assert mean_token_length("كتاب مدرسة طالب") < 10
    assert mean_token_length("كتابمدرسةطالبمعلمدرسجديد") > 20


def test_strip_diacritics_keeps_letter_forms():
    """Unlike the search fold, this must not collapse alef variants."""
    assert strip_diacritics("أَحْمَد") == "أحمد"


def test_whitespace_collapsed_but_paragraphs_kept():
    out = normalize_for_display("سطر   أول\n\n\n\nسطر ثانٍ")
    assert "   " not in out
    assert "\n\n" in out


def test_normalization_is_idempotent():
    once = normalize_for_display(VOCALISED)
    assert normalize_for_display(once) == once
    once_s = normalize_for_search(VOCALISED)
    assert normalize_for_search(once_s) == once_s
