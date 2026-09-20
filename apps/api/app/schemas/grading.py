"""Structured output models for generation and grading.

These are passed to ``client.messages.parse(output_format=...)``, so the shape
here IS the contract with the model — constrained decoding guarantees a
conforming object rather than hoping the prompt was obeyed.

The central design choice (plan §3): key points are produced at GENERATION time,
each with a verbatim supporting quote. Grading then only decides, per key point,
whether the learner conveyed it — a far more repeatable judgement than "grade
this answer", and it rides along on the generation call at no extra cost.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.taxonomy import ErrorCategory, ErrorSubcategory, is_valid_pair

CEFRLevel = Literal["A1", "A2", "B1", "B2", "C1", "C2"]


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


class KeyPoint(BaseModel):
    """One fact a correct answer must contain, with its evidence."""

    id: str = Field(description="Stable identifier, e.g. 'kp1'.")
    text: str = Field(description="The fact, stated in English, that the answer must convey.")
    source_quote: str = Field(
        description=(
            "VERBATIM Arabic from the source passage supporting this point. Must be "
            "copied exactly — it is checked as a substring of the retrieved text."
        )
    )


class ComprehensionQuestion(BaseModel):
    """A grounded comprehension question. Output of generate-comprehension-questions."""

    question_arabic: str = Field(description="The question, in Modern Standard Arabic.")
    question_english: str = Field(description="English gloss, shown only on request.")
    # NOT min_length=1: a refusal (answerable_from_source=False) must return an
    # empty list, and §5.2 makes refusing the correct behaviour for a passage
    # that cannot support a question. A schema that forbids the refusal forces
    # the model to invent one instead. The model_validator below enforces the
    # real rule: non-empty when answerable, empty when not.
    key_points: list[KeyPoint] = Field(
        default_factory=list,
        max_length=3,
        description="The 1-3 facts a correct answer must convey. Empty if unanswerable.",
    )
    source_chunk_ids: list[str] = Field(
        min_length=1, description="IDs of the chunks this question was built from."
    )
    difficulty_cefr: CEFRLevel
    answerable_from_source: bool = Field(
        description=(
            "False if the passage does not actually support a question. Emitting "
            "False is correct behaviour, not a failure — an ungrounded question is "
            "worse than none."
        )
    )

    @model_validator(mode="after")
    def answerable_implies_key_points(self) -> ComprehensionQuestion:
        if self.answerable_from_source and not self.key_points:
            raise ValueError(
                "answerable_from_source is True but no key points were given"
            )
        return self


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------


class KeyPointVerdict(BaseModel):
    """Whether the learner conveyed one key point."""

    key_point_id: str
    status: Literal["conveyed", "partially_conveyed", "absent", "contradicted"] = Field(
        description=(
            "'contradicted' means the learner asserted the opposite — this is what a "
            "near-miss looks like and must be distinguished from simply not mentioning it."
        )
    )
    evidence_span: str | None = Field(
        default=None, description="Verbatim substring of the LEARNER's answer, if any."
    )
    reasoning: str = Field(max_length=300, description="One sentence, in English.")


class ErrorTag(BaseModel):
    """One grammar error, constrained to the controlled vocabulary (§5.6)."""

    category: ErrorCategory
    subcategory: ErrorSubcategory
    span: str = Field(description="Verbatim substring of the learner's answer.")
    correction: str = Field(description="The corrected form of that span.")
    explanation: str = Field(max_length=300, description="One sentence, in English.")
    severity: Literal["minor", "moderate", "blocking"]

    @model_validator(mode="after")
    def check_pair(self) -> ErrorTag:
        # The flat subcategory enum would otherwise accept
        # `orthography/broken_plural`.
        if not is_valid_pair(self.category, self.subcategory):
            raise ValueError(
                f"'{self.subcategory}' is not a subcategory of '{self.category}'"
            )
        return self


class ShortAnswerGrade(BaseModel):
    """Output of grade-short-answer. Grading and tagging in one call."""

    gradable: bool = Field(
        description=(
            "False when the answer cannot be graded against the source or rubric — "
            "blank, off-language, or unintelligible. Spec §7: never invent a mark."
        )
    )
    ungradable_reason: str | None = None

    key_points: list[KeyPointVerdict] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(
        default_factory=list,
        description=(
            "Assertions absent from the source. Surfaced to the learner but NOT "
            "penalised — the question tests comprehension, not recall of everything."
        ),
    )
    is_off_topic: bool = False

    language_errors: list[ErrorTag] = Field(default_factory=list)

    model_comprehension_score: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "The model's own holistic judgement. RECORDED BUT NOT USED for the grade — "
            "it is a disagreement signal against the computed score."
        ),
    )
    holistic_note: str = Field(max_length=500, description="Feedback for the learner, in English.")

    @field_validator("ungradable_reason")
    @classmethod
    def reason_is_text(cls, v: str | None) -> str | None:
        return v.strip() if v and v.strip() else None

    @model_validator(mode="after")
    def ungradable_needs_reason(self) -> ShortAnswerGrade:
        if not self.gradable and not self.ungradable_reason:
            raise ValueError("ungradable_reason is required when gradable is False")
        return self


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


class VocabItem(BaseModel):
    """One harvested vocabulary item. Output of extract-vocab-from-chunk."""

    arabic: str = Field(description="The word as it appears, diacritics preserved.")
    lemma: str = Field(description="Dictionary form.")
    root: str | None = Field(default=None, description="Triliteral/quadriliteral root if clear.")
    pos: Literal["noun", "verb", "adjective", "adverb", "particle", "phrase"]
    translation: str = Field(description="Concise English gloss.")
    context_sentence: str = Field(
        description="The sentence from the source containing it, copied verbatim."
    )
    difficulty_cefr: CEFRLevel


class VocabExtraction(BaseModel):
    # 12 to match the skill's cap, with headroom.
    items: list[VocabItem] = Field(default_factory=list, max_length=20)


class WordTranslation(BaseModel):
    """One word's meaning in context. Output of translate-word."""

    translatable: bool = Field(
        description="False when the word is damaged or not Arabic; never guess."
    )
    translation: str = Field(description="Concise English gloss, flashcard-sized.")
    lemma: str = Field(description="Dictionary form.")
    root: str | None = Field(default=None, description="Root if clear, else null.")
    pos: Literal["noun", "verb", "adjective", "adverb", "particle", "phrase"]
    note: str | None = Field(
        default=None, max_length=200, description="One short remark, if useful."
    )
