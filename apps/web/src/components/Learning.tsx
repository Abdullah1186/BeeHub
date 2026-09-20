import { useEffect, useState } from "react";
import { api, type Resource } from "../lib/api";
import { Badge, Button, Card, EmptyState, Skeleton } from "../ui";
import { Practice } from "./Practice";
import { Review } from "./Review";
import { Vocab } from "./Vocab";

/** Spec §2.3 — the learning tab. Pick a resource, pick a mode.
 *
 *  Only Questions is built. The other modes are listed rather than hidden, so
 *  the shape of the product is visible and the spec's §2.3 table is legible in
 *  the UI rather than only in the document. */

type Mode = "questions" | "vocab" | "review" | "essays" | "speaking" | "photo";

const MODES: {
  id: Mode;
  label: string;
  blurb: string;
  ready: boolean;
  phase?: string;
  /** Review draws from the whole queue, so it needs no material selected. */
  standalone?: boolean;
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
    blurb: "Flashcards built from the words in your own books.",
    ready: true,
  },
  {
    id: "review",
    label: "Review",
    blurb: "Spaced repetition over what you got wrong. Needs no material.",
    ready: true,
    standalone: true,
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
  const selectedTitle = usable.find((r) => r.id === selected)?.title ?? null;

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
  if (mode === "review") {
    return <Review onBack={() => setMode(null)} />;
  }

  if (selected && mode === "vocab") {
    return (
      <Vocab
        resourceId={selected}
        onBack={() => {
          setSelected(null);
          setMode(null);
        }}
      />
    );
  }

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
        <h2 className="text-sm font-medium text-[var(--text-muted)]">
          1 · Material {selectedTitle && <span className="text-[var(--accent-text)]">✓</span>}
        </h2>
        <div className="grid gap-3 sm:grid-cols-2">
          {usable.map((r) => (
            <button
              key={r.id}
              onClick={() => setSelected(r.id)}
              aria-pressed={selected === r.id}
              className="text-left"
            >
              {/* Selection needs to survive a glance: a ring, a filled tick and
                  a word, not a background tint alone. Colour by itself is also
                  the one cue some users cannot see. */}
              <Card
                interactive
                className={`relative p-4 transition-all ${
                  selected === r.id
                    ? "border-[var(--accent)] bg-[var(--accent-soft)] ring-2 ring-[var(--accent)] ring-offset-2 ring-offset-[var(--bg)]"
                    : "hover:border-[var(--accent)]/40"
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <h3 className="arabic bidi-isolate truncate text-lg" dir="rtl" lang="ar">
                    {r.title}
                  </h3>
                  <div className="flex shrink-0 items-center gap-2">
                    {r.ingest_status === "degraded" && <Badge tone="warn">issues</Badge>}
                    {selected === r.id ? (
                      <span
                        className="flex h-5 w-5 items-center justify-center rounded-full
                                   bg-[var(--accent)] text-[var(--accent-fg)]"
                        aria-hidden="true"
                      >
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                          <path d="m5 13 4 4L19 7" stroke="currentColor" strokeWidth="3"
                                strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      </span>
                    ) : (
                      <span className="h-5 w-5 rounded-full border-2 border-[var(--border)]"
                            aria-hidden="true" />
                    )}
                  </div>
                </div>
                {r.total_length && (
                  <p className="mt-1 text-xs text-[var(--text-muted)]">
                    page {r.position_value ?? 0} of {r.total_length}
                  </p>
                )}
                {selected === r.id && (
                  <p className="mt-2 text-xs font-medium text-[var(--accent-text)]">Selected</p>
                )}
              </Card>
            </button>
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-medium text-[var(--text-muted)]">
          2 · Mode
          {selectedTitle && (
            <>
              {" · "}
              <span className="arabic bidi-isolate text-[var(--accent-text)]" dir="rtl" lang="ar">
                {selectedTitle}
              </span>
            </>
          )}
        </h2>
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
                  disabled={!m.standalone && !selected}
                  onClick={() => setMode(m.id)}
                >
                  {m.standalone || selected ? "Start" : "Pick material first"}
                </Button>
              )}
            </Card>
          ))}
        </div>
      </section>
    </div>
  );
}
