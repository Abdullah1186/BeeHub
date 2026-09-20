"""Tier 0 — grounding enforcement (§5.2). No network, no API key, no cost.

The verbatim-quote check is the one that actually catches hallucination: a model
can echo back chunk IDs it was given while inventing content, but it cannot
reproduce exact Arabic from text that was never there.
"""

from __future__ import annotations

import pytest

from app.generation.validate import validate_question
from app.schemas.grading import ComprehensionQuestion, KeyPoint

PASSAGE = (
    "ذهب الولد إلى المدرسة في الصباح الباكر، وكان الطقس جميلا صافيا. "
    "وفي الطريق التقى بصديقه القديم أحمد، الذي كان يحمل كتابا جديدا عن تاريخ الأندلس."
)
ALLOWED = {"c1", "c2"}


def question(**kw) -> ComprehensionQuestion:
    defaults = dict(
        question_arabic="متى ذهب الولد؟",
        question_english="When did the boy go?",
        key_points=[KeyPoint(id="kp1", text="Early morning.",
                             source_quote="في الصباح الباكر")],
        source_chunk_ids=["c1"],
        difficulty_cefr="A2",
        answerable_from_source=True,
    )
    defaults.update(kw)
    return ComprehensionQuestion(**defaults)


def test_grounded_question_passes():
    assert validate_question(question(), PASSAGE, ALLOWED).ok


def test_fabricated_quote_rejected():
    """The core hallucination check."""
    q = question(key_points=[KeyPoint(id="kp1", text="He rode a horse.",
                                      source_quote="ركب الولد حصانا")])
    result = validate_question(q, PASSAGE, ALLOWED)
    assert not result.ok
    assert "not verbatim" in result.detail


def test_paraphrased_quote_rejected():
    """A near-miss quote is still not verbatim — it must fail."""
    q = question(key_points=[KeyPoint(id="kp1", text="Morning.",
                                      source_quote="في الصباح المبكر")])
    assert not validate_question(q, PASSAGE, ALLOWED).ok


def test_chunk_outside_retrieval_set_rejected():
    q = question(source_chunk_ids=["c1", "c99"])
    result = validate_question(q, PASSAGE, ALLOWED)
    assert not result.ok
    assert "outside the retrieval set" in result.detail


def test_empty_chunk_ids_rejected():
    with pytest.raises(Exception):
        question(source_chunk_ids=[])  # min_length=1 on the model


def test_no_key_points_rejected():
    with pytest.raises(Exception):
        question(key_points=[])  # min_length=1 on the model


def test_empty_question_rejected():
    result = validate_question(question(question_arabic="  "), PASSAGE, ALLOWED)
    assert not result.ok
    assert "empty question" in result.detail


def test_whitespace_differences_tolerated():
    """Line breaks in the passage must not fail an otherwise exact quote."""
    spaced = PASSAGE.replace("، ", "،\n   ")
    assert validate_question(question(), spaced, ALLOWED).ok


def test_diacritic_changes_not_tolerated():
    """A quote that silently 'corrects' the source is not verbatim."""
    q = question(key_points=[KeyPoint(id="kp1", text="Morning.",
                                      source_quote="فِي الصَّباحِ الباكِرِ")])
    assert not validate_question(q, PASSAGE, ALLOWED).ok


def test_refusal_is_valid_output():
    """Declining to ground a question is correct behaviour, not failure."""
    q = ComprehensionQuestion(
        question_arabic="", question_english="",
        key_points=[], source_chunk_ids=["c1"],
        difficulty_cefr="A2", answerable_from_source=False,
    )
    assert validate_question(q, PASSAGE, ALLOWED).ok


def test_refusal_must_be_empty_handed():
    """Cannot claim unanswerable while still returning a question."""
    q = ComprehensionQuestion(
        question_arabic="متى ذهب الولد؟", question_english="When?",
        key_points=[], source_chunk_ids=["c1"],
        difficulty_cefr="A2", answerable_from_source=False,
    )
    result = validate_question(q, PASSAGE, ALLOWED)
    assert not result.ok
    assert "unanswerable" in result.detail


def test_multiple_key_points_all_checked():
    q = question(key_points=[
        KeyPoint(id="kp1", text="Morning.", source_quote="في الصباح الباكر"),
        KeyPoint(id="kp2", text="Invented.", source_quote="لم يحدث هذا أبدا"),
    ])
    result = validate_question(q, PASSAGE, ALLOWED)
    assert not result.ok
    assert "kp2" in result.detail


def test_empty_source_quote_rejected():
    q = question(key_points=[KeyPoint(id="kp1", text="x", source_quote="   ")])
    result = validate_question(q, PASSAGE, ALLOWED)
    assert not result.ok
    assert "empty source_quote" in result.detail
