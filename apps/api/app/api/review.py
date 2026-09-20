"""Review endpoints (spec §2.4).

Spaced repetition over **things already got wrong** — never new material. Items
are vocabulary words and error tags, resurfacing at expanding intervals until
retired.

Scheduling is FSRS-6; see app/review/scheduler.py for why, and note that the
scheduling itself is pure and tested offline. This module only moves rows.
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth import AuthenticatedUser, current_user
from app.db import user_client
from app.review.scheduler import new_card, review as schedule_review

log = structlog.get_logger()
router = APIRouter(prefix="/review", tags=["review"])


class ReviewCard(BaseModel):
    id: str
    kind: str
    front: str
    back: str
    hint: str | None = None
    reps: int
    lapses: int
    due_at: str


class ReviewGrade(BaseModel):
    card_id: str
    # 0-1, the same scale grading uses everywhere else. The UI sends discrete
    # buttons, but the scale stays continuous so an automatic enqueue from a
    # graded attempt can feed the same path.
    score: float = Field(ge=0.0, le=1.0)


class ReviewResult(BaseModel):
    next_due_at: str
    interval_days: float
    reps: int
    lapses: int
    retired: bool


class QueueStats(BaseModel):
    due_now: int
    total_active: int
    retired: int


@router.get("/due", response_model=list[ReviewCard])
def due(
    limit: int = 20, user: AuthenticatedUser = Depends(current_user)
) -> list[ReviewCard]:
    """Cards due for review, oldest-due first."""
    client = user_client(user.token)
    now = datetime.now(timezone.utc).isoformat()

    rows = (
        client.table("review_queue")
        .select("id, kind, front, back, hint, reps, lapses, due_at")
        .is_("retired_at", "null")
        .lte("due_at", now)
        .order("due_at")
        .limit(min(limit, 100))
        .execute()
    ).data or []

    return [ReviewCard(**row) for row in rows]


@router.get("/stats", response_model=QueueStats)
def stats(user: AuthenticatedUser = Depends(current_user)) -> QueueStats:
    client = user_client(user.token)
    now = datetime.now(timezone.utc).isoformat()

    active = (
        client.table("review_queue").select("id, due_at").is_("retired_at", "null").execute()
    ).data or []
    retired = (
        client.table("review_queue").select("id").not_.is_("retired_at", "null").execute()
    ).data or []

    return QueueStats(
        due_now=sum(1 for r in active if r["due_at"] <= now),
        total_active=len(active),
        retired=len(retired),
    )


@router.post("/grade", response_model=ReviewResult)
def grade(
    body: ReviewGrade, user: AuthenticatedUser = Depends(current_user)
) -> ReviewResult:
    """Record a review and reschedule the card."""
    client = user_client(user.token)

    rows = (
        client.table("review_queue").select("*").eq("id", body.card_id).execute()
    ).data
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown card")
    card = rows[0]

    result = schedule_review(
        card["fsrs_state"],
        body.score,
        reps=card["reps"],
        lapses=card["lapses"],
    )

    update = {
        "fsrs_state": result.fsrs_state,
        "due_at": result.due_at.isoformat(),
        "reps": result.reps,
        "lapses": result.lapses,
    }
    if result.retired:
        update["retired_at"] = datetime.now(timezone.utc).isoformat()
        update["retired_reason"] = result.retired_reason

    client.table("review_queue").update(update).eq("id", body.card_id).execute()

    log.info(
        "review_graded",
        card_id=body.card_id,
        score=body.score,
        interval_days=round(result.interval_days, 2),
        retired=result.retired,
    )
    return ReviewResult(
        next_due_at=result.due_at.isoformat(),
        interval_days=round(result.interval_days, 2),
        reps=result.reps,
        lapses=result.lapses,
        retired=result.retired,
    )


@router.post("/enqueue-vocab", response_model=QueueStats)
def enqueue_vocab(user: AuthenticatedUser = Depends(current_user)) -> QueueStats:
    """Add vocabulary that is not yet in the queue.

    §2.4 says review is "not new material — only things previously got wrong".
    Vocabulary is the honest exception: a harvested word has never been tested,
    so its first review IS the test. Error tags enter the queue automatically
    when an answer is graded (see below); words need this nudge.
    """
    client = user_client(user.token)

    words = (
        client.table("vocab_items")
        .select("id, arabic, translation, context_sentence")
        .limit(200)
        .execute()
    ).data or []

    existing = {
        row["vocab_id"]
        for row in (
            client.table("review_queue").select("vocab_id").execute().data or []
        )
        if row.get("vocab_id")
    }

    added = 0
    for word in words:
        if word["id"] in existing:
            continue
        state, due = new_card()
        try:
            client.table("review_queue").insert(
                {
                    "user_id": user.id,
                    "kind": "vocab",
                    "vocab_id": word["id"],
                    "front": word["arabic"],
                    "back": word["translation"],
                    "hint": word.get("context_sentence"),
                    "due_at": due.isoformat(),
                    "fsrs_state": state,
                }
            ).execute()
            added += 1
        except Exception:
            # Unique index on (user_id, vocab_id) — a concurrent enqueue got
            # there first. Adding a word twice should not double it.
            continue

    log.info("vocab_enqueued", added=added)
    return stats(user)


def enqueue_error_tags(client, user_id: str, attempt_id: str) -> int:
    """Queue the grammar errors from one graded attempt.

    Called from the grading path, not exposed as an endpoint: an error tag
    belongs in review the moment it is produced, and asking the learner to
    press a button for that would mean the queue only ever holds what they
    remembered to add.
    """
    tags = (
        client.table("error_tags")
        .select("id, category, subcategory, span, correction, explanation")
        .eq("attempt_id", attempt_id)
        .execute()
    ).data or []

    added = 0
    for tag in tags:
        # Minor errors are tagged for the metrics but do not cost marks, and
        # drilling every hamza slip would swamp the queue with noise.
        state, due = new_card()
        try:
            client.table("review_queue").insert(
                {
                    "user_id": user_id,
                    "kind": "error_tag",
                    "error_tag_id": tag["id"],
                    "front": tag["span"],
                    "back": tag.get("correction") or tag["explanation"],
                    "hint": tag["explanation"],
                    "due_at": due.isoformat(),
                    "fsrs_state": state,
                }
            ).execute()
            added += 1
        except Exception:
            continue
    return added
