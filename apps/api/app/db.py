"""Database access.

Two clients, deliberately separated:

- ``service_client()`` bypasses RLS. The ingestion worker needs it, because it
  writes chunks for a user whose JWT it does not hold.
- ``user_client(jwt)`` carries the caller's token, so every query is filtered by
  RLS as that user.

**Never use the service client in a request handler.** Doing so silently demotes
the §5.2 position gate from a database guarantee to an application promise: one
forgotten ``where user_id =`` and a learner sees another learner's material, or
their own unread pages.
"""

from __future__ import annotations

from functools import lru_cache

from supabase import Client, create_client

from app.config import get_settings


@lru_cache
def service_client() -> Client:
    """RLS-bypassing client. Worker and migrations only."""
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for the "
            "service client; see .env.example"
        )
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def user_client(access_token: str) -> Client:
    """Per-request client. Every query runs as the authenticated user."""
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_ANON_KEY are required; see .env.example"
        )
    client = create_client(settings.supabase_url, settings.supabase_anon_key)
    client.postgrest.auth(access_token)
    return client
