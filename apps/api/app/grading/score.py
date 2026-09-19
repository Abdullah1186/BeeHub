"""Score arithmetic. Pure functions, no model involvement.

The model returns per-key-point verdicts and error tags — discrete, checkable
judgements. The number comes from here.

Two reasons this is not the model's job:

1. **Auditability.** A learner disputing a mark can be shown exactly which key
   point was missed and which errors cost what. A holistic score from the model
   is unexplainable and drifts between runs.
2. **Tunability.** Weights change here, in code, covered by tests, without
   touching a prompt or re-running an eval.

The policy decision encoded below: **minor errors carry no penalty.** A learner
who conveys the meaning with a hamza slip has comprehended. The error is still
tagged and still feeds metrics and the review queue — it just does not cost
marks. That is the fair-to-paraphrase guarantee, enforced rather than requested.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.grading import ShortAnswerGrade

# Credit per key-point verdict.
KEY_POINT_CREDIT: dict[str, float] = {
    "conveyed": 1.0,
    "partially_conveyed": 0.5,
    "absent": 0.0,
    # Same credit as 'absent', but tracked separately: asserting the opposite is
    # a comprehension failure worth surfacing, not just an omission.
    "contradicted": 0.0,
}

# Penalty per error, by severity. Minor is deliberately zero.
SEVERITY_PENALTY: dict[str, float] = {
    "minor": 0.00,
    "moderate": 0.05,
    "blocking": 0.12,
}

# Cap on total language penalty. Without it, a long answer with many small
# errors could score zero despite perfect comprehension.
MAX_LANGUAGE_PENALTY = 0.25

# Flag for eval review when the model's holistic score and the computed content
# score disagree by more than this. These become free eval cases.
DISAGREEMENT_THRESHOLD = 0.3


@dataclass(frozen=True)
class ScoreBreakdown:
    """Everything needed to explain a mark to the learner."""

    content_score: float      # 0-1, comprehension -> reading CEFR
    language_score: float     # 0-1, accuracy     -> writing CEFR
    final_score: float        # 0-1, combined
    language_penalty: float
    key_points_total: int
    key_points_conveyed: float
    contradicted_count: int
    error_counts: dict[str, int]
    review_flagged: bool

    def as_dict(self) -> dict:
        return {
            "content_score": round(self.content_score, 3),
            "language_score": round(self.language_score, 3),
            "final_score": round(self.final_score, 3),
            "language_penalty": round(self.language_penalty, 3),
            "key_points_total": self.key_points_total,
            "key_points_conveyed": round(self.key_points_conveyed, 3),
            "contradicted_count": self.contradicted_count,
            "error_counts": dict(self.error_counts),
            "review_flagged": self.review_flagged,
        }


def compute_score(grade: ShortAnswerGrade) -> ScoreBreakdown:
    """Turn a model grade into numbers.

    An ungradable answer scores zero on everything and is flagged for review
    rather than guessed at (spec §7: never invent a mark).
    """
    error_counts = {"minor": 0, "moderate": 0, "blocking": 0}
    for tag in grade.language_errors:
        error_counts[str(tag.severity)] += 1

    if not grade.gradable:
        return ScoreBreakdown(
            content_score=0.0,
            language_score=0.0,
            final_score=0.0,
            language_penalty=0.0,
            key_points_total=len(grade.key_points),
            key_points_conveyed=0.0,
            contradicted_count=0,
            error_counts=error_counts,
            review_flagged=True,
        )

    # --- content: did they answer the question? ---
    if grade.key_points:
        conveyed = sum(KEY_POINT_CREDIT[str(v.status)] for v in grade.key_points)
        content_score = conveyed / len(grade.key_points)
    else:
        # No key points to check against. Not the learner's fault, but not
        # evidence of comprehension either — flag rather than award marks.
        conveyed = 0.0
        content_score = 0.0

    contradicted = sum(1 for v in grade.key_points if str(v.status) == "contradicted")

    # An off-topic answer gets no content credit regardless of key-point verdicts.
    if grade.is_off_topic:
        content_score = 0.0

    # --- language: how accurate was the Arabic? ---
    raw_penalty = sum(
        SEVERITY_PENALTY[str(tag.severity)] for tag in grade.language_errors
    )
    language_penalty = min(MAX_LANGUAGE_PENALTY, raw_penalty)
    language_score = max(0.0, 1.0 - language_penalty)

    # --- combined ---
    final = max(0.0, content_score - language_penalty)
    # Round to 0.2 steps so the learner sees a stable mark rather than 0.6333.
    final_score = round(final * 5) / 5

    # The model's holistic score is not used for the grade, only compared.
    review_flagged = (
        abs(grade.model_comprehension_score - content_score) > DISAGREEMENT_THRESHOLD
        or not grade.key_points
    )

    return ScoreBreakdown(
        content_score=content_score,
        language_score=language_score,
        final_score=final_score,
        language_penalty=language_penalty,
        key_points_total=len(grade.key_points),
        key_points_conveyed=conveyed,
        contradicted_count=contradicted,
        error_counts=error_counts,
        review_flagged=review_flagged,
    )
