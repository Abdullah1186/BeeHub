import { useEffect, useRef, useState } from "react";
import { api, type Resource } from "../lib/api";

/** Ingest states the user needs to distinguish, with why each matters. */
const STATUS: Record<
  string,
  { label: string; className: string; hint?: string }
> = {
  pending:    { label: "Queued",     className: "bg-stone-100 text-stone-600" },
  extracting: { label: "Processing", className: "bg-blue-50 text-blue-700" },
  ok:         { label: "Ready",      className: "bg-green-50 text-green-700" },
  degraded: {
    label: "Ready, with issues",
    className: "bg-amber-50 text-amber-800",
    hint: "The text extracted imperfectly, so questions may quote it oddly.",
  },
  failed: {
    label: "Unusable",
    className: "bg-red-50 text-red-700",
    hint: "The text could not be extracted, so no practice can be generated.",
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

  // Poll while anything is still being processed, so the UI reflects the
  // worker's progress without the user refreshing.
  useEffect(() => {
    const working = resources.some(
      (r) => r.ingest_status === "pending" || r.ingest_status === "extracting",
    );
    if (!working) return;
    const timer = setInterval(load, 3000);
    return () => clearInterval(timer);
  }, [resources]);

  if (loading) return <p className="text-sm text-stone-500">Loading…</p>;

  return (
    <div className="space-y-6">
      <Upload onDone={load} />

      {error && <p className="text-sm text-red-600">{error}</p>}

      {resources.length === 0 ? (
        <p className="text-sm text-stone-500">
          No material yet. Upload a PDF to start.
        </p>
      ) : (
        <ul className="space-y-3">
          {resources.map((r) => (
            <ResourceRow key={r.id} resource={r} onPractice={onPractice} onChange={load} />
          ))}
        </ul>
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
  const status = STATUS[resource.ingest_status] ?? STATUS.pending;
  const usable = resource.ingest_status === "ok" || resource.ingest_status === "degraded";

  async function savePosition(value: number) {
    setSaving(true);
    try {
      await api.updatePosition(resource.id, value);
      onChange();
    } finally {
      setSaving(false);
    }
  }

  return (
    <li className="rounded-lg border border-stone-200 bg-white p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          {/* The title is usually Arabic; isolate it so surrounding LTR chrome
              cannot reorder its punctuation. */}
          <h3 className="arabic bidi-isolate text-lg truncate">{resource.title}</h3>
          {resource.author && (
            <p className="arabic bidi-isolate text-sm text-stone-500">{resource.author}</p>
          )}
        </div>
        <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs ${status.className}`}>
          {status.label}
        </span>
      </div>

      {status.hint && (
        <p className="mt-2 text-xs text-stone-600">{status.hint}</p>
      )}

      {resource.ingest_report?.reasons?.length > 0 &&
        resource.ingest_status !== "ok" && (
          <ul className="mt-2 space-y-1">
            {resource.ingest_report.reasons.map((reason, i) => (
              <li key={i} className="text-xs text-stone-500">
                • {reason}
              </li>
            ))}
          </ul>
        )}

      {usable && (
        <div className="mt-4 flex items-center gap-3">
          <label className="text-xs text-stone-500">
            Read to page
            <input
              type="number"
              min={0}
              max={resource.total_length ?? undefined}
              value={position}
              onChange={(e) => setPosition(Number(e.target.value))}
              onBlur={() => position !== resource.position_value && savePosition(position)}
              className="ml-2 w-20 rounded border border-stone-300 px-2 py-1 text-sm"
            />
            {resource.total_length && (
              <span className="ml-1 text-stone-400">of {resource.total_length}</span>
            )}
          </label>
          {saving && <span className="text-xs text-stone-400">saving…</span>}

          <button
            onClick={() => onPractice(resource.id)}
            className="ml-auto rounded-lg bg-bee-600 px-3 py-1.5 text-sm font-medium
                       text-white hover:bg-bee-700"
          >
            Practise
          </button>
        </div>
      )}
    </li>
  );
}

function Upload({ onDone }: { onDone: () => void }) {
  const [title, setTitle] = useState("");
  const [position, setPosition] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      await api.uploadPdf(file, title || file.name.replace(/\.pdf$/i, ""), position);
      setTitle("");
      if (fileRef.current) fileRef.current.value = "";
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="rounded-lg border border-dashed border-stone-300 p-4">
      <div className="flex flex-wrap items-end gap-3">
        <input
          ref={fileRef}
          type="file"
          accept="application/pdf"
          required
          className="text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-bee-50
                     file:px-3 file:py-1.5 file:text-sm file:text-bee-700"
        />
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Title (optional)"
          className="rounded-lg border border-stone-300 px-3 py-1.5 text-sm"
        />
        <label className="text-xs text-stone-500">
          Start at page
          <input
            type="number"
            min={0}
            value={position}
            onChange={(e) => setPosition(Number(e.target.value))}
            className="ml-2 w-20 rounded border border-stone-300 px-2 py-1 text-sm"
          />
        </label>
        <button
          type="submit"
          disabled={busy}
          className="rounded-lg bg-stone-800 px-3 py-1.5 text-sm font-medium text-white
                     hover:bg-stone-900 disabled:opacity-50"
        >
          {busy ? "Uploading…" : "Upload"}
        </button>
      </div>
      {/* Questions are only ever drawn from pages at or before this. */}
      <p className="mt-2 text-xs text-stone-500">
        Practice is only generated from pages you have already read.
      </p>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </form>
  );
}
