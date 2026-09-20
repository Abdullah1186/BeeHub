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
from supabase.lib.client_options import SyncClientOptions

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
    # The token must reach EVERY sub-client, not just postgrest.
    #
    # `client.postgrest.auth(token)` alone authenticates database calls but
    # leaves storage on the anon key, so uploads run as an anonymous user and
    # storage RLS rejects them ("new row violates row-level security policy")
    # while table queries succeed — a confusing split that took a live upload
    # to surface. Setting the Authorization header at construction covers all
    # of them.
    client = create_client(
        settings.supabase_url,
        settings.supabase_anon_key,
        options=SyncClientOptions(
            headers={"Authorization": f"Bearer {access_token}"}
        ),
    )
    client.postgrest.auth(access_token)
    return client
