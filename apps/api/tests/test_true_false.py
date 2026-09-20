"""Tier 0 — true/false generation contract. No network, no API key, no cost."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.generation.validate import validate_true_false
from app.schemas.grading import TrueFalseSet, TrueFalseStatement

PASSAGE = (
    "ذهب الولد إلى المدرسة في الصباح الباكر، وكان الطقس جميلا صافيا. "
    "وفي الطريق التقى بصديقه القديم أحمد."
)
ALLOWED = {"c1"}


def statement(id="s1", is_true=True, quote="في الصباح الباكر", text="في الصباح"):
    return TrueFalseStatement(
        id=id,
        statement_arabic=text,
        statement_english="in the morning",
        is_true=is_true,
        source_quote=quote,
        explanation="Stated in the passage.",
    )


def tf_set(statements=None, **kw):
    defaults = dict(
        statements=statements
        if statements is not None
        else [statement("s1", True), statement("s2", False, "وكان الطقس جميلا صافيا"),
              statement("s3", True, "التقى بصديقه القديم أحمد")],
        source_chunk_ids=["c1"],
        difficulty_cefr="A2",
        answerable_from_source=True,
    )
    defaults.update(kw)
    return TrueFalseSet(**defaults)


# --- the mixed-verdict rule ------------------------------------------------
# A set that is all-true or all-false teaches the learner to guess one way
# rather than to read the passage.


def test_all_true_set_rejected():
    with pytest.raises(ValidationError, match="both true and false"):
        tf_set([statement("s1", True), statement("s2", True), statement("s3", True)])


def test_all_false_set_rejected():
    with pytest.raises(ValidationError, match="both true and false"):
        tf_set([statement("s1", False), statement("s2", False), statement("s3", False)])


def test_mixed_set_accepted():
    assert len(tf_set().statements) == 3


def test_two_statements_exempt_from_the_mix_rule():
    """With only two, one-of-each is the only mix — the rule adds nothing and
    would reject a legitimate pair."""
    assert tf_set([statement("s1", True), statement("s2", True)])


def test_answerable_requires_statements():
    with pytest.raises(ValidationError, match="no statements"):
        tf_set([], answerable_from_source=True)


def test_refusal_is_valid():
    """A passage that cannot support statements must be refusable."""
    result = tf_set([], answerable_from_source=False)
    assert validate_true_false(result, PASSAGE, ALLOWED).ok


# --- grounding -------------------------------------------------------------


def test_grounded_set_passes():
    assert validate_true_false(tf_set(), PASSAGE, ALLOWED).ok


def test_fabricated_quote_rejected():
    result = tf_set(
        [statement("s1", True, "ركب الولد حصانا"), statement("s2", False, "وكان الطقس جميلا صافيا")]
    )
    verdict = validate_true_false(result, PASSAGE, ALLOWED)
    assert not verdict.ok
    assert "not verbatim" in verdict.detail


def test_false_statement_quote_must_also_be_verbatim():
    """A false statement's quote is the text it CONTRADICTS — that is what
    proves it false about this passage rather than merely absent from it."""
    result = tf_set(
        [statement("s1", True), statement("s2", False, "كان الطقس ماطرا")]
    )
    assert not validate_true_false(result, PASSAGE, ALLOWED).ok


def test_chunk_outside_retrieval_set_rejected():
    result = tf_set(source_chunk_ids=["c1", "c99"])
    verdict = validate_true_false(result, PASSAGE, ALLOWED)
    assert not verdict.ok
    assert "outside the retrieval set" in verdict.detail


def test_refusal_must_be_empty_handed():
    result = TrueFalseSet(
        statements=[],
        source_chunk_ids=["c1"],
        difficulty_cefr="A2",
        answerable_from_source=False,
    )
    # Constructing with statements AND answerable=False is caught by the
    # validator rather than the schema, since the schema only guards the
    # opposite direction.
    result.statements = [statement()]
    verdict = validate_true_false(result, PASSAGE, ALLOWED)
    assert not verdict.ok
    assert "unanswerable" in verdict.detail


def test_empty_quote_rejected():
    result = tf_set([statement("s1", True, "  "), statement("s2", False, "وكان الطقس جميلا صافيا")])
    assert not validate_true_false(result, PASSAGE, ALLOWED).ok


def test_at_most_six_statements():
    with pytest.raises(ValidationError):
        tf_set([statement(f"s{i}", i % 2 == 0) for i in range(7)])
