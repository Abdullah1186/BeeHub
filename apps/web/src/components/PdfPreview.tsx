import { useEffect, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import { api } from "../lib/api";
import { Button, Skeleton } from "../ui";

// Served from our own origin rather than a CDN: the worker must match the
// installed pdfjs version exactly, and a CDN pinned to the wrong one fails at
// render time with an unhelpful error.
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

/** A cover thumbnail that expands into a scrollable preview.
 *
 *  The signed URL is fetched lazily — one per resource on a list of ten would
 *  be ten round trips for covers most people will not look at. */
export function PdfCover({
  resourceId,
  onOpen,
}: {
  resourceId: string;
  onOpen: () => void;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .resourceFileUrl(resourceId)
      .then(({ url }) => !cancelled && setUrl(url))
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [resourceId]);

  if (failed) return null;

  return (
    <button
      onClick={onOpen}
      className="group relative shrink-0 overflow-hidden rounded-md border
                 border-[var(--border)] bg-[var(--surface-alt)]
                 transition-shadow hover:shadow-[var(--shadow-md)]"
      style={{ width: 72, height: 96 }}
      aria-label="Open the PDF"
    >
      {url ? (
        <Document file={url} loading={<Skeleton className="h-full w-full" />} error={null}>
          <Page
            pageNumber={1}
            width={72}
            renderTextLayer={false}
            renderAnnotationLayer={false}
          />
        </Document>
      ) : (
        <Skeleton className="h-full w-full" />
      )}
      <span className="absolute inset-0 flex items-center justify-center bg-black/50
                       text-[10px] font-medium text-white opacity-0 transition-opacity
                       group-hover:opacity-100">
        Open
      </span>
    </button>
  );
}

/** Full-screen scrollable reader. */
export function PdfViewer({
  resourceId,
  title,
  onClose,
}: {
  resourceId: string;
  title: string;
  onClose: () => void;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [pages, setPages] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .resourceFileUrl(resourceId)
      .then(({ url }) => setUrl(url))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [resourceId]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    // The page behind must not scroll while the reader is open.
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-[var(--bg)]">
      <header className="flex items-center justify-between gap-4 border-b
                         border-[var(--border)] bg-[var(--surface)] px-4 py-3">
        <h2 className="arabic bidi-isolate truncate text-lg" dir="rtl" lang="ar">
          {title}
        </h2>
        <div className="flex shrink-0 items-center gap-2">
          {pages > 0 && (
            <span className="text-xs text-[var(--text-muted)]">{pages} pages</span>
          )}
          {url && (
            <a href={url} target="_blank" rel="noopener noreferrer">
              <Button variant="secondary" size="sm">Open in new tab</Button>
            </a>
          )}
          <Button variant="ghost" size="sm" onClick={onClose}>Close</Button>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-6">
        {error ? (
          <p className="text-center text-sm text-[var(--bad-text)]">{error}</p>
        ) : url ? (
          <Document
            file={url}
            onLoadSuccess={({ numPages }) => setPages(numPages)}
            onLoadError={(e) => setError(e.message)}
            loading={<Skeleton className="mx-auto h-[70vh] w-full max-w-2xl" />}
            className="mx-auto flex max-w-2xl flex-col items-center gap-4"
          >
            {Array.from({ length: pages }, (_, i) => (
              <div
                key={i}
                className="overflow-hidden rounded-md border border-[var(--border)]
                           shadow-[var(--shadow-sm)]"
              >
                <Page pageNumber={i + 1} width={Math.min(680, window.innerWidth - 48)} />
              </div>
            ))}
          </Document>
        ) : (
          <Skeleton className="mx-auto h-[70vh] w-full max-w-2xl" />
        )}
      </div>
    </div>
  );
}
