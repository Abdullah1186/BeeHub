"""Metrics endpoints (spec §2.5).

Everything here is computed from rows the app already records — attempts,
error_tags, model_calls. **No model calls happen in this module.** §5.7 is
explicit that the statistics are code's job and the model's role is grading
individual items well.

CEFR estimation deliberately reports confidence rather than pretending
precision: "A2, low confidence (12 graded items)" is the honest output early on.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import AuthenticatedUser, current_user
from app.db import user_client

router = APIRouter(prefix="/metrics", tags=["metrics"])

CEFR_ORDER = ["A1", "A2", "B1", "B2", "C1", "C2"]

# Below this many graded attempts, an estimate is not worth showing as a level.
# §5.7: "do not show B1 off the back of four answers."
MIN_OBSERVATIONS = 15


class SkillEstimate(BaseModel):
    skill: str
    cefr_level: str | None
    confidence: float
    n_observations: int
    # Present so the UI can say "not enough data yet" rather than inventing one.
    sufficient: bool


class WeakSpot(BaseModel):
    category: str
    subcategory: str
    count: int
    severity_mix: dict[str, int]


class Overview(BaseModel):
    attempts_total: int
    attempts_7d: int
    mean_content_score: float | None
    mean_language_score: float | None
    streak_days: int
    estimates: list[SkillEstimate]
    weak_spots: list[WeakSpot]
    activity: list[dict]
    vocab_total: int
    cost_usd_total: float


def _estimate(scores: list[tuple[str, float]]) -> SkillEstimate | None:
    """Difficulty-weighted estimate from (difficulty_cefr, score) pairs.

    Elo-style in spirit but deliberately simple: each attempt nudges the
    estimate toward the difficulty it was set at, weighted by how well it went.
    §5.7 warns against asking the model "what level is this user?" per attempt,
    because the estimate jitters wildly. Statistics belong in code.
    """
    if not scores:
        return None

    total = 0.0
    for level, score in scores:
        index = CEFR_ORDER.index(level) if level in CEFR_ORDER else 1
        # Scoring well at a level implies you are at or above it; scoring badly
        # implies below. ±0.5 of a band per attempt, averaged.
        total += index + (score - 0.5)

    mean = total / len(scores)
    band = max(0, min(len(CEFR_ORDER) - 1, round(mean)))

    n = len(scores)
    # Confidence grows with n and shrinks with score variance — a learner who is
    # all-or-nothing is less pinned down than one who is consistently at a level.
    variance = (
        sum((s - sum(x for _, x in scores) / n) ** 2 for _, s in scores) / n
        if n > 1
        else 0.5
    )
    confidence = min(0.95, (n / (n + 12)) * (1 - min(variance, 0.5)))

    return SkillEstimate(
        skill="",
        cefr_level=CEFR_ORDER[band] if n >= MIN_OBSERVATIONS else None,
        confidence=round(confidence, 2),
        n_observations=n,
        sufficient=n >= MIN_OBSERVATIONS,
    )


@router.get("/overview", response_model=Overview)
def overview(user: AuthenticatedUser = Depends(current_user)) -> Overview:
    client = user_client(user.token)

    attempts = (
        client.table("attempts")
        .select("content_score, language_score, difficulty_cefr, created_at, gradable")
        .order("created_at", desc=True)
        .limit(500)
        .execute()
    ).data or []

    graded = [a for a in attempts if a.get("gradable") and a.get("content_score") is not None]

    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    def parsed(row) -> datetime | None:
        try:
            return datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
        except Exception:
            return None

    recent = [a for a in attempts if (d := parsed(a)) and d >= week_ago]

    # Streak: consecutive days back from today with at least one attempt.
    days_active = {d.date() for a in attempts if (d := parsed(a))}
    streak = 0
    cursor = now.date()
    while cursor in days_active:
        streak += 1
        cursor -= timedelta(days=1)

    # Reading is measured by content, writing by language — the two scores move
    # independently, which is the whole point of splitting them (§2.5).
    reading = _estimate([(a["difficulty_cefr"], float(a["content_score"])) for a in graded])
    writing = _estimate(
        [
            (a["difficulty_cefr"], float(a["language_score"]))
            for a in graded
            if a.get("language_score") is not None
        ]
    )

    estimates = []
    for name, est in (("reading", reading), ("writing", writing)):
        if est:
            estimates.append(est.model_copy(update={"skill": name}))
        else:
            estimates.append(
                SkillEstimate(
                    skill=name, cefr_level=None, confidence=0.0,
                    n_observations=0, sufficient=False,
                )
            )

    tags = (
        client.table("error_tags")
        .select("category, subcategory, severity")
        .order("created_at", desc=True)
        .limit(500)
        .execute()
    ).data or []

    pairs = Counter((t["category"], t["subcategory"]) for t in tags)
    weak_spots = []
    for (category, subcategory), count in pairs.most_common(3):
        mix = Counter(
            t["severity"]
            for t in tags
            if t["category"] == category and t["subcategory"] == subcategory
        )
        weak_spots.append(
            WeakSpot(
                category=category, subcategory=subcategory,
                count=count, severity_mix=dict(mix),
            )
        )

    # Last 14 days of activity, for the sparkline.
    by_day: Counter[str] = Counter()
    for a in attempts:
        if (d := parsed(a)) and d >= now - timedelta(days=14):
            by_day[d.date().isoformat()] += 1
    activity = [
        {"date": (now.date() - timedelta(days=i)).isoformat(),
         "count": by_day.get((now.date() - timedelta(days=i)).isoformat(), 0)}
        for i in range(13, -1, -1)
    ]

    vocab = client.table("vocab_items").select("id").execute()
    calls = client.table("model_calls").select("cost_usd").limit(1000).execute()

    return Overview(
        attempts_total=len(attempts),
        attempts_7d=len(recent),
        mean_content_score=(
            round(sum(float(a["content_score"]) for a in graded) / len(graded), 3)
            if graded else None
        ),
        mean_language_score=(
            round(
                sum(float(a["language_score"]) for a in graded
                    if a.get("language_score") is not None) / len(graded), 3
            ) if graded else None
        ),
        streak_days=streak,
        estimates=estimates,
        weak_spots=weak_spots,
        activity=activity,
        vocab_total=len(vocab.data or []),
        cost_usd_total=round(sum(float(c["cost_usd"]) for c in (calls.data or [])), 4),
    )
