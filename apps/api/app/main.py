"""BeeHub API entrypoint."""

from __future__ import annotations

import logging

import structlog
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import learning, metrics, resources
from app.auth import AuthenticatedUser, current_user
from app.config import CONFIG_DIR, SKILLS_DIR, get_settings, verify_paths

settings = get_settings()

logging.basicConfig(level=settings.log_level)
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        logging.getLevelName(settings.log_level)
    ),
)
log = structlog.get_logger()

# Fail at import, not on the first practice request. skills/ and config/ live
# at the repo root, so a deployment whose build context is apps/api/ would
# otherwise boot green and die later with FileNotFoundError.
verify_paths()
log.info("prompt_paths_ok", skills=str(SKILLS_DIR), config=str(CONFIG_DIR))

app = FastAPI(title="BeeHub API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(resources.router)
app.include_router(learning.router)
app.include_router(metrics.router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe. Deliberately touches nothing external."""
    return {"status": "ok", "environment": settings.environment}


@app.get("/me")
def me(user: AuthenticatedUser = Depends(current_user)) -> dict[str, str | None]:
    """Round-trips the caller's JWT. Proves auth is wired end to end."""
    return {"id": user.id, "email": user.email}
