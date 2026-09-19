"""Ingestion worker.

Runs as a separate Railway process, polling ``ingest_jobs``. PDF parsing and
chunking are far too slow for a request cycle, and this keeps them off the API.

A Postgres-backed queue rather than Supabase Edge Functions, deliberately: the
worker then runs the same Python and the same PyMuPDF as the tests, so what CI
verifies is what production executes.

This is the one place the service client is legitimate — it writes chunks for a
user whose JWT it does not hold.

    python -m app.worker           # poll forever
    python -m app.worker --once    # drain and exit (CI, local)
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

import structlog

from app.config import get_settings
from app.db import service_client
from app.ingest.pipeline import ingest_pdf
from app.ingest.quality import IngestStatus

log = structlog.get_logger()

POLL_SECONDS = 5
MAX_ATTEMPTS = 3
# A job still 'running' after this long is assumed dead (worker crash/redeploy)
# and is retried rather than left stuck forever.
STALE_LOCK_SECONDS = 900


def claim_job(client) -> dict | None:
    """Claim the oldest queued job.

    Single-worker-safe. With several workers this needs SELECT ... FOR UPDATE
    SKIP LOCKED via a direct connection; Phase 1 runs one worker.
    """
    result = (
        client.table("ingest_jobs")
        .select("*")
        .eq("status", "queued")
        .order("created_at")
        .limit(1)
        .execute()
    )
    if not result.data:
        return None

    job = result.data[0]
    client.table("ingest_jobs").update(
        {"status": "running", "attempts": job["attempts"] + 1, "locked_at": "now()"}
    ).eq("id", job["id"]).execute()
    return job


def download_pdf(client, storage_path: str) -> bytes:
    settings = get_settings()
    return client.storage.from_(settings.storage_bucket).download(storage_path)


def process_job(client, job: dict) -> None:
    """Extract, gate, chunk, and store one resource."""
    resource_id = job["resource_id"]
    bound = log.bind(resource_id=resource_id, job_id=job["id"])

    resources = (
        client.table("resources").select("*").eq("id", resource_id).execute()
    )
    if not resources.data:
        bound.warning("resource_gone")
        client.table("ingest_jobs").update(
            {"status": "error", "last_error": "resource no longer exists"}
        ).eq("id", job["id"]).execute()
        return

    resource = resources.data[0]
    client.table("resources").update({"ingest_status": "extracting"}).eq(
        "id", resource_id
    ).execute()

    contents = download_pdf(client, resource["storage_path"])
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as handle:
        handle.write(contents)
        handle.flush()
        result = ingest_pdf(Path(handle.name))

    bound.info(
        "extraction_complete",
        status=str(result.status),
        pages=result.page_count,
        chunks=len(result.chunks),
    )

    # Record the verdict first, so a failure is visible even if the chunk
    # insert below goes wrong.
    client.table("resources").update(
        {
            "ingest_status": str(result.status),
            "ingest_report": result.report.to_dict(),
            "total_length": result.page_count,
        }
    ).eq("id", resource_id).execute()

    if result.status is IngestStatus.FAILED:
        # No chunks by construction — the pipeline refuses to produce them for
        # a failed document, so unreadable text cannot become practice (§5.2).
        bound.warning("ingest_failed", reasons=result.report.reasons)
        client.table("ingest_jobs").update({"status": "done"}).eq(
            "id", job["id"]
        ).execute()
        return

    # Replace rather than append, so a re-run is idempotent.
    client.table("resource_chunks").delete().eq("resource_id", resource_id).execute()

    from app.ingest.arabic_text import normalize_for_search

    rows = [
        {
            "resource_id": resource_id,
            "chunk_index": chunk.chunk_index,
            "text": chunk.text,
            "text_normalized": normalize_for_search(chunk.text),
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "char_start": chunk.char_start,
            "char_end": chunk.char_end,
            "token_estimate": chunk.token_estimate,
        }
        for chunk in result.chunks
    ]
    for start in range(0, len(rows), 200):
        client.table("resource_chunks").insert(rows[start : start + 200]).execute()

    bound.info("chunks_stored", count=len(rows))
    client.table("ingest_jobs").update({"status": "done"}).eq("id", job["id"]).execute()


def run_once(client) -> bool:
    """Process one job. Returns False when the queue is empty."""
    job = claim_job(client)
    if job is None:
        return False

    try:
        process_job(client, job)
    except Exception as exc:  # noqa: BLE001 — a bad PDF must not kill the worker
        log.error("job_failed", job_id=job["id"], error=str(exc), exc_info=True)
        terminal = job["attempts"] + 1 >= MAX_ATTEMPTS
        client.table("ingest_jobs").update(
            {"status": "error" if terminal else "queued", "last_error": str(exc)[:500]}
        ).eq("id", job["id"]).execute()
        if terminal:
            client.table("resources").update(
                {
                    "ingest_status": "failed",
                    "ingest_report": {
                        "status": "failed",
                        "reasons": [f"ingestion failed after {MAX_ATTEMPTS} attempts"],
                        "needs_ocr": False,
                    },
                }
            ).eq("id", job["resource_id"]).execute()
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="BeeHub ingestion worker")
    parser.add_argument("--once", action="store_true", help="drain the queue and exit")
    args = parser.parse_args()

    client = service_client()
    log.info("worker_started", mode="once" if args.once else "poll")

    if args.once:
        processed = 0
        while run_once(client):
            processed += 1
        log.info("worker_finished", processed=processed)
        return 0

    while True:
        try:
            if not run_once(client):
                time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            log.info("worker_stopped")
            return 0
        except Exception as exc:  # noqa: BLE001 — keep polling through transient faults
            log.error("poll_failed", error=str(exc))
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
