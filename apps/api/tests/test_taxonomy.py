"""Tier 0 — error taxonomy. No network, no API key, no cost."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.grading import ErrorTag
from app.schemas.taxonomy import (
    VALID_PAIRS,
    ErrorCategory,
    ErrorSubcategory,
    is_valid_pair,
    load_taxonomy,
    render_for_prompt,
    subcategories_for,
)


def test_taxonomy_loads():
    data = load_taxonomy()
    assert data["categories"]
    assert data["severities"]


def test_spec_categories_all_present():
    """§5.6 names these seven groups explicitly."""
    expected = {
        "morphology", "syntax", "case_marking",
        "agreement", "lexis", "orthography", "discourse",
    }
    assert expected <= {str(c) for c in ErrorCategory}


def test_every_category_has_subcategories():
    for category in ErrorCategory:
        assert subcategories_for(category), f"{category} has none"


def test_valid_pair_accepts_real_pairs():
    assert is_valid_pair("orthography", "hamza")
    assert is_valid_pair("morphology", "broken_plural")
    assert is_valid_pair("case_marking", "accusative")


def test_valid_pair_rejects_crossed_pairs():
    """The flat subcategory enum alone would let these through."""
    assert not is_valid_pair("orthography", "broken_plural")
    assert not is_valid_pair("discourse", "hamza")
    assert not is_valid_pair("lexis", "nominative")


def test_error_tag_rejects_crossed_pair():
    with pytest.raises(ValidationError, match="not a subcategory"):
        ErrorTag(
            category="orthography",
            subcategory="broken_plural",
            span="كتابات",
            correction="كتب",
            explanation="Wrong plural.",
            severity="moderate",
        )


def test_error_tag_accepts_valid_pair():
    tag = ErrorTag(
        category="orthography",
        subcategory="hamza",
        span="سئل",
        correction="سأل",
        explanation="Wrong hamza seat.",
        severity="minor",
    )
    assert tag.category == ErrorCategory.ORTHOGRAPHY


def test_error_tag_rejects_unknown_category():
    """The closed enum makes an invented category structurally impossible."""
    with pytest.raises(ValidationError):
        ErrorTag(
            category="vibes",
            subcategory="hamza",
            span="x",
            correction="y",
            explanation="z",
            severity="minor",
        )


def test_error_tag_rejects_unknown_severity():
    with pytest.raises(ValidationError):
        ErrorTag(
            category="orthography",
            subcategory="hamza",
            span="x",
            correction="y",
            explanation="z",
            severity="catastrophic",
        )


def test_prompt_mentions_every_enum_member():
    """The model cannot emit what the prompt never showed it."""
    rendered = render_for_prompt()
    for category in ErrorCategory:
        assert f"`{category}`" in rendered, f"{category} missing from prompt"
    for subcategory in ErrorSubcategory:
        assert f"`{subcategory}`" in rendered, f"{subcategory} missing from prompt"


def test_prompt_mentions_severities():
    rendered = render_for_prompt()
    for severity in ("minor", "moderate", "blocking"):
        assert f"`{severity}`" in rendered


def test_render_is_deterministic():
    """A reordered prompt is a different prompt_hash for no reason."""
    assert render_for_prompt() == render_for_prompt()


def test_enum_order_is_sorted():
    names = [str(c) for c in ErrorCategory]
    assert names == sorted(names)


def test_valid_pairs_covers_every_subcategory():
    covered = {sub for _, sub in VALID_PAIRS}
    assert covered == {str(s) for s in ErrorSubcategory}
