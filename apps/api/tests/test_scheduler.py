"""Tier 0 — FSRS scheduling. No network, no API key, no cost.

Scheduling bugs are invisible in production: a wrong interval still looks like
a plausible interval, and the learner has no way to tell that a card came back
too early or too late. These tests are the only thing that catches it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fsrs import Rating

from app.review.scheduler import (
    LAPSE_INTERVAL_MINUTES,
    RETIRE_STABILITY_DAYS,
    new_card,
    review,
    score_to_rating,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (1.0, Rating.Easy),
        (0.9, Rating.Easy),
        (0.85, Rating.Good),
        (0.7, Rating.Good),
        (0.6, Rating.Hard),
        (0.4, Rating.Hard),
        (0.3, Rating.Again),
        (0.0, Rating.Again),
    ],
)
def test_score_maps_to_rating(score, expected):
    assert score_to_rating(score) is expected


def test_half_remembered_is_not_a_pass():
    """0.5 must be Hard, not Good — a card you half-know you will forget."""
    assert score_to_rating(0.5) is Rating.Hard


def test_new_card_is_due_immediately():
    """Items enter the queue because they were got wrong; no reason to wait."""
    _state, due = new_card(NOW)
    assert due == NOW


def test_intervals_expand_on_success():
    """The core §2.4 property: 'resurfaces at expanding intervals'."""
    state, _ = new_card(NOW)
    now = NOW
    intervals = []
    reps = lapses = 0

    for _ in range(4):
        result = review(state, 0.95, reps=reps, lapses=lapses, now=now)
        intervals.append(result.interval_days)
        state, reps, lapses, now = (
            result.fsrs_state, result.reps, result.lapses, result.due_at,
        )

    assert intervals == sorted(intervals), f"intervals must grow: {intervals}"
    assert intervals[-1] > intervals[0] * 5


def test_failure_collapses_the_interval():
    """Forgetting must bring a card back soon, not keep the old schedule."""
    state, _ = new_card(NOW)
    now = NOW
    reps = lapses = 0
    for _ in range(3):
        r = review(state, 0.95, reps=reps, lapses=lapses, now=now)
        state, reps, lapses, now = r.fsrs_state, r.reps, r.lapses, r.due_at

    good = review(state, 0.95, reps=reps, lapses=lapses, now=now)
    failed = review(state, 0.0, reps=reps, lapses=lapses, now=now)

    assert failed.interval_days < good.interval_days
    assert failed.lapses == lapses + 1


def test_lapses_only_count_failures():
    state, _ = new_card(NOW)
    assert review(state, 0.95, now=NOW).lapses == 0
    assert review(state, 0.2, now=NOW).lapses == 1


def test_reps_always_increment():
    state, _ = new_card(NOW)
    for score in (0.0, 0.5, 1.0):
        assert review(state, score, reps=4, now=NOW).reps == 5


def test_well_known_card_retires():
    """§2.4: 'until retired'. Drilling a card you will remember for a year is
    wasted time."""
    state, _ = new_card(NOW)
    now = NOW
    reps = lapses = 0
    for _ in range(6):
        result = review(state, 1.0, reps=reps, lapses=lapses, now=now)
        if result.retired:
            assert result.retired_reason == "learned"
            return
        state, reps, lapses, now = (
            result.fsrs_state, result.reps, result.lapses, result.due_at,
        )
    pytest.fail("a perfectly answered card should retire within six reviews")


def test_troublesome_card_never_retires():
    """A card forgotten repeatedly stays in the queue regardless of stability."""
    state, _ = new_card(NOW)
    result = review(state, 1.0, reps=20, lapses=10, now=NOW)
    assert not result.retired


def test_state_round_trips_through_json():
    """fsrs_state is stored as JSONB, so it must survive serialisation."""
    import json

    state, _ = new_card(NOW)
    result = review(state, 0.8, now=NOW)
    restored = json.loads(json.dumps(result.fsrs_state))
    again = review(restored, 0.8, now=result.due_at)
    assert again.due_at > result.due_at


def test_due_dates_are_timezone_aware():
    """A naive datetime compared against a tz-aware `now` raises at runtime."""
    state, _ = new_card(NOW)
    assert review(state, 0.8, now=NOW).due_at.tzinfo is not None


def test_retire_threshold_is_a_year():
    assert RETIRE_STABILITY_DAYS == pytest.approx(365.0)


def test_scheduler_is_deterministic():
    """Same state and score must give the same schedule, or evals are noise."""
    state, _ = new_card(NOW)
    assert review(state, 0.8, now=NOW).due_at == review(state, 0.8, now=NOW).due_at


# --- deck contract ---------------------------------------------------------
# The deck promises that a card you mark known LEAVES. FSRS's default learning
# steps break that promise: the first "Good" schedules a card ~15 minutes out,
# so it reappears in the same session. Right for Anki, wrong here.


def test_known_card_leaves_for_at_least_a_day():
    """The first 'I know it' must schedule a real interval, not minutes."""
    state, _ = new_card(NOW)
    result = review(state, 0.85, now=NOW)
    assert result.interval_days >= 1.0, (
        f"a known card came back in {result.interval_days * 24:.1f} hours — "
        "learning steps are back on"
    )


def test_still_learning_returns_within_the_session():
    """The other half: an unknown card must come back in minutes, not days."""
    state, _ = new_card(NOW)
    result = review(state, 0.2, now=NOW)
    minutes = result.interval_days * 24 * 60
    assert minutes == pytest.approx(LAPSE_INTERVAL_MINUTES, abs=1)


def test_lapse_keeps_the_memory_model():
    """Bringing a card back soon must not reset what FSRS has learned."""
    state, _ = new_card(NOW)
    now = NOW
    reps = lapses = 0
    for _ in range(3):
        r = review(state, 0.85, reps=reps, lapses=lapses, now=now)
        state, reps, lapses, now = r.fsrs_state, r.reps, r.lapses, r.due_at

    lapsed = review(state, 0.2, reps=reps, lapses=lapses, now=now)
    # Stability survives the lapse, so the next success builds on it rather
    # than starting from scratch.
    assert lapsed.fsrs_state.get("stability") is not None
    assert lapsed.lapses == lapses + 1


def test_intervals_still_expand_without_learning_steps():
    state, _ = new_card(NOW)
    now = NOW
    reps = lapses = 0
    intervals = []
    for _ in range(4):
        r = review(state, 0.85, reps=reps, lapses=lapses, now=now)
        intervals.append(r.interval_days)
        state, reps, lapses, now = r.fsrs_state, r.reps, r.lapses, r.due_at

    assert intervals == sorted(intervals)
    assert intervals[0] >= 1.0
