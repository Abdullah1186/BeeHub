"""Spaced repetition scheduling (spec §2.4).

**FSRS-6, not SM-2.** The spec offers either and asks for the choice to be
noted, so:

FSRS models memory directly — stability, difficulty, retrievability — and
schedules a card for the moment you are about to forget it. SM-2 has no notion
of recall probability; it multiplies an interval by an ease factor and hopes.

The decisive point for BeeHub is cold start. SM-2 needs its parameters tuned
per learner to behave well, and a new user has no history to tune from. FSRS
ships defaults trained on ~700M reviews that beat SM-2 for ~99.5% of users
*without* personalisation, and can be optimised later once a learner has
several hundred reviews. Roughly 20-30% fewer reviews for the same retention.

This module is pure: it takes state in and returns state out, with no database
and no clock of its own beyond an injectable `now`. That keeps it testable for
free — scheduling bugs are invisible in production because a wrong interval
still looks like a plausible interval.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fsrs import Card, Rating, Scheduler

# How the learner's answer maps to FSRS's four grades.
#
# BeeHub grades on a 0-1 scale rather than asking "how well did you know
# that?", so the mapping is ours to choose. It is deliberately harsh at the
# bottom: a card you half-remember is a card you will forget, and treating it
# as a success schedules it too far out.
RATING_THRESHOLDS: list[tuple[float, Rating]] = [
    (0.9, Rating.Easy),   # effortless
    (0.7, Rating.Good),   # recalled
    (0.4, Rating.Hard),   # recalled with difficulty
    (0.0, Rating.Again),  # failed
]

# Retire a card once it is this stable — FSRS predicts you will still remember
# it in this many days. Continuing to drill it past this point is wasted time.
RETIRE_STABILITY_DAYS = 365.0

# ...but never retire something that keeps being forgotten, however stable the
# model currently thinks it is.
MAX_LAPSES_BEFORE_KEEPING = 8

_scheduler = Scheduler()


@dataclass(frozen=True)
class ScheduleResult:
    fsrs_state: dict[str, Any]
    due_at: datetime
    reps: int
    lapses: int
    retired: bool
    retired_reason: str | None
    interval_days: float


def score_to_rating(score: float) -> Rating:
    """Map a 0-1 score to an FSRS grade."""
    for threshold, rating in RATING_THRESHOLDS:
        if score >= threshold:
            return rating
    return Rating.Again


def new_card(now: datetime | None = None) -> tuple[dict[str, Any], datetime]:
    """A fresh card, due immediately.

    Items enter the queue because they were got wrong, so there is no reason to
    wait before the first review.
    """
    now = now or datetime.now(timezone.utc)
    card = Card()
    return card.to_dict(), now


def review(
    fsrs_state: dict[str, Any],
    score: float,
    *,
    reps: int = 0,
    lapses: int = 0,
    now: datetime | None = None,
) -> ScheduleResult:
    """Apply one review and return the next schedule."""
    now = now or datetime.now(timezone.utc)
    rating = score_to_rating(score)

    card = Card.from_dict(fsrs_state)
    card, _log = _scheduler.review_card(card, rating, now)

    reps += 1
    if rating is Rating.Again:
        lapses += 1

    stability = card.stability or 0.0
    retired = (
        stability >= RETIRE_STABILITY_DAYS and lapses < MAX_LAPSES_BEFORE_KEEPING
    )

    return ScheduleResult(
        fsrs_state=card.to_dict(),
        due_at=card.due,
        reps=reps,
        lapses=lapses,
        retired=retired,
        retired_reason="learned" if retired else None,
        interval_days=(card.due - now).total_seconds() / 86400,
    )
