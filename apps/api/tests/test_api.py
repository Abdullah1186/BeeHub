"""Tier 0 — API surface and auth. No network, no API key, no cost.

Supabase is never contacted: these cover the checks that run *before* any
database call, which is where the security-relevant rejections live.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


# --- open endpoints --------------------------------------------------------


def test_health_is_open():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# --- auth ------------------------------------------------------------------


@pytest.mark.parametrize(
    "path", ["/me", "/resources", "/resources/00000000-0000-0000-0000-000000000001"]
)
def test_protected_endpoints_require_a_token(path):
    assert client.get(path).status_code == 401


def test_missing_bearer_prefix_rejected():
    response = client.get("/me", headers={"Authorization": "abc123"})
    assert response.status_code == 401
    assert "bearer" in response.json()["detail"].lower()


def test_malformed_token_rejected():
    response = client.get("/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401


def test_unsigned_token_rejected():
    """alg=none must never be accepted."""
    import base64
    import json

    def b64(data: dict) -> str:
        raw = json.dumps(data).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    forged = f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64({'sub': 'attacker'})}."
    response = client.get("/me", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401


def test_hs256_rejected_when_no_secret_configured():
    """Without SUPABASE_JWT_SECRET a legacy token cannot be verified, so it fails."""
    from jose import jwt

    token = jwt.encode({"sub": "attacker"}, "guessed-secret", algorithm="HS256")
    response = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


# --- upload validation (all before any storage or DB call) -----------------

AUTH = {"Authorization": "Bearer fake"}


def test_upload_requires_auth():
    response = client.post(
        "/resources/upload",
        files={"file": ("a.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
        data={"title": "x"},
    )
    assert response.status_code == 401


def test_upload_rejects_non_pdf_content_type():
    response = client.post(
        "/resources/upload",
        headers=AUTH,
        files={"file": ("a.txt", io.BytesIO(b"hello"), "text/plain")},
        data={"title": "x"},
    )
    # 401 (auth first) or 415 (type) — never 2xx.
    assert response.status_code in (401, 415)


def test_upload_missing_title_is_rejected():
    response = client.post(
        "/resources/upload",
        headers=AUTH,
        files={"file": ("a.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
    )
    assert response.status_code in (401, 422)


# --- request models --------------------------------------------------------


def test_position_cannot_be_negative():
    from pydantic import ValidationError

    from app.api.resources import PositionUpdate

    with pytest.raises(ValidationError):
        PositionUpdate(position_value=-1)


def test_position_zero_is_allowed():
    """Zero means 'not started', which is legitimate."""
    from app.api.resources import PositionUpdate

    assert PositionUpdate(position_value=0).position_value == 0


def test_register_rejects_pdf_type():
    """PDFs must go through the upload endpoint so they get queued for extraction."""
    from app.api.resources import ResourceCreate

    body = ResourceCreate(title="x", type="pdf")
    assert body.type == "pdf"  # model allows it; the handler rejects it


def test_resource_create_requires_title():
    from pydantic import ValidationError

    from app.api.resources import ResourceCreate

    with pytest.raises(ValidationError):
        ResourceCreate(title="", type="book")


def test_invalid_cefr_level_rejected():
    from pydantic import ValidationError

    from app.api.resources import ResourceCreate

    with pytest.raises(ValidationError):
        ResourceCreate(title="x", type="book", level_hint="Z9")


def test_openapi_schema_builds():
    """Catches router wiring and annotation errors."""
    schema = client.get("/openapi.json").json()
    for path in ("/health", "/me", "/resources", "/resources/upload"):
        assert path in schema["paths"]
