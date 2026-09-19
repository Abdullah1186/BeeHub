"""BeeHub API entrypoint."""

from __future__ import annotations

import logging

import structlog
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import resources
from app.auth import AuthenticatedUser, current_user
from app.config import get_settings

settings = get_settings()

logging.basicConfig(level=settings.log_level)
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        logging.getLevelName(settings.log_level)
    ),
)
log = structlog.get_logger()

app = FastAPI(title="BeeHub API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(resources.router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe. Deliberately touches nothing external."""
    return {"status": "ok", "environment": settings.environment}


@app.get("/me")
def me(user: AuthenticatedUser = Depends(current_user)) -> dict[str, str | None]:
    """Round-trips the caller's JWT. Proves auth is wired end to end."""
    return {"id": user.id, "email": user.email}
