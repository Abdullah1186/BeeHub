"""The ingestion pipeline: extract -> assess -> chunk.

One entry point so the quality gate can never be bypassed. A caller that wants
chunks gets them only when the document passed; a failed document yields a
report and no chunks at all, which is what keeps unreadable text from silently
becoming practice material (spec §5.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.ingest.chunker import Chunk, chunk_pages
from app.ingest.extract import extract_pdf
from app.ingest.quality import IngestStatus, QualityReport, assess_document, assess_page


@dataclass
class IngestResult:
    status: IngestStatus
    report: QualityReport
    chunks: list[Chunk]
    page_count: int

    @property
    def can_generate_practice(self) -> bool:
        """`degraded` still generates — the user was warned and chose to keep it."""
        return self.status in (IngestStatus.OK, IngestStatus.DEGRADED)


def ingest_pdf(path: str | Path, *, max_pages_sampled: int = 40) -> IngestResult:
    """Run a PDF through the full pipeline.

    Quality is assessed on an evenly-spaced sample rather than every page, so a
    600-page book does not pay a full scan to learn it is a scan.
    """
    document = extract_pdf(path)

    numbers = sorted(document.pages)
    if len(numbers) > max_pages_sampled:
        step = len(numbers) / max_pages_sampled
        sampled = [numbers[int(i * step)] for i in range(max_pages_sampled)]
    else:
        sampled = numbers

    report = assess_document(
        [assess_page(number, document.pages[number]) for number in sampled]
    )

    chunks: list[Chunk] = []
    if report.status is not IngestStatus.FAILED:
        chunks = chunk_pages(document.pages)
        # An empty chunk list after a passing verdict means the gate's sample
        # missed that the body is empty. Fail rather than ingest nothing.
        if not chunks:
            report.status = IngestStatus.FAILED
            report.reasons.append("no chunks could be produced from the extracted text")

    return IngestResult(
        status=report.status,
        report=report,
        chunks=chunks,
        page_count=document.page_count,
    )
