"""Tier 0 — ingestion worker. No network, no API key, no cost.

Uses a fake Supabase client so the worker's control flow can be exercised
offline: what it writes, what it retries, and — most importantly — that a
failed quality gate results in zero chunks.
"""

from __future__ import annotations

import os

import pymupdf
import pytest

from app import worker

FONT = next(
    (
        f
        for f in (
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "/Library/Fonts/Arial Unicode.ttf",
        )
        if os.path.exists(f)
    ),
    None,
)


class FakeTable:
    def __init__(self, store: dict, name: str):
        self.store = store
        self.name = name
        self._filters: list[tuple[str, object]] = []
        self._in_filters: list[tuple[str, set]] = []
        self._op: str | None = None
        self._payload = None

    def select(self, *_a, **_k):
        self._op = "select"
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def delete(self):
        self._op = "delete"
        return self

    def eq(self, column, value):
        self._filters.append((column, value))
        return self

    def in_(self, column, values):
        self._in_filters.append((column, set(values)))
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def _matches(self, row) -> bool:
        return all(row.get(c) == v for c, v in self._filters) and all(
            row.get(c) in vs for c, vs in self._in_filters
        )

    def execute(self):
        rows = self.store.setdefault(self.name, [])
        if self._op == "select":
            return type("R", (), {"data": [r for r in rows if self._matches(r)]})()
        if self._op == "insert":
            items = self._payload if isinstance(self._payload, list) else [self._payload]
            for item in items:
                item.setdefault("id", f"{self.name}-{len(rows)}")
                item.setdefault("attempts", 0)
                item.setdefault("status", item.get("status", "queued"))
                rows.append(item)
            return type("R", (), {"data": items})()
        if self._op == "update":
            changed = []
            for row in rows:
                if self._matches(row):
                    row.update(self._payload)
                    changed.append(row)
            return type("R", (), {"data": changed})()
        if self._op == "delete":
            self.store[self.name] = [r for r in rows if not self._matches(r)]
            return type("R", (), {"data": []})()
        raise AssertionError("no operation")


class FakeStorageBucket:
    def __init__(self, blobs: dict):
        self.blobs = blobs

    def download(self, path: str) -> bytes:
        if path not in self.blobs:
            raise FileNotFoundError(path)
        return self.blobs[path]


class FakeClient:
    def __init__(self):
        self.store: dict[str, list[dict]] = {}
        self.blobs: dict[str, bytes] = {}

    def table(self, name: str) -> FakeTable:
        return FakeTable(self.store, name)

    @property
    def storage(self):
        outer = self

        class S:
            def from_(self, _bucket):
                return FakeStorageBucket(outer.blobs)

        return S()


def make_pdf(pages: int = 2, arabic: bool = True) -> bytes:
    doc = pymupdf.open()
    for p in range(pages):
        page = doc.new_page()
        y = 80
        for i in range(5):
            if arabic and FONT:
                page.insert_text(
                    (60, y), f"نص تجريبي للصفحة {p + 1} سطر {i + 1}",
                    fontfile=FONT, fontname="ar", fontsize=13,
                )
            else:
                page.insert_text(
                    (60, y),
                    f"Sample English line {i + 1} on page {p + 1} for testing.",
                    fontsize=13,
                )
            y += 34
    raw = doc.tobytes()
    doc.close()
    return raw


@pytest.fixture
def seeded():
    client = FakeClient()
    client.blobs["u1/r1.pdf"] = make_pdf()
    client.store["resources"] = [
        {
            "id": "r1",
            "user_id": "u1",
            "storage_path": "u1/r1.pdf",
            "ingest_status": "pending",
        }
    ]
    client.store["ingest_jobs"] = [
        {"id": "j1", "resource_id": "r1", "status": "queued", "attempts": 0}
    ]
    client.store["resource_chunks"] = []
    return client


def test_claim_job_marks_running(seeded):
    job = worker.claim_job(seeded)
    assert job["id"] == "j1"
    assert seeded.store["ingest_jobs"][0]["status"] == "running"
    assert seeded.store["ingest_jobs"][0]["attempts"] == 1


def test_claim_job_returns_none_when_empty():
    client = FakeClient()
    client.store["ingest_jobs"] = []
    assert worker.claim_job(client) is None


def test_failed_gate_stores_no_chunks(seeded):
    """The core §5.2 guarantee, at the point it actually matters."""
    job = worker.claim_job(seeded)
    worker.process_job(seeded, job)

    resource = seeded.store["resources"][0]
    if resource["ingest_status"] == "failed":
        assert seeded.store["resource_chunks"] == []
        assert resource["ingest_report"]["reasons"]
    else:
        # If a future extractor handles this PDF correctly, chunks must be
        # well-formed rather than absent.
        assert seeded.store["resource_chunks"]
        for chunk in seeded.store["resource_chunks"]:
            assert chunk["page_start"] == chunk["page_end"]


def test_status_and_report_always_recorded(seeded):
    job = worker.claim_job(seeded)
    worker.process_job(seeded, job)
    resource = seeded.store["resources"][0]
    assert resource["ingest_status"] in ("ok", "degraded", "failed")
    assert "status" in resource["ingest_report"]
    assert resource["total_length"] == 2


def test_job_marked_done(seeded):
    job = worker.claim_job(seeded)
    worker.process_job(seeded, job)
    assert seeded.store["ingest_jobs"][0]["status"] == "done"


def test_missing_resource_does_not_crash():
    client = FakeClient()
    client.store["resources"] = []
    client.store["ingest_jobs"] = [
        {"id": "j1", "resource_id": "gone", "status": "running", "attempts": 1}
    ]
    worker.process_job(client, client.store["ingest_jobs"][0])
    assert client.store["ingest_jobs"][0]["status"] == "error"


def test_failure_requeues_until_max_attempts():
    """A transient fault retries; a persistent one gives up and marks the resource."""
    client = FakeClient()
    client.store["resources"] = [
        {"id": "r1", "user_id": "u1", "storage_path": "missing.pdf"}
    ]
    client.store["ingest_jobs"] = [
        {"id": "j1", "resource_id": "r1", "status": "queued", "attempts": 0}
    ]

    for _ in range(worker.MAX_ATTEMPTS):
        client.store["ingest_jobs"][0]["status"] = "queued"
        assert worker.run_once(client) is True

    assert client.store["ingest_jobs"][0]["status"] == "error"
    assert client.store["resources"][0]["ingest_status"] == "failed"


def test_run_once_returns_false_when_idle():
    client = FakeClient()
    client.store["ingest_jobs"] = []
    assert worker.run_once(client) is False


def test_reingest_is_idempotent(seeded):
    """Re-running replaces chunks rather than appending duplicates."""
    job = worker.claim_job(seeded)
    worker.process_job(seeded, job)
    first = len(seeded.store["resource_chunks"])

    seeded.store["ingest_jobs"][0]["status"] = "queued"
    job = worker.claim_job(seeded)
    worker.process_job(seeded, job)
    assert len(seeded.store["resource_chunks"]) == first


def test_english_pdf_is_rejected_by_the_gate():
    """A non-Arabic PDF must not become Arabic practice material."""
    client = FakeClient()
    client.blobs["u1/en.pdf"] = make_pdf(arabic=False)
    client.store["resources"] = [
        {"id": "r1", "user_id": "u1", "storage_path": "u1/en.pdf"}
    ]
    client.store["ingest_jobs"] = [
        {"id": "j1", "resource_id": "r1", "status": "running", "attempts": 1}
    ]
    client.store["resource_chunks"] = []

    worker.process_job(client, client.store["ingest_jobs"][0])
    assert client.store["resources"][0]["ingest_status"] == "failed"
    assert client.store["resource_chunks"] == []


# --- orphan recovery -------------------------------------------------------
# Upload writes the resource and its job separately, so a fault between them
# strands a resource at `pending` with nothing to process it. That happened for
# real: ingest_jobs was missing an INSERT policy, the insert was rejected, and
# the resource sat in the queue forever with no job behind it.


def test_requeue_orphans_recovers_stranded_resource():
    client = FakeClient()
    client.store["resources"] = [
        {"id": "r1", "user_id": "u1", "storage_path": "u1/r1.pdf", "ingest_status": "pending"}
    ]
    client.store["ingest_jobs"] = []

    assert worker.requeue_orphans(client) == 1
    assert len(client.store["ingest_jobs"]) == 1
    assert client.store["ingest_jobs"][0]["resource_id"] == "r1"


def test_requeue_orphans_ignores_resources_with_a_job():
    """Must not double-queue work that is already pending."""
    client = FakeClient()
    client.store["resources"] = [
        {"id": "r1", "user_id": "u1", "storage_path": "u1/r1.pdf", "ingest_status": "pending"}
    ]
    client.store["ingest_jobs"] = [
        {"id": "j1", "resource_id": "r1", "status": "queued", "attempts": 0}
    ]

    assert worker.requeue_orphans(client) == 0
    assert len(client.store["ingest_jobs"]) == 1


def test_requeue_orphans_ignores_finished_resources():
    client = FakeClient()
    client.store["resources"] = [
        {"id": "r1", "user_id": "u1", "storage_path": "u1/r1.pdf", "ingest_status": "ok"},
        {"id": "r2", "user_id": "u1", "storage_path": "u1/r2.pdf", "ingest_status": "failed"},
        {"id": "r3", "user_id": "u1", "storage_path": "u1/r3.pdf", "ingest_status": "degraded"},
    ]
    client.store["ingest_jobs"] = []

    assert worker.requeue_orphans(client) == 0


def test_requeue_orphans_recovers_from_a_dead_worker():
    """A resource left `extracting` by a crashed worker is also stranded."""
    client = FakeClient()
    client.store["resources"] = [
        {"id": "r1", "user_id": "u1", "storage_path": "u1/r1.pdf", "ingest_status": "extracting"}
    ]
    # The job was marked done, or lost, but the resource never moved on.
    client.store["ingest_jobs"] = [
        {"id": "j1", "resource_id": "r1", "status": "done", "attempts": 1}
    ]

    assert worker.requeue_orphans(client) == 1


def test_requeue_orphans_noop_when_clean():
    client = FakeClient()
    client.store["resources"] = []
    client.store["ingest_jobs"] = []
    assert worker.requeue_orphans(client) == 0
