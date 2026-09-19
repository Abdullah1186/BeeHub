"""Tier 0 — score arithmetic. No network, no API key, no cost.

Table-driven over verdict/severity combinations. These tests encode the grading
POLICY, so a change here should be a deliberate decision, not a side effect.
"""

from __future__ import annotations

import pytest

from app.grading.score import (
    DISAGREEMENT_THRESHOLD,
    MAX_LANGUAGE_PENALTY,
    compute_score,
)
from app.schemas.grading import ErrorTag, KeyPointVerdict, ShortAnswerGrade


def verdict(status: str, kp_id: str = "kp1") -> KeyPointVerdict:
    return KeyPointVerdict(key_point_id=kp_id, status=status, reasoning="test")


def tag(severity: str) -> ErrorTag:
    return ErrorTag(
        category="orthography",
        subcategory="hamza",
        span="سئل",
        correction="سأل",
        explanation="Wrong hamza seat.",
        severity=severity,
    )


def grade(**kwargs) -> ShortAnswerGrade:
    defaults = dict(
        gradable=True,
        key_points=[verdict("conveyed")],
        language_errors=[],
        model_comprehension_score=1.0,
        holistic_note="ok",
    )
    defaults.update(kwargs)
    return ShortAnswerGrade(**defaults)


# --- content scoring -------------------------------------------------------


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        (["conveyed"], 1.0),
        (["absent"], 0.0),
        (["contradicted"], 0.0),
        (["partially_conveyed"], 0.5),
        (["conveyed", "conveyed"], 1.0),
        (["conveyed", "absent"], 0.5),
        (["conveyed", "partially_conveyed"], 0.75),
        (["conveyed", "conveyed", "absent"], pytest.approx(2 / 3)),
    ],
)
def test_content_score(statuses, expected):
    result = compute_score(
        grade(key_points=[verdict(s, f"kp{i}") for i, s in enumerate(statuses)])
    )
    assert result.content_score == expected


def test_contradicted_is_counted_separately():
    """'Said the opposite' is a near-miss and must be visible, not just absent."""
    result = compute_score(
        grade(key_points=[verdict("contradicted", "kp1"), verdict("absent", "kp2")])
    )
    assert result.contradicted_count == 1
    assert result.content_score == 0.0


# --- the fair-to-paraphrase guarantee --------------------------------------


def test_minor_errors_cost_nothing():
    """A correct answer with spelling slips must not lose marks."""
    result = compute_score(grade(language_errors=[tag("minor")] * 5))
    assert result.language_penalty == 0.0
    assert result.final_score == 1.0
    assert result.error_counts["minor"] == 5  # still tagged for metrics


def test_moderate_and_blocking_do_cost():
    assert compute_score(grade(language_errors=[tag("moderate")])).language_penalty == 0.05
    assert compute_score(grade(language_errors=[tag("blocking")])).language_penalty == 0.12


def test_language_penalty_is_capped():
    """Many small errors must not zero out perfect comprehension."""
    result = compute_score(grade(language_errors=[tag("blocking")] * 20))
    assert result.language_penalty == MAX_LANGUAGE_PENALTY
    assert result.final_score > 0.0


def test_content_and_language_are_independent():
    """Right answer, broken Arabic: full content, reduced language. §2.5 needs this.

    The two must move independently, so reading and writing CEFR can diverge.
    language_score bottoms out at 1 - MAX_LANGUAGE_PENALTY by design.
    """
    result = compute_score(
        grade(key_points=[verdict("conveyed")], language_errors=[tag("blocking")] * 3)
    )
    assert result.content_score == 1.0
    assert result.language_score == pytest.approx(1.0 - MAX_LANGUAGE_PENALTY)
    assert result.language_score < result.content_score


def test_wrong_answer_in_perfect_arabic():
    result = compute_score(grade(key_points=[verdict("absent")], language_errors=[]))
    assert result.content_score == 0.0
    assert result.language_score == 1.0
    assert result.final_score == 0.0


# --- edge cases ------------------------------------------------------------


def test_ungradable_scores_zero_and_flags():
    result = compute_score(
        grade(gradable=False, ungradable_reason="blank answer", key_points=[])
    )
    assert result.final_score == 0.0
    assert result.review_flagged is True


def test_off_topic_gets_no_content_credit():
    result = compute_score(grade(key_points=[verdict("conveyed")], is_off_topic=True))
    assert result.content_score == 0.0


def test_no_key_points_flags_for_review():
    result = compute_score(grade(key_points=[], model_comprehension_score=0.0))
    assert result.review_flagged is True


def test_scores_never_negative():
    result = compute_score(
        grade(key_points=[verdict("absent")], language_errors=[tag("blocking")] * 10)
    )
    assert result.final_score >= 0.0
    assert result.language_score >= 0.0


def test_final_score_quantised():
    """Learners see a stable mark, not 0.6333."""
    for statuses in (["conveyed"], ["partially_conveyed"], ["conveyed", "absent"]):
        result = compute_score(grade(key_points=[verdict(s) for s in statuses]))
        assert abs(result.final_score * 5 - round(result.final_score * 5)) < 1e-9


# --- disagreement signal ---------------------------------------------------


def test_disagreement_flags_for_review():
    """Model says 0.0, key points say 1.0 -> a free eval case."""
    result = compute_score(
        grade(key_points=[verdict("conveyed")], model_comprehension_score=0.0)
    )
    assert result.review_flagged is True


def test_agreement_does_not_flag():
    result = compute_score(
        grade(key_points=[verdict("conveyed")], model_comprehension_score=1.0)
    )
    assert result.review_flagged is False


def test_model_score_does_not_affect_grade():
    """The model's holistic number is recorded, never used."""
    high = compute_score(grade(key_points=[verdict("absent")], model_comprehension_score=1.0))
    low = compute_score(grade(key_points=[verdict("absent")], model_comprehension_score=0.0))
    assert high.final_score == low.final_score == 0.0


def test_threshold_boundary():
    just_under = compute_score(
        grade(
            key_points=[verdict("conveyed")],
            model_comprehension_score=1.0 - DISAGREEMENT_THRESHOLD + 0.01,
        )
    )
    assert just_under.review_flagged is False


def test_breakdown_serializes():
    import json

    json.dumps(compute_score(grade()).as_dict())
