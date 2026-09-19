"""Supabase JWT verification.

Supabase now signs access tokens with asymmetric keys (ES256) published at the
project's JWKS endpoint, with the legacy shared HS256 secret still valid for
tokens issued before a project switches over. Both can be in flight during a
changeover, so the token header's ``alg`` decides the path:

- ES256 / RS256 / EdDSA -> verify against the JWKS public key (preferred; no
  shared secret ever reaches this service)
- HS256                 -> verify against SUPABASE_JWT_SECRET, if configured

The JWKS is cached and force-refreshed once on an unknown ``kid``, so key
rotation does not require a redeploy.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx2 as httpx
import structlog
from fastapi import Depends, Header, HTTPException, status
from jose import jwt
from jose.exceptions import JWTError

from app.config import get_settings

log = structlog.get_logger()

JWKS_CACHE_SECONDS = 600
_ASYMMETRIC_ALGS = {"ES256", "RS256", "EdDSA"}

_jwks_cache: dict | None = None
_jwks_fetched_at: float = 0.0


@dataclass(frozen=True)
class AuthenticatedUser:
    """The caller. ``token`` is kept so handlers can build an RLS-scoped client."""

    id: str
    email: str | None
    token: str


def _fetch_jwks(force: bool = False) -> dict:
    global _jwks_cache, _jwks_fetched_at

    fresh = _jwks_cache is not None and (time.time() - _jwks_fetched_at) < JWKS_CACHE_SECONDS
    if fresh and not force:
        return _jwks_cache  # type: ignore[return-value]

    settings = get_settings()
    url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
    response = httpx.get(url, timeout=10.0)
    response.raise_for_status()

    _jwks_cache = response.json()
    _jwks_fetched_at = time.time()
    return _jwks_cache


def _key_for(kid: str | None) -> dict:
    jwks = _fetch_jwks()
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return key
    # Unknown kid: the project may have rotated keys. Refresh once before failing.
    for key in _fetch_jwks(force=True).get("keys", []):
        if key.get("kid") == kid:
            return key
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="token signing key not recognised",
    )


def verify_token(token: str) -> dict:
    """Verify a Supabase access token and return its claims."""
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="malformed token"
        ) from exc

    algorithm = header.get("alg")
    settings = get_settings()

    try:
        if algorithm in _ASYMMETRIC_ALGS:
            claims = jwt.decode(
                token,
                _key_for(header.get("kid")),
                algorithms=[algorithm],
                # Supabase sets aud to "authenticated"; tolerate its absence
                # rather than rejecting a valid token over an optional claim.
                options={"verify_aud": False},
            )
        elif algorithm == "HS256":
            if not settings.supabase_jwt_secret:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="legacy HS256 token received but SUPABASE_JWT_SECRET is unset",
                )
            claims = jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                options={"verify_aud": False},
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"unsupported token algorithm: {algorithm}",
            )
    except JWTError as exc:
        # Covers expiry and signature failure alike; do not leak which.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or expired token"
        ) from exc

    if not claims.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="token has no subject"
        )
    return claims


async def current_user(
    authorization: str | None = Header(default=None),
) -> AuthenticatedUser:
    """FastAPI dependency. Rejects anything that is not a valid Bearer token."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization.split(" ", 1)[1].strip()
    claims = verify_token(token)
    return AuthenticatedUser(
        id=claims["sub"], email=claims.get("email"), token=token
    )


CurrentUser = Depends(current_user)
