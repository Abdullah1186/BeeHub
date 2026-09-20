import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import { api } from "../lib/api";
import { Button, Skeleton } from "../ui";

// Served from our own bundle rather than a CDN: the worker must match the
// installed pdfjs exactly, and a CDN pinned elsewhere fails at render time.
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

/** `file` must be referentially stable.
 *
 *  react-pdf reloads the document whenever this prop changes identity, so a
 *  fresh object or string on each render loops forever. Memoising on the URL
 *  string is what keeps it to one load. */
function useFile(url: string | null) {
  return useMemo(() => (url ? { url } : null), [url]);
}

export function PdfCover({
  resourceId,
  onOpen,
}: {
  resourceId: string;
  onOpen: () => void;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const file = useFile(url);

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
      {file ? (
        <Document
          file={file}
          loading={<Skeleton className="h-full w-full" />}
          error={<div className="h-full w-full bg-[var(--surface-alt)]" />}
          onLoadError={() => setFailed(true)}
        >
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

/**
 * Page-at-a-time reader.
 *
 * The first version rendered every page at once. On an 18-page document that
 * spawns eighteen concurrent canvas renders through one worker, which stalls
 * the tab and can take it down outright — and a real book would be far worse.
 * One page at a time keeps it to a single render regardless of length.
 */
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
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [width, setWidth] = useState(() => Math.min(680, window.innerWidth - 48));
  const containerRef = useRef<HTMLDivElement>(null);
  const file = useFile(url);

  useEffect(() => {
    let cancelled = false;
    api
      .resourceFileUrl(resourceId)
      .then(({ url }) => !cancelled && setUrl(url))
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
  }, [resourceId]);

  // Width is state rather than an inline expression, so a resize does not
  // re-render the page on every frame.
  useEffect(() => {
    const onResize = () => setWidth(Math.min(680, window.innerWidth - 48));
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const go = useCallback(
    (delta: number) => {
      setPage((p) => Math.min(Math.max(1, p + delta), Math.max(pages, 1)));
      containerRef.current?.scrollTo({ top: 0 });
    },
    [pages],
  );

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight" || e.key === "PageDown") go(1);
      if (e.key === "ArrowLeft" || e.key === "PageUp") go(-1);
    }
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [onClose, go]);

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-[var(--bg)]">
      <header className="flex items-center justify-between gap-4 border-b
                         border-[var(--border)] bg-[var(--surface)] px-4 py-3">
        <h2 className="arabic bidi-isolate min-w-0 truncate text-lg" dir="rtl" lang="ar">
          {title}
        </h2>
        <div className="flex shrink-0 items-center gap-2">
          {url && (
            <a href={url} target="_blank" rel="noopener noreferrer">
              <Button variant="secondary" size="sm">New tab</Button>
            </a>
          )}
          <Button variant="ghost" size="sm" onClick={onClose}>Close</Button>
        </div>
      </header>

      <div ref={containerRef} className="flex-1 overflow-y-auto px-4 py-6">
        {error ? (
          <div className="mx-auto max-w-md text-center">
            <p className="text-sm text-[var(--bad-text)]">{error}</p>
            {url && (
              <a href={url} target="_blank" rel="noopener noreferrer">
                <Button variant="secondary" size="sm" className="mt-3">
                  Open it in a new tab instead
                </Button>
              </a>
            )}
          </div>
        ) : file ? (
          <Document
            file={file}
            onLoadSuccess={({ numPages }) => setPages(numPages)}
            onLoadError={(e) => setError(e.message)}
            loading={<Skeleton className="mx-auto h-[70vh] w-full max-w-2xl" />}
            className="flex justify-center"
          >
            <div className="overflow-hidden rounded-md border border-[var(--border)]
                            shadow-[var(--shadow-sm)]">
              <Page
                pageNumber={page}
                width={width}
                loading={<Skeleton style={{ width, height: width * 1.4 }} />}
                renderAnnotationLayer={false}
              />
            </div>
          </Document>
        ) : (
          <Skeleton className="mx-auto h-[70vh] w-full max-w-2xl" />
        )}
      </div>

      {pages > 0 && (
        <footer className="flex items-center justify-center gap-4 border-t
                           border-[var(--border)] bg-[var(--surface)] px-4 py-3">
          <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => go(-1)}>
            ←
          </Button>
          <span className="text-sm text-[var(--text-muted)]">
            {page} of {pages}
          </span>
          <Button
            variant="secondary"
            size="sm"
            disabled={page >= pages}
            onClick={() => go(1)}
          >
            →
          </Button>
        </footer>
      )}
    </div>
  );
}
