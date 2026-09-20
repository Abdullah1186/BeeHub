"""Application settings, loaded from the environment.

Secrets live in env vars only (spec §7). `.env.example` documents every key.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# skills/ and config/ live inside apps/api, alongside app/, so the backend is a
# self-contained deployable unit. No discovery, no env vars, no build-context
# gymnastics: the path is fixed relative to this file.
#
#   apps/api/app/config.py -> parents[1] is apps/api
#
# (app/skills/ is the Python package that LOADS these files; apps/api/skills/ is
# the prompt markdown itself. Different things, deliberately kept apart.)
API_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = API_ROOT / "skills"
CONFIG_DIR = API_ROOT / "config"

# The repo root, for things that genuinely live above the backend (.env, evals).
REPO_ROOT = API_ROOT.parents[1]
EVALS_DIR = REPO_ROOT / "evals"


def verify_paths() -> None:
    """Fail at startup rather than on the first practice request."""
    missing = []
    if not (SKILLS_DIR / "_shared" / "error-taxonomy.yaml").is_file():
        missing.append(f"skills not found at {SKILLS_DIR}")
    if not (CONFIG_DIR / "models.yaml").is_file():
        missing.append(f"config/models.yaml not found at {CONFIG_DIR}")
    if missing:
        raise RuntimeError(
            "BeeHub cannot find its prompt files:\n  " + "\n  ".join(missing)
        )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173"

    anthropic_api_key: str = ""
    voyage_api_key: str = ""

    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    # Legacy HS256 signing secret. Only needed while a project still has
    # pre-migration tokens in flight; ES256 tokens verify via JWKS instead.
    supabase_jwt_secret: str = ""
    database_url: str = ""

    # Supabase Storage bucket holding uploaded PDFs.
    storage_bucket: str = "resources"
    max_upload_mb: int = 50

    # Must stay False in production: a mid-request skill change breaks the cached
    # prefix and produces two different results under one recorded prompt_hash.
    reload_skills: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
