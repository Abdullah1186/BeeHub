"""Settings endpoints (spec §2.6).

Target level, daily goal, and dialect preference. The level matters beyond
display: it is what the vocabulary extractor uses to decide how much
elementary vocabulary to skip, so a wrong level directly changes what the
learner is taught.
"""

from __future__ import annotations

from typing import Literal

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth import AuthenticatedUser, current_user
from app.db import user_client

log = structlog.get_logger()
router = APIRouter(prefix="/settings", tags=["settings"])

CEFRLevel = Literal["A1", "A2", "B1", "B2", "C1", "C2"]


class Settings(BaseModel):
    # The level the learner says they are at. Distinct from the measured
    # estimate in level_estimates: this one is theirs to set, and is used
    # until enough graded answers exist to measure one.
    target_level: CEFRLevel | None = None
    daily_goal: int = Field(default=10, ge=1, le=200)
    dialect_pref: str = "MSA"


class SettingsUpdate(BaseModel):
    target_level: CEFRLevel | None = None
    daily_goal: int | None = Field(default=None, ge=1, le=200)
    dialect_pref: str | None = None


@router.get("", response_model=Settings)
def get_settings_(user: AuthenticatedUser = Depends(current_user)) -> Settings:
    client = user_client(user.token)
    rows = (
        client.table("profiles")
        .select("target_level, daily_goal, dialect_pref")
        .eq("id", user.id)
        .execute()
    ).data
    return Settings(**rows[0]) if rows else Settings()


@router.patch("", response_model=Settings)
def update_settings(
    body: SettingsUpdate, user: AuthenticatedUser = Depends(current_user)
) -> Settings:
    client = user_client(user.token)
    payload = body.model_dump(exclude_none=True)
    if not payload:
        return get_settings_(user)

    result = (
        client.table("profiles").update(payload).eq("id", user.id).execute()
    )
    log.info("settings_updated", fields=sorted(payload))
    return Settings(**result.data[0]) if result.data else Settings(**payload)
