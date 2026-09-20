"""Resource endpoints: upload, register, list, and position tracking.

Every handler uses an RLS-scoped client built from the caller's JWT. The service
client is not imported here on purpose — see app/db.py.

Position matters more than it looks. §5.2 forbids generating practice from
material the learner has not reached, so a PDF arrives with an explicit starting
position (defaulting to page 1) rather than silently defaulting to the whole
document.
"""

from __future__ import annotations

import uuid
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.auth import AuthenticatedUser, current_user
from app.config import get_settings
from app.db import user_client

log = structlog.get_logger()
router = APIRouter(prefix="/resources", tags=["resources"])

ResourceType = Literal["pdf", "book", "poetry", "video", "podcast"]
PositionUnit = Literal["page", "minute", "percent"]
CEFRLevel = Literal["A1", "A2", "B1", "B2", "C1", "C2"]


class ResourceCreate(BaseModel):
    """Register a resource with no file — a paper book, a video, a podcast."""

    title: str = Field(min_length=1, max_length=500)
    type: ResourceType
    author: str | None = None
    url: str | None = None
    level_hint: CEFRLevel | None = None
    tags: list[str] = Field(default_factory=list)
    position_value: int | None = Field(default=None, ge=0)
    position_unit: PositionUnit | None = None
    total_length: int | None = Field(default=None, ge=0)


class PositionUpdate(BaseModel):
    """Move the learner's position.

    Lowering it is legitimate — re-reading, or correcting a mistake — and the
    gate re-applies at serve time, so already-generated items that fall out of
    range stop being served.
    """

    position_value: int = Field(ge=0)
    position_unit: PositionUnit | None = None


class ResourceOut(BaseModel):
    id: str
    title: str
    type: str
    author: str | None = None
    url: str | None = None
    level_hint: str | None = None
    tags: list[str] = Field(default_factory=list)
    position_value: int | None = None
    position_unit: str | None = None
    total_length: int | None = None
    ingest_status: str
    ingest_report: dict = Field(default_factory=dict)
    created_at: str | None = None


@router.post("", response_model=ResourceOut, status_code=status.HTTP_201_CREATED)
def register_resource(
    body: ResourceCreate, user: AuthenticatedUser = Depends(current_user)
) -> ResourceOut:
    """Register a resource that has no uploaded file."""
    if body.type == "pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="upload PDFs via POST /resources/upload",
        )

    client = user_client(user.token)
    payload = body.model_dump(exclude_none=True)
    payload["user_id"] = user.id
    # Nothing to extract, so these are immediately usable.
    payload["ingest_status"] = "ok"

    result = client.table("resources").insert(payload).execute()
    return ResourceOut(**result.data[0])


@router.post("/upload", response_model=ResourceOut, status_code=status.HTTP_201_CREATED)
async def upload_pdf(
    file: UploadFile = File(...),
    title: str = Form(...),
    author: str | None = Form(default=None),
    level_hint: str | None = Form(default=None),
    # Explicit starting position. Defaults to page 1 rather than the whole
    # document, so the §5.2 gate is meaningful from the first question.
    position_value: int = Form(default=1),
    user: AuthenticatedUser = Depends(current_user),
) -> ResourceOut:
    """Upload a PDF, store it, and queue it for extraction."""
    settings = get_settings()

    if file.content_type not in ("application/pdf", "application/x-pdf"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"expected a PDF, got {file.content_type}",
        )

    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)
    if size_mb > settings.max_upload_mb:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"file is {size_mb:.1f} MB; the limit is {settings.max_upload_mb} MB",
        )
    if not contents.startswith(b"%PDF"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="file does not look like a PDF",
        )

    client = user_client(user.token)
    resource_id = str(uuid.uuid4())
    # User-scoped prefix so storage policies can mirror the table's RLS.
    storage_path = f"{user.id}/{resource_id}.pdf"

    try:
        client.storage.from_(settings.storage_bucket).upload(
            storage_path, contents, {"content-type": "application/pdf"}
        )
    except Exception as exc:
        log.error("storage_upload_failed", resource_id=resource_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="could not store the file"
        ) from exc

    row = {
        "id": resource_id,
        "user_id": user.id,
        "title": title,
        "type": "pdf",
        "author": author,
        "level_hint": level_hint,
        "storage_path": storage_path,
        "position_value": position_value,
        "position_unit": "page",
        "ingest_status": "pending",
    }
    result = client.table("resources").insert(row).execute()

    # Queue extraction. The worker polls this table; nothing heavy happens in
    # the request cycle.
    #
    # This is NOT transactional with the insert above, so a failure here would
    # otherwise leave a resource stuck at `pending` with no job to process it —
    # invisible except as a queue entry that never moves. That happened for
    # real when ingest_jobs was missing an INSERT policy. Clean up and fail
    # loudly instead of returning a half-created resource.
    try:
        client.table("ingest_jobs").insert({"resource_id": resource_id}).execute()
    except Exception as exc:
        log.error("queue_failed_rolling_back", resource_id=resource_id, error=str(exc))
        try:
            client.table("resources").delete().eq("id", resource_id).execute()
            client.storage.from_(settings.storage_bucket).remove([storage_path])
        except Exception as cleanup_exc:  # noqa: BLE001
            log.error("rollback_incomplete", resource_id=resource_id, error=str(cleanup_exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="could not queue the file for processing; nothing was saved",
        ) from exc

    log.info("resource_uploaded", resource_id=resource_id, size_mb=round(size_mb, 2))
    return ResourceOut(**result.data[0])


@router.get("", response_model=list[ResourceOut])
def list_resources(user: AuthenticatedUser = Depends(current_user)) -> list[ResourceOut]:
    client = user_client(user.token)
    result = (
        client.table("resources")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    return [ResourceOut(**row) for row in result.data]


@router.get("/{resource_id}", response_model=ResourceOut)
def get_resource(
    resource_id: str, user: AuthenticatedUser = Depends(current_user)
) -> ResourceOut:
    client = user_client(user.token)
    result = client.table("resources").select("*").eq("id", resource_id).execute()
    if not result.data:
        # RLS already hides other users' rows, so "not found" is also the
        # correct answer for "not yours" — and leaks nothing either way.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return ResourceOut(**result.data[0])


@router.delete("/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_resource(
    resource_id: str, user: AuthenticatedUser = Depends(current_user)
) -> None:
    """Delete a resource and everything derived from it.

    Chunks, generated questions and ingestion jobs go with it via ON DELETE
    CASCADE. Attempts and vocabulary survive: they are the learner's own record
    of work done, and `resource_id` is ON DELETE SET NULL on both, so history
    stays intact after the book is gone.

    The stored PDF is removed too — leaving orphaned files in the bucket costs
    money and leaks content that the user asked to be rid of.
    """
    settings = get_settings()
    client = user_client(user.token)

    existing = (
        client.table("resources")
        .select("id, storage_path")
        .eq("id", resource_id)
        .execute()
    )
    if not existing.data:
        # RLS already hides other users' rows, so "not found" is also the right
        # answer for "not yours" — and leaks neither.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")

    storage_path = existing.data[0].get("storage_path")

    # Delete the row first: the row is what the app reads, so if the storage
    # removal fails we are left with an unreferenced file rather than a
    # resource pointing at a file that is gone.
    client.table("resources").delete().eq("id", resource_id).execute()

    if storage_path:
        try:
            client.storage.from_(settings.storage_bucket).remove([storage_path])
        except Exception as exc:  # noqa: BLE001
            log.error(
                "storage_delete_failed",
                resource_id=resource_id,
                path=storage_path,
                error=str(exc),
                hint="row is deleted; this file is now orphaned in the bucket",
            )

    log.info("resource_deleted", resource_id=resource_id)


@router.patch("/{resource_id}/position", response_model=ResourceOut)
def update_position(
    resource_id: str,
    body: PositionUpdate,
    user: AuthenticatedUser = Depends(current_user),
) -> ResourceOut:
    """Update how far the learner has read. Drives the §5.2 gate."""
    client = user_client(user.token)

    existing = (
        client.table("resources")
        .select("total_length")
        .eq("id", resource_id)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")

    total = existing.data[0].get("total_length")
    if total is not None and body.position_value > total:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"position {body.position_value} exceeds the resource length ({total})",
        )

    result = (
        client.table("resources")
        .update(body.model_dump(exclude_none=True))
        .eq("id", resource_id)
        .execute()
    )
    return ResourceOut(**result.data[0])
