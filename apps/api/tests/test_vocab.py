"""Tier 0 — vocabulary harvesting guards. No network, no API key, no cost."""

from __future__ import annotations

import pytest

from app.api.vocab import _is_intact_word


@pytest.mark.parametrize(
    ("word", "pos"),
    [
        ("كتاب", "noun"),
        ("حملها", "verb"),
        ("الباكِر", "adjective"),      # diacritics are fine
        ("صافِيا", "adjective"),
        ("فَرَدَّنا", "verb"),          # heavy vocalisation is fine
    ],
)
def test_intact_words_accepted(word, pos):
    assert _is_intact_word(word, pos)


@pytest.mark.parametrize(
    ("word", "pos"),
    [
        # Real output from harvesting a fragmented PDF. Each piece is long
        # enough to pass a naive length check, which is why part-of-speech
        # decides instead.
        ("نحمل ها", "verb"),
        ("تَز ور ها", "verb"),
        ("فَق لْت", "verb"),
        ("ن عْمَة", "noun"),
        ("ر", "noun"),              # single letter
        ("", "noun"),               # empty
        ("   ", "noun"),
    ],
)
def test_fragmented_words_rejected(word, pos):
    assert not _is_intact_word(word, pos)


@pytest.mark.parametrize("phrase", ["في القدس", "أخذ حماما", "على الرغم من"])
def test_phrases_may_have_spaces(phrase):
    """`phrase` exists for idioms; only they may be multi-token."""
    assert _is_intact_word(phrase, "phrase")


def test_phrase_still_rejects_fragments():
    assert not _is_intact_word("ن عْمَة", "phrase")


def test_phrase_length_capped():
    """A whole sentence is not a vocabulary card."""
    assert not _is_intact_word("ذهب الولد إلى المدرسة في الصباح", "phrase")


def test_missing_pos_treated_as_single_word():
    assert _is_intact_word("كتاب")
    assert not _is_intact_word("نحمل ها")
