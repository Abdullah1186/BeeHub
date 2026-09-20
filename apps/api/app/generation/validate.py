"""Grounding enforcement (spec §5.2).

The rule: a generated question must cite chunks it actually came from, and every
claim must be traceable to the retrieved text. An ungrounded question is worse
than no question — the learner answers correctly from the page and is marked
wrong, which destroys trust in every metric downstream.

Chunk IDs alone are not enough. A model can echo back the IDs it was given while
inventing content. **The verbatim quote check is what actually catches
hallucination**, because reproducing exact Arabic from a passage is something a
model cannot do for text that was never there.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

import structlog

from app.schemas.grading import ComprehensionQuestion

log = structlog.get_logger()

_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    reasons: list[str]

    @property
    def detail(self) -> str:
        return "; ".join(self.reasons)


def _canonical(text: str) -> str:
    """Normalise only whitespace and Unicode form for substring comparison.

    Deliberately conservative: diacritics and letter forms are preserved, so a
    quote that silently "corrects" the source still fails. Only differences that
    cannot carry meaning are ignored.
    """
    return _WS.sub(" ", unicodedata.normalize("NFKC", text)).strip()


def validate_question(
    question: ComprehensionQuestion,
    passage: str,
    allowed_chunk_ids: set[str],
) -> ValidationResult:
    """Check a generated question against the passage it was built from."""
    reasons: list[str] = []

    # A refusal is valid output, not a failure — but it must be empty-handed.
    if not question.answerable_from_source:
        if question.key_points:
            reasons.append("declared unanswerable but still returned key points")
        if question.question_arabic.strip():
            reasons.append("declared unanswerable but still returned a question")
        return ValidationResult(not reasons, reasons)

    if not question.question_arabic.strip():
        reasons.append("empty question")
    if not question.key_points:
        reasons.append("no key points")

    # Citations must come from the retrieval set, not from thin air.
    cited = set(question.source_chunk_ids)
    if not cited:
        reasons.append("no source_chunk_ids")
    elif not cited <= allowed_chunk_ids:
        stray = sorted(cited - allowed_chunk_ids)
        reasons.append(f"cites chunks outside the retrieval set: {stray}")

    # The check that matters: every quote must actually be in the passage.
    canonical_passage = _canonical(passage)
    for kp in question.key_points:
        quote = _canonical(kp.source_quote)
        if not quote:
            reasons.append(f"{kp.id}: empty source_quote")
        elif quote not in canonical_passage:
            reasons.append(
                f"{kp.id}: source_quote is not verbatim in the passage "
                f"({kp.source_quote[:40]!r})"
            )

    return ValidationResult(not reasons, reasons)


def validate_or_none(
    question: ComprehensionQuestion,
    passage: str,
    allowed_chunk_ids: set[str],
) -> ComprehensionQuestion | None:
    """Return the question only if it is grounded; otherwise None."""
    result = validate_question(question, passage, allowed_chunk_ids)
    if result.ok:
        return question
    log.warning("generated_item_rejected", reasons=result.reasons)
    return None
