import { useEffect, useRef, useState } from "react";
import { api, type Resource } from "../lib/api";
import { Badge, Button, Card, ConfirmButton, EmptyState, Input, Progress, SkeletonCard } from "../ui";

/** Spec §2.2 — the library. Upload, register, position tracking, per-resource
 *  status. Practice itself lives in the Learning tab. */

const STATUS: Record<
  string,
  { label: string; tone: "neutral" | "ok" | "warn" | "bad" | "accent"; hint?: string }
> = {
  pending: { label: "Queued", tone: "neutral" },
  extracting: { label: "Processing", tone: "accent" },
  ok: { label: "Ready", tone: "ok" },
  degraded: {
    label: "Ready · issues",
    tone: "warn",
    hint: "The text extracted imperfectly, so questions may quote it oddly.",
  },
  failed: {
    label: "Unusable",
    tone: "bad",
    hint: "The text could not be extracted, so no practice can be generated from it.",
  },
};

export function Resources({ onPractice }: { onPractice: (id: string) => void }) {
  const [resources, setResources] = useState<Resource[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      setResources(await api.listResources());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  // Poll while the worker is still processing, so its progress appears without
  // a refresh. Stops as soon as nothing is in flight.
  const working = resources.some(
    (r) => r.ingest_status === "pending" || r.ingest_status === "extracting",
  );
  useEffect(() => {
    if (!working) return;
    const timer = setInterval(load, 2500);
    return () => clearInterval(timer);
  }, [working]);

  return (
    <div className="space-y-6 fade-up">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Resources</h1>
        <p className="mt-1 text-sm text-[var(--text-muted)]">
          Everything you practise from. Questions only ever come from pages you have read.
        </p>
      </div>

      <Upload onDone={load} />

      {error && (
        <Card className="border-[var(--bad-text)]/30 bg-[var(--bad-bg)] p-4">
          <p className="text-sm text-[var(--bad-text)]">{error}</p>
        </Card>
      )}

      {loading ? (
        <div className="space-y-3">
          <SkeletonCard />
          <SkeletonCard />
        </div>
      ) : resources.length === 0 ? (
        <EmptyState
          title="Nothing here yet"
          body="Upload an Arabic PDF above. It is parsed, checked, and split into passages you can be questioned on."
        />
      ) : (
        <div className="space-y-3">
          {resources.map((r) => (
            <ResourceRow key={r.id} resource={r} onPractice={onPractice} onChange={load} />
          ))}
        </div>
      )}
    </div>
  );
}

function ResourceRow({
  resource,
  onPractice,
  onChange,
}: {
  resource: Resource;
  onPractice: (id: string) => void;
  onChange: () => void;
}) {
  const [position, setPosition] = useState(resource.position_value ?? 1);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const status = STATUS[resource.ingest_status] ?? STATUS.pending;
  const usable = resource.ingest_status === "ok" || resource.ingest_status === "degraded";
  const inFlight = resource.ingest_status === "pending" || resource.ingest_status === "extracting";

  useEffect(() => {
    setPosition(resource.position_value ?? 1);
  }, [resource.position_value]);

  async function savePosition(value: number) {
    if (value === resource.position_value) return;
    setSaving(true);
    try {
      await api.updatePosition(resource.id, value);
      onChange();
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    setDeleting(true);
    try {
      await api.deleteResource(resource.id);
      onChange();
    } finally {
      setDeleting(false);
    }
  }

  const progress =
    resource.total_length && resource.position_value != null
      ? Math.min(1, resource.position_value / resource.total_length)
      : undefined;

  return (
    <Card className="p-5" interactive={usable}>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h3 className="arabic bidi-isolate truncate text-xl" dir="rtl" lang="ar">
            {resource.title}
          </h3>
          {resource.author && (
            <p className="arabic bidi-isolate truncate text-sm text-[var(--text-muted)]"
               dir="rtl" lang="ar">
              {resource.author}
            </p>
          )}
        </div>
        <Badge tone={status.tone}>{status.label}</Badge>
      </div>

      {/* Worker progress. No percentage is available while queued, so the bar
          is indeterminate rather than fake. */}
      {inFlight && (
        <div className="mt-4">
          <Progress
            label={
              resource.ingest_status === "pending"
                ? "Waiting for the worker…"
                : "Extracting and embedding…"
            }
          />
        </div>
      )}

      {status.hint && <p className="mt-3 text-xs text-[var(--text-muted)]">{status.hint}</p>}

      {resource.ingest_report?.reasons?.length > 0 && resource.ingest_status !== "ok" && (
        <ul className="mt-2 space-y-1">
          {resource.ingest_report.reasons.map((reason, i) => (
            <li key={i} className="text-xs text-[var(--text-subtle)]">· {reason}</li>
          ))}
        </ul>
      )}

      {usable && (
        <>
          {progress !== undefined && (
            <div className="mt-4">
              <Progress value={progress} label="Reading progress" />
            </div>
          )}

          <div className="mt-4 flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-xs text-[var(--text-muted)]">
              Read to page
              <Input
                type="number"
                min={0}
                max={resource.total_length ?? undefined}
                value={position}
                onChange={(e) => setPosition(Number(e.target.value))}
                onBlur={() => savePosition(position)}
                className="w-20 py-1.5"
              />
              {resource.total_length && (
                <span className="text-[var(--text-subtle)]">of {resource.total_length}</span>
              )}
            </label>
            {saving && <span className="text-xs text-[var(--text-subtle)]">saving…</span>}

            <div className="ml-auto flex items-center gap-1">
              <ConfirmButton
                onConfirm={remove}
                busy={deleting}
                question="Delete this? Your answers and vocabulary are kept."
              />
              <Button size="sm" onClick={() => onPractice(resource.id)}>
                Practise
              </Button>
            </div>
          </div>
        </>
      )}

      {/* Unusable or still-queued resources have no Practise row, so delete
          gets its own — otherwise a failed upload could never be removed. */}
      {!usable && (
        <div className="mt-4 flex justify-end">
          <ConfirmButton
            onConfirm={remove}
            busy={deleting}
            question="Delete this?"
          />
        </div>
      )}
    </Card>
  );
}

function Upload({ onDone }: { onDone: () => void }) {
  const [title, setTitle] = useState("");
  const [position, setPosition] = useState(1);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      await api.uploadPdf(file, title || file.name.replace(/\.pdf$/i, ""), position);
      setTitle("");
      setFile(null);
      if (fileRef.current) fileRef.current.value = "";
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const dropped = e.dataTransfer.files?.[0];
          if (dropped?.type === "application/pdf") setFile(dropped);
        }}
        onClick={() => fileRef.current?.click()}
        className={`cursor-pointer rounded-[var(--radius-card)] border-2 border-dashed
                    px-6 py-8 text-center transition-colors ${
                      dragging
                        ? "border-[var(--accent)] bg-[var(--accent-soft)]"
                        : "border-[var(--border)] hover:border-[var(--accent)]/50 hover:bg-[var(--surface-alt)]"
                    }`}
      >
        <input
          ref={fileRef}
          type="file"
          accept="application/pdf"
          hidden
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none"
             className="mx-auto text-[var(--text-subtle)]" aria-hidden="true">
          <path d="M12 16V4m0 0L8 8m4-4 4 4M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"
                stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <p className="mt-2 text-sm font-medium">
          {file ? file.name : "Drop an Arabic PDF, or click to choose"}
        </p>
        <p className="mt-0.5 text-xs text-[var(--text-subtle)]">PDF, up to 50 MB</p>
      </div>

      {file && (
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <label className="flex-1 min-w-48 text-xs text-[var(--text-muted)]">
            Title
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={file.name.replace(/\.pdf$/i, "")}
              className="mt-1"
            />
          </label>
          <label className="text-xs text-[var(--text-muted)]">
            Start at page
            <Input
              type="number"
              min={0}
              value={position}
              onChange={(e) => setPosition(Number(e.target.value))}
              className="mt-1 w-24"
            />
          </label>
          <Button type="submit" loading={busy}>
            {busy ? "Uploading…" : "Upload"}
          </Button>
        </div>
      )}

      <p className="mt-2 text-xs text-[var(--text-subtle)]">
        Practice is only generated from pages at or before your position.
      </p>
      {error && <p className="mt-2 text-sm text-[var(--bad-text)]">{error}</p>}
    </form>
  );
}
