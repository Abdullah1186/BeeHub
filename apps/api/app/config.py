"""Application settings, loaded from the environment.

Secrets live in env vars only (spec §7). `.env.example` documents every key.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root, from apps/api/app/config.py -> ../../../
REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / "skills"
CONFIG_DIR = REPO_ROOT / "config"
EVALS_DIR = REPO_ROOT / "evals"


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
    database_url: str = ""

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
