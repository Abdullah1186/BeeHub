import { useEffect, useState } from "react";
import { api, type Resource } from "../lib/api";
import { Badge, Button, Card, EmptyState, Skeleton } from "../ui";
import { Deck } from "./Deck";
import { Practice } from "./Practice";
import { Vocab } from "./Vocab";
import { VocabTable } from "./VocabTable";
import { WordPicker } from "./WordPicker";

/**
 * Spec §2.3 — the learning tab.
 *
 * Modes run down the left as a rail, with their own sub-tabs on the right.
 * The alternative — a grid of cards you click through to a full-screen view —
 * hid where you were and made switching modes a round trip via Back.
 */

type ModeId = "questions" | "words" | "flashcards" | "essays" | "speaking" | "photo";

interface Mode {
  id: ModeId;
  label: string;
  icon: string;
  blurb: string;
  ready: boolean;
  phase?: string;
  /** Needs a book chosen before it can do anything. */
  needsResource?: boolean;
  tabs?: { id: string; label: string }[];
}

const MODES: Mode[] = [
  {
    id: "questions",
    label: "Questions",
    icon: "?",
    blurb: "Comprehension questions from the pages you have read.",
    ready: true,
    needsResource: true,
  },
  {
    id: "words",
    label: "Collect words",
    icon: "+",
    blurb: "Build your vocabulary from what you are reading.",
    ready: true,
    needsResource: true,
    tabs: [
      { id: "auto", label: "Find for me" },
      { id: "manual", label: "Pick myself" },
    ],
  },
  {
    id: "flashcards",
    label: "Flashcards",
    icon: "▣",
    blurb: "Your deck, and everything in it.",
    ready: true,
    tabs: [
      { id: "deck", label: "Practise" },
      { id: "list", label: "All words" },
    ],
  },
  {
    id: "essays",
    label: "Essays",
    icon: "✎",
    blurb: "Longer prompts, graded against CEFR.",
    ready: false,
    phase: "Phase 2",
  },
  {
    id: "speaking",
    label: "Speaking",
    icon: "◉",
    blurb: "Speak Arabic; the tutor replies in text.",
    ready: false,
    phase: "Phase 3",
  },
  {
    id: "photo",
    label: "Photo answer",
    icon: "▤",
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
  const [mode, setMode] = useState<ModeId>("questions");
  const [tab, setTab] = useState<string>("auto");

  useEffect(() => {
    api
      .listResources()
      .then(setResources)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (focusResource) setSelected(focusResource);
  }, [focusResource]);

  const usable = resources.filter(
    (r) => r.ingest_status === "ok" || r.ingest_status === "degraded",
  );
  const current = MODES.find((m) => m.id === mode)!;
  const selectedResource = usable.find((r) => r.id === selected);

  // Keep the sub-tab valid when the mode changes.
  useEffect(() => {
    if (current.tabs && !current.tabs.some((t) => t.id === tab)) {
      setTab(current.tabs[0].id);
    }
  }, [mode]);

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-9 w-40" />
        <Skeleton className="h-64 rounded-[var(--radius-card)]" />
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

  return (
    <div className="space-y-6 fade-up">
      <h1 className="text-2xl font-semibold tracking-tight">Learning</h1>

      <div className="grid gap-5 sm:grid-cols-[180px_1fr]">
        {/* Mode rail. Horizontal scroll on narrow screens, vertical above. */}
        <nav className="flex gap-2 overflow-x-auto sm:flex-col sm:overflow-visible">
          {MODES.map((m) => {
            const active = mode === m.id;
            return (
              <button
                key={m.id}
                onClick={() => m.ready && setMode(m.id)}
                disabled={!m.ready}
                aria-current={active ? "page" : undefined}
                className={`flex shrink-0 items-center gap-2.5 rounded-lg px-3 py-2.5
                            text-left text-sm transition-colors sm:w-full ${
                              active
                                ? "bg-[var(--accent-soft)] font-medium text-[var(--accent-text)]"
                                : m.ready
                                  ? "text-[var(--text-muted)] hover:bg-[var(--surface-alt)] hover:text-[var(--text)]"
                                  : "cursor-not-allowed text-[var(--text-subtle)] opacity-60"
                            }`}
              >
                <span
                  className={`flex h-6 w-6 shrink-0 items-center justify-center rounded
                              text-xs ${
                                active
                                  ? "bg-[var(--accent)] text-[var(--accent-fg)]"
                                  : "bg-[var(--surface-alt)]"
                              }`}
                >
                  {m.icon}
                </span>
                <span className="whitespace-nowrap">{m.label}</span>
                {!m.ready && <span className="ml-auto hidden text-[10px] sm:inline">soon</span>}
              </button>
            );
          })}
        </nav>

        <div className="min-w-0 space-y-4">
          <div>
            <p className="text-sm text-[var(--text-muted)]">{current.blurb}</p>
          </div>

          {/* Material picker, only for the modes that need one. */}
          {current.needsResource && (
            <Card className="p-4">
              <p className="mb-2 text-xs uppercase tracking-wide text-[var(--text-subtle)]">
                Material
              </p>
              <div className="flex flex-wrap gap-2">
                {usable.map((r) => {
                  const active = selected === r.id;
                  return (
                    <button
                      key={r.id}
                      onClick={() => setSelected(r.id)}
                      aria-pressed={active}
                      className={`rounded-lg border px-3 py-2 text-left transition-all ${
                        active
                          ? "border-[var(--accent)] bg-[var(--accent-soft)] ring-2 ring-[var(--accent)]"
                          : "border-[var(--border)] hover:border-[var(--accent)]/40"
                      }`}
                    >
                      <span className="arabic bidi-isolate text-base" dir="rtl" lang="ar">
                        {r.title}
                      </span>
                      {r.ingest_status === "degraded" && (
                        <Badge tone="warn">issues</Badge>
                      )}
                    </button>
                  );
                })}
              </div>
            </Card>
          )}

          {/* Sub-tabs. */}
          {current.tabs && (
            <div className="flex gap-1 border-b border-[var(--border)]">
              {current.tabs.map((t) => (
                <button
                  key={t.id}
                  onClick={() => setTab(t.id)}
                  className={`-mb-px border-b-2 px-3 py-2 text-sm transition-colors ${
                    tab === t.id
                      ? "border-[var(--accent)] font-medium text-[var(--accent-text)]"
                      : "border-transparent text-[var(--text-muted)] hover:text-[var(--text)]"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>
          )}

          {current.needsResource && !selectedResource ? (
            <EmptyState title="Choose some material above" />
          ) : (
            <Content mode={mode} tab={tab} resourceId={selected} />
          )}
        </div>
      </div>
    </div>
  );
}

function Content({
  mode,
  tab,
  resourceId,
}: {
  mode: ModeId;
  tab: string;
  resourceId: string | null;
}) {
  if (mode === "questions" && resourceId) {
    return <Practice resourceId={resourceId} onBack={() => {}} hideBack />;
  }
  if (mode === "words" && resourceId) {
    return tab === "manual" ? (
      <WordPicker resourceId={resourceId} />
    ) : (
      <Vocab resourceId={resourceId} onBack={() => {}} hideBack />
    );
  }
  if (mode === "flashcards") {
    return tab === "list" ? <VocabTable /> : <Deck onBack={() => {}} hideBack />;
  }
  return null;
}
