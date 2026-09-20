"""Learning endpoints: serve a question, grade an answer.

The two calls that make up the core loop. Both are thin — the real work lives in
retrieval (the position gate), generation (grounding), and scoring (arithmetic).

Serving prefers the cache: §4 says never regenerate a question the learner has
not seen, which cuts cost substantially and makes the app feel faster.
"""

from __future__ import annotations

import json

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.ai.client import call_skill, record_call
from app.auth import AuthenticatedUser, current_user
from app.db import user_client
from app.generation.validate import validate_question, validate_true_false
from app.grading.score import compute_score
from app.retrieval.selector import select_window
from app.schemas.grading import ShortAnswerGrade

log = structlog.get_logger()
router = APIRouter(prefix="/learning", tags=["learning"])


class KeyPointOut(BaseModel):
    id: str
    text: str


class QuestionOut(BaseModel):
    item_id: str
    resource_id: str
    question_arabic: str
    question_english: str
    difficulty_cefr: str
    # Key point *text* is returned so the UI can show what was expected after
    # answering. source_quote is withheld — it would give the answer away.
    key_points: list[KeyPointOut]


class AnswerIn(BaseModel):
    item_id: str
    answer: str = Field(max_length=5000)


class ErrorTagOut(BaseModel):
    category: str
    subcategory: str
    span: str
    correction: str | None = None
    explanation: str
    severity: str


class GradeOut(BaseModel):
    gradable: bool
    ungradable_reason: str | None = None
    content_score: float
    language_score: float
    final_score: float
    key_point_verdicts: list[dict]
    errors: list[ErrorTagOut]
    feedback: str


def _serve_cached(client, user_id: str, resource_id: str | None) -> dict | None:
    """Next unseen, in-range, grounded item. Re-applies the gate at serve time."""
    result = client.rpc(
        "next_practice_item",
        {"p_user_id": user_id, "p_resource_id": resource_id},
    ).execute()
    return result.data[0] if result.data else None


@router.get("/next", response_model=QuestionOut)
def next_question(
    resource_id: str | None = None,
    user: AuthenticatedUser = Depends(current_user),
) -> QuestionOut:
    """Serve a question, generating one only if the bank has nothing unseen."""
    client = user_client(user.token)

    cached = _serve_cached(client, user.id, resource_id)
    if cached:
        payload = cached["payload"]
        return QuestionOut(
            item_id=cached["id"],
            resource_id=cached["resource_id"],
            question_arabic=payload["question_arabic"],
            question_english=payload.get("question_english", ""),
            difficulty_cefr=cached["difficulty_cefr"],
            key_points=[KeyPointOut(id=k["id"], text=k["text"])
                        for k in payload.get("key_points", [])],
        )

    if not resource_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no cached questions; specify a resource_id to generate one",
        )

    # --- generate ---
    retrieval = select_window(client, resource_id, user.id)
    if retrieval.is_empty:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "no material available to practise from. Either this resource has "
                "not finished processing, its text could not be extracted, or your "
                "reading position is at the very beginning."
            ),
        )

    level = _current_level(client, user.id)
    call = call_skill(
        "generate-comprehension-questions",
        json.dumps(
            {
                "passage": retrieval.text,
                "chunk_ids": sorted(retrieval.chunk_ids),
                "target_cefr": level,
            },
            ensure_ascii=False,
        ),
    )
    call_id = record_call(client, call, user.id)

    if call.status != "ok":
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="question generation failed; please try again",
        )

    question = call.parsed
    verdict = validate_question(question, retrieval.text, retrieval.chunk_ids)
    if not verdict.ok:
        # §5.2: reject rather than serve something ungrounded.
        log.warning("generation_rejected", reasons=verdict.reasons)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="could not generate a question grounded in this passage",
        )
    if not question.answerable_from_source:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "this passage does not support a comprehension question. It may be "
                "a heading, or its text may have extracted poorly."
            ),
        )

    row = (
        client.table("generated_items")
        .insert(
            {
                "user_id": user.id,
                "resource_id": resource_id,
                "item_type": "short_answer",
                "payload": question.model_dump(mode="json"),
                "source_chunk_ids": sorted(retrieval.chunk_ids),
                "max_page": retrieval.max_page,
                "difficulty_cefr": question.difficulty_cefr,
                "model_call_id": call_id,
            }
        )
        .execute()
    )

    return QuestionOut(
        item_id=row.data[0]["id"],
        resource_id=resource_id,
        question_arabic=question.question_arabic,
        question_english=question.question_english,
        difficulty_cefr=question.difficulty_cefr,
        key_points=[KeyPointOut(id=k.id, text=k.text) for k in question.key_points],
    )


@router.post("/answer", response_model=GradeOut)
def submit_answer(
    body: AnswerIn, user: AuthenticatedUser = Depends(current_user)
) -> GradeOut:
    """Grade an answer, tag its errors, and record the attempt."""
    client = user_client(user.token)

    items = (
        client.table("generated_items").select("*").eq("id", body.item_id).execute()
    )
    if not items.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown item")
    item = items.data[0]
    payload = item["payload"]

    # The passage the question came from, for the grader's context.
    chunks = (
        client.table("resource_chunks")
        .select("text, chunk_index")
        .in_("id", item["source_chunk_ids"])
        .order("chunk_index")
        .execute()
    )
    passage = "\n\n".join(c["text"] for c in (chunks.data or []))

    call = call_skill(
        "grade-short-answer",
        json.dumps(
            {
                "question": payload["question_arabic"],
                "key_points": payload["key_points"],
                "learner_answer": body.answer,
                "source_passage": passage,
            },
            ensure_ascii=False,
        ),
    )
    call_id = record_call(client, call, user.id)

    if call.status != "ok":
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="grading failed; your answer was not recorded",
        )

    grade: ShortAnswerGrade = call.parsed
    score = compute_score(grade)

    attempt = (
        client.table("attempts")
        .insert(
            {
                "user_id": user.id,
                "resource_id": item["resource_id"],
                "generated_item_id": item["id"],
                "mode": "questions",
                "item_type": "short_answer",
                "prompt_text": payload["question_arabic"],
                "user_answer": body.answer,
                "input_method": "typed",
                "content_score": round(score.content_score, 3),
                "language_score": round(score.language_score, 3),
                "score": round(score.final_score, 3),
                "difficulty_cefr": item["difficulty_cefr"],
                "grade_payload": {**grade.model_dump(mode="json"), **score.as_dict()},
                "gradable": grade.gradable,
                "review_flagged": score.review_flagged,
                "model_call_id": call_id,
            }
        )
        .execute()
    )

    attempt_id = attempt.data[0]["id"]

    if grade.language_errors:
        client.table("error_tags").insert(
            [
                {
                    "attempt_id": attempt_id,
                    "user_id": user.id,
                    "category": str(tag.category),
                    "subcategory": str(tag.subcategory),
                    "span": tag.span,
                    "correction": tag.correction,
                    "explanation": tag.explanation,
                    "severity": tag.severity,
                }
                for tag in grade.language_errors
            ]
        ).execute()

        # Queue the errors for spaced repetition (§2.4: "only things previously
        # got wrong"). Automatic rather than a button, because a queue that
        # only holds what the learner remembered to add is a queue of the
        # things they were already thinking about.
        #
        # Failure here must not cost the learner their graded answer, so it is
        # swallowed — but loudly, the same lesson as the telemetry write.
        try:
            from app.api.review import enqueue_error_tags

            queued = enqueue_error_tags(client, user.id, attempt_id)
            if queued:
                log.info("errors_queued_for_review", count=queued)
        except Exception as exc:  # noqa: BLE001
            log.error(
                "review_enqueue_failed",
                attempt_id=attempt_id,
                error=str(exc),
                hint="these errors will not resurface for review",
            )

    # Consume the item so it is not served again.
    client.table("generated_items").update({"consumed_at": "now()"}).eq(
        "id", item["id"]
    ).execute()

    return GradeOut(
        gradable=grade.gradable,
        ungradable_reason=grade.ungradable_reason,
        content_score=round(score.content_score, 2),
        language_score=round(score.language_score, 2),
        final_score=round(score.final_score, 2),
        key_point_verdicts=[
            {"id": v.key_point_id, "status": str(v.status), "why": v.reasoning}
            for v in grade.key_points
        ],
        errors=[
            ErrorTagOut(
                category=str(t.category),
                subcategory=str(t.subcategory),
                span=t.span,
                correction=t.correction,
                explanation=t.explanation,
                severity=str(t.severity),
            )
            for t in grade.language_errors
        ],
        feedback=grade.holistic_note,
    )


class TFStatementOut(BaseModel):
    id: str
    statement_arabic: str
    statement_english: str


class TrueFalseOut(BaseModel):
    item_id: str
    resource_id: str
    difficulty_cefr: str
    statements: list[TFStatementOut]


class TFAnswer(BaseModel):
    item_id: str
    # statement id -> the learner's verdict
    answers: dict[str, bool]


class TFVerdict(BaseModel):
    id: str
    statement_arabic: str
    correct: bool
    correct_answer: bool
    explanation: str
    source_quote: str


class TFResult(BaseModel):
    score: float
    correct_count: int
    total: int
    verdicts: list[TFVerdict]


@router.get("/true-false", response_model=TrueFalseOut)
def next_true_false(
    resource_id: str, user: AuthenticatedUser = Depends(current_user)
) -> TrueFalseOut:
    """Serve a true/false set, generating one if the bank has nothing unseen."""
    client = user_client(user.token)

    cached = (
        client.rpc("next_practice_item", {"p_user_id": user.id, "p_resource_id": resource_id})
        .execute()
    ).data
    cached_tf = [c for c in (cached or []) if c["item_type"] == "true_false"]
    if cached_tf:
        item = cached_tf[0]
        payload = item["payload"]
        return TrueFalseOut(
            item_id=item["id"],
            resource_id=item["resource_id"],
            difficulty_cefr=item["difficulty_cefr"],
            statements=[
                TFStatementOut(
                    id=s["id"],
                    statement_arabic=s["statement_arabic"],
                    statement_english=s["statement_english"],
                )
                for s in payload.get("statements", [])
            ],
        )

    retrieval = select_window(client, resource_id, user.id)
    if retrieval.is_empty:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "no material available to practise from. Either this resource has not "
                "finished processing, or your reading position is at the very beginning."
            ),
        )

    level = _current_level(client, user.id)
    call = call_skill(
        "generate-true-false",
        json.dumps(
            {
                "passage": retrieval.text,
                "chunk_ids": sorted(retrieval.chunk_ids),
                "target_cefr": level,
            },
            ensure_ascii=False,
        ),
    )
    call_id = record_call(client, call, user.id)

    if call.status != "ok":
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="could not generate statements; please try again",
        )

    result = call.parsed
    verdict = validate_true_false(result, retrieval.text, retrieval.chunk_ids)
    if not verdict.ok:
        log.warning("true_false_rejected", reasons=verdict.reasons)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="could not produce statements grounded in this passage",
        )
    if not result.answerable_from_source:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="this passage does not support true/false statements.",
        )

    row = (
        client.table("generated_items")
        .insert(
            {
                "user_id": user.id,
                "resource_id": resource_id,
                "item_type": "true_false",
                "payload": result.model_dump(mode="json"),
                "source_chunk_ids": sorted(retrieval.chunk_ids),
                "max_page": retrieval.max_page,
                "difficulty_cefr": result.difficulty_cefr,
                "model_call_id": call_id,
            }
        )
        .execute()
    )

    return TrueFalseOut(
        item_id=row.data[0]["id"],
        resource_id=resource_id,
        difficulty_cefr=result.difficulty_cefr,
        statements=[
            TFStatementOut(
                id=s.id,
                statement_arabic=s.statement_arabic,
                statement_english=s.statement_english,
            )
            for s in result.statements
        ],
    )


@router.post("/true-false/answer", response_model=TFResult)
def answer_true_false(
    body: TFAnswer, user: AuthenticatedUser = Depends(current_user)
) -> TFResult:
    """Mark a true/false set.

    No model call: the answers were decided at generation time and stored with
    their evidence. Grading is a comparison, and paying a model to compare two
    booleans would be absurd.
    """
    client = user_client(user.token)

    items = client.table("generated_items").select("*").eq("id", body.item_id).execute()
    if not items.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown item")
    item = items.data[0]
    statements = item["payload"].get("statements", [])

    verdicts: list[TFVerdict] = []
    correct_count = 0
    for s in statements:
        given = body.answers.get(s["id"])
        is_correct = given is not None and given == s["is_true"]
        correct_count += int(is_correct)
        verdicts.append(
            TFVerdict(
                id=s["id"],
                statement_arabic=s["statement_arabic"],
                correct=is_correct,
                correct_answer=s["is_true"],
                explanation=s["explanation"],
                source_quote=s["source_quote"],
            )
        )

    total = len(statements) or 1
    score = correct_count / total

    client.table("attempts").insert(
        {
            "user_id": user.id,
            "resource_id": item["resource_id"],
            "generated_item_id": item["id"],
            "mode": "questions",
            "item_type": "true_false",
            "prompt_text": " · ".join(s["statement_arabic"] for s in statements)[:2000],
            "user_answer": json.dumps(body.answers, ensure_ascii=False),
            "input_method": "typed",
            # True/false tests comprehension only — there is no written Arabic
            # to judge, so language_score stays null rather than being invented.
            "content_score": round(score, 3),
            "score": round(score, 3),
            "difficulty_cefr": item["difficulty_cefr"],
            "grade_payload": {"correct": correct_count, "total": len(statements)},
            "gradable": True,
        }
    ).execute()

    client.table("generated_items").update({"consumed_at": "now()"}).eq(
        "id", item["id"]
    ).execute()

    return TFResult(
        score=round(score, 2),
        correct_count=correct_count,
        total=len(statements),
        verdicts=verdicts,
    )


def _current_level(client, user_id: str) -> str:
    """The learner's level: stated first, measured second, A2 as a last resort."""
    from app.api.vocab import _current_level as resolve

    return resolve(client, user_id)
