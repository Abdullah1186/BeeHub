"""Vocabulary endpoints (spec §2.3).

Words are harvested from the passages the learner has actually read, not from a
generic frequency list — that is the whole point of §2.3's "vocab is harvested
from the resources the user is actually reading".

Extraction runs on the `mechanical` pool (Haiku) because it is close to
mechanical: find the words, give the dictionary form and a gloss. It is gated by
position like everything else, so harvesting cannot leak unread pages.
"""

from __future__ import annotations

import json

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.ai.client import call_skill, record_call
from app.auth import AuthenticatedUser, current_user
from app.db import user_client
from app.ingest.arabic_text import normalize_for_search
from app.retrieval.selector import select_window

log = structlog.get_logger()
router = APIRouter(prefix="/vocab", tags=["vocab"])


class VocabCard(BaseModel):
    id: str
    arabic: str
    root: str | None = None
    pos: str | None = None
    translation: str
    context_sentence: str | None = None
    resource_id: str | None = None


class HarvestResult(BaseModel):
    added: int
    skipped_duplicates: int
    # Words the model found but that were discarded as damaged — split
    # mid-word by PDF extraction. Distinct from "found nothing", because the
    # cause and the fix are completely different: one means try another
    # passage, the other means this book extracts too poorly to teach from.
    rejected_damaged: int = 0
    items: list[VocabCard]


@router.get("/deck", response_model=list[VocabCard])
def deck(
    resource_id: str | None = None,
    limit: int = 50,
    user: AuthenticatedUser = Depends(current_user),
) -> list[VocabCard]:
    """The learner's cards, newest first."""
    client = user_client(user.token)
    query = (
        client.table("vocab_items")
        .select("id, arabic, root, pos, translation, context_sentence, resource_id")
        .order("first_seen_at", desc=True)
        .limit(min(limit, 200))
    )
    if resource_id:
        query = query.eq("resource_id", resource_id)
    return [VocabCard(**row) for row in (query.execute().data or [])]


class ManualVocab(BaseModel):
    """A word the learner picked out themselves."""

    arabic: str = Field(min_length=1, max_length=120)
    translation: str = Field(min_length=1, max_length=300)
    resource_id: str | None = None
    context_sentence: str | None = Field(default=None, max_length=1000)
    root: str | None = Field(default=None, max_length=40)
    pos: str | None = None


@router.post("/manual", response_model=VocabCard, status_code=status.HTTP_201_CREATED)
def add_manual(
    body: ManualVocab, user: AuthenticatedUser = Depends(current_user)
) -> VocabCard:
    """Add a word by hand.

    Harvesting decides for you what is worth learning; this is the escape
    hatch for when it is wrong — a word you hit while reading and want
    regardless of what the extractor judged.

    No fragmentation guard here: the learner typed or selected it, so if it
    contains a space that is their decision, not extraction damage.
    """
    client = user_client(user.token)
    arabic = body.arabic.strip()

    row = {
        "user_id": user.id,
        "resource_id": body.resource_id,
        "arabic": arabic,
        "arabic_normalized": normalize_for_search(arabic),
        "translation": body.translation.strip(),
        "context_sentence": body.context_sentence,
        "root": body.root,
        "pos": body.pos,
    }

    try:
        result = client.table("vocab_items").insert(row).execute()
    except Exception as exc:
        # unique (user_id, arabic_normalized)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="that word is already in your vocabulary",
        ) from exc

    saved = result.data[0]
    log.info("vocab_added_manually", word=arabic)
    return VocabCard(
        id=saved["id"],
        arabic=arabic,
        root=body.root,
        pos=body.pos,
        translation=body.translation,
        context_sentence=body.context_sentence,
        resource_id=body.resource_id,
    )


@router.get("/chunks/{resource_id}", response_model=list[dict])
def resource_text(
    resource_id: str, user: AuthenticatedUser = Depends(current_user)
) -> list[dict]:
    """The readable text of a resource, gated by position.

    This is what the manual-selection UI reads from: the learner sees the
    passages they have actually reached and taps a word. Gated like everything
    else, so picking words cannot leak unread pages.
    """
    from app.retrieval.selector import resolve_max_page

    client = user_client(user.token)
    max_page = resolve_max_page(client, resource_id, user.id)
    if max_page < 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")

    rows = (
        client.table("resource_chunks")
        .select("id, chunk_index, text, page_start")
        .eq("resource_id", resource_id)
        .lte("page_end", max_page)
        .order("chunk_index")
        .limit(200)
        .execute()
    ).data or []
    return rows


@router.post("/harvest", response_model=HarvestResult)
def harvest(
    resource_id: str,
    user: AuthenticatedUser = Depends(current_user),
) -> HarvestResult:
    """Extract vocabulary from a passage the learner has read.

    Uses the same gated window as question generation, so a word can never come
    from a page beyond their position.
    """
    client = user_client(user.token)

    retrieval = select_window(client, resource_id, user.id, window=2)
    if retrieval.is_empty:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "no material available to harvest from. The resource may still be "
                "processing, or your reading position may be at the very beginning."
            ),
        )

    level = _current_level(client, user.id)

    # Tell the model which words the learner already has.
    #
    # Without this it can only guess from a CEFR level — "an A2 learner knows
    # ذهب" — which is a guess about a level that, before the estimation job
    # exists, is itself a default. Passing the actual deck turns a guess into
    # a fact for the words we know about.
    known = [
        row["arabic"]
        for row in (
            client.table("vocab_items")
            .select("arabic")
            .order("first_seen_at", desc=True)
            .limit(300)
            .execute()
            .data
            or []
        )
    ]

    call = call_skill(
        "extract-vocab-from-chunk",
        json.dumps(
            {
                "passage": retrieval.text,
                "learner_level": level,
                "already_known": known,
            },
            ensure_ascii=False,
        ),
    )
    record_call(client, call, user.id)

    if call.status != "ok":
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="vocabulary extraction failed; please try again",
        )

    added: list[VocabCard] = []
    skipped = 0
    rejected = 0

    for item in call.parsed.items:
        # Grounding, same rule as questions: the context sentence must actually
        # appear in the passage. A fabricated example teaches the word wrong.
        if item.context_sentence.strip() and item.context_sentence not in retrieval.text:
            log.warning("vocab_context_not_verbatim", word=item.arabic)
            rejected += 1
            continue

        # Reject words damaged by extraction, rather than teaching them.
        #
        # The quality gate marks a resource `degraded` when words are split
        # mid-word, but it lets practice continue because comprehension still
        # works on the intact passages. Vocabulary is different: a card is the
        # word, so a broken one teaches a spelling that does not exist.
        # Harvesting في القدس produced "نحمل ها" — حملها with a stray space.
        if not _is_intact_word(item.arabic, item.pos):
            log.warning("vocab_word_fragmented", word=item.arabic)
            rejected += 1
            continue

        normalized = normalize_for_search(item.arabic)
        try:
            row = (
                client.table("vocab_items")
                .insert(
                    {
                        "user_id": user.id,
                        "resource_id": resource_id,
                        "arabic": item.arabic,
                        "arabic_normalized": normalized,
                        "root": item.root,
                        "pos": item.pos,
                        "translation": item.translation,
                        "context_sentence": item.context_sentence,
                    }
                )
                .execute()
            )
            added.append(VocabCard(**{
                "id": row.data[0]["id"],
                "arabic": item.arabic,
                "root": item.root,
                "pos": item.pos,
                "translation": item.translation,
                "context_sentence": item.context_sentence,
                "resource_id": resource_id,
            }))
        except Exception:
            # unique (user_id, arabic_normalized) — already known. Not an error:
            # re-harvesting a passage should be idempotent.
            skipped += 1

    log.info(
        "vocab_harvested",
        added=len(added),
        skipped=skipped,
        rejected=rejected,
        resource=resource_id,
    )
    return HarvestResult(
        added=len(added),
        skipped_duplicates=skipped,
        rejected_damaged=rejected,
        items=added,
    )


def _is_intact_word(arabic: str, pos: str | None = None) -> bool:
    """Whether a harvested entry looks like a real word rather than fragments.

    A single Arabic word never contains a space, so part-of-speech decides how
    many parts are allowed: a noun, verb or adjective must be ONE token, while
    ``phrase`` may be several.

    Length alone is not enough to catch fragmentation — extraction splits words
    into pieces that are themselves two letters (``تَز ور ها`` for تزورها,
    ``نحمل ها`` for نحملها), so those pieces pass a minimum-length test while
    being nonsense. Requiring single-token-ness for single-word parts of speech
    is what actually works.
    """
    parts = [p for p in arabic.strip().split() if p]
    if not parts:
        return False

    if pos == "phrase":
        # An idiom may be several words, but each must be a plausible word and
        # the whole thing must stay short.
        return len(parts) <= 4 and all(len(p) >= 2 for p in parts)

    # Everything else is one word by definition.
    return len(parts) == 1 and len(parts[0]) >= 2


def _current_level(client, user_id: str) -> str:
    """The learner's level, preferring what they told us.

    Order matters. A stated level is a fact about the learner; a measured
    estimate is inference from a handful of answers. Before §5.7's estimation
    job exists there is nothing measured at all, which is why this used to
    return a hardcoded A2 for everyone — and why a self-reported A1 learner
    was being served B1-filtered vocabulary.
    """
    profile = (
        client.table("profiles").select("target_level").eq("id", user_id).execute()
    ).data
    if profile and profile[0].get("target_level"):
        return profile[0]["target_level"]

    measured = (
        client.table("level_estimates")
        .select("cefr_level")
        .eq("skill", "reading")
        .order("computed_at", desc=True)
        .limit(1)
        .execute()
    ).data
    return measured[0]["cefr_level"] if measured else "A2"
