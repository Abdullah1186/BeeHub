import { useEffect, useState } from "react";
import { api, type Resource } from "../lib/api";
import { Badge, Button, Card, EmptyState, Skeleton } from "../ui";
import { Practice } from "./Practice";

/** Spec §2.3 — the learning tab. Pick a resource, pick a mode.
 *
 *  Only Questions is built. The other modes are listed rather than hidden, so
 *  the shape of the product is visible and the spec's §2.3 table is legible in
 *  the UI rather than only in the document. */

type Mode = "questions" | "vocab" | "essays" | "speaking" | "photo";

const MODES: {
  id: Mode;
  label: string;
  blurb: string;
  ready: boolean;
  phase?: string;
}[] = [
  {
    id: "questions",
    label: "Questions",
    blurb: "Comprehension questions written from the pages you have read.",
    ready: true,
  },
  {
    id: "vocab",
    label: "Vocabulary",
    blurb: "Flashcards and a matching game, built from your own books.",
    ready: false,
    phase: "Phase 2",
  },
  {
    id: "essays",
    label: "Essays",
    blurb: "Longer prompts on your book's themes, graded against CEFR.",
    ready: false,
    phase: "Phase 2",
  },
  {
    id: "speaking",
    label: "Speaking",
    blurb: "Speak Arabic; the tutor replies in text.",
    ready: false,
    phase: "Phase 3",
  },
  {
    id: "photo",
    label: "Upload an answer",
    blurb: "Write on paper, photograph it, get it graded.",
    ready: false,
    phase: "Phase 3",
  },
];

export function Learning({
  focusResource,
  onBrowse,
}: {
  focusResource: string | null;
  onBrowse: () => void;
}) {
  const [resources, setResources] = useState<Resource[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(focusResource);
  const [mode, setMode] = useState<Mode | null>(focusResource ? "questions" : null);

  useEffect(() => {
    api
      .listResources()
      .then(setResources)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (focusResource) {
      setSelected(focusResource);
      setMode("questions");
    }
  }, [focusResource]);

  const usable = resources.filter(
    (r) => r.ingest_status === "ok" || r.ingest_status === "degraded",
  );

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-9 w-40" />
        <Skeleton className="h-32 rounded-[var(--radius-card)]" />
      </div>
    );
  }

  if (usable.length === 0) {
    return (
      <EmptyState
        title="Nothing to practise yet"
        body="Add a resource first — every question is grounded in material you have actually read."
        action={<Button onClick={onBrowse}>Go to Resources</Button>}
      />
    );
  }

  // Practising.
  if (selected && mode === "questions") {
    return (
      <Practice
        resourceId={selected}
        onBack={() => {
          setSelected(null);
          setMode(null);
        }}
      />
    );
  }

  return (
    <div className="space-y-8 fade-up">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Learning</h1>
        <p className="mt-1 text-sm text-[var(--text-muted)]">
          Choose what to practise from, then how.
        </p>
      </div>

      <section className="space-y-3">
        <h2 className="text-sm font-medium text-[var(--text-muted)]">Material</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          {usable.map((r) => (
            <button key={r.id} onClick={() => setSelected(r.id)} className="text-left">
              <Card
                interactive
                className={`p-4 transition-colors ${
                  selected === r.id ? "border-[var(--accent)] bg-[var(--accent-soft)]" : ""
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <h3 className="arabic bidi-isolate truncate text-lg" dir="rtl" lang="ar">
                    {r.title}
                  </h3>
                  {r.ingest_status === "degraded" && <Badge tone="warn">issues</Badge>}
                </div>
                {r.total_length && (
                  <p className="mt-1 text-xs text-[var(--text-muted)]">
                    page {r.position_value ?? 0} of {r.total_length}
                  </p>
                )}
              </Card>
            </button>
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-medium text-[var(--text-muted)]">Mode</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          {MODES.map((m) => (
            <Card
              key={m.id}
              interactive={m.ready}
              className={`p-4 ${m.ready ? "" : "opacity-60"}`}
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-medium">{m.label}</p>
                  <p className="mt-0.5 text-sm text-[var(--text-muted)]">{m.blurb}</p>
                </div>
                {!m.ready && <Badge>{m.phase}</Badge>}
              </div>
              {m.ready && (
                <Button
                  size="sm"
                  className="mt-4 w-full"
                  disabled={!selected}
                  onClick={() => setMode(m.id)}
                >
                  {selected ? "Start" : "Pick material first"}
                </Button>
              )}
            </Card>
          ))}
        </div>
      </section>
    </div>
  );
}
