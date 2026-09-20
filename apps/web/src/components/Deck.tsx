import { useEffect, useState } from "react";
import { api, type DeckCard, type DeckState } from "../lib/api";
import { Badge, Button, Card, ConfirmButton, EmptyState, Skeleton } from "../ui";

/**
 * The vocabulary deck (spec §2.3 + §2.4, merged).
 *
 * Vocabulary and review are one deck rather than two modes. You go through
 * cards; the ones you know leave the deck, the ones you do not stay in it.
 *
 * FSRS still schedules underneath. A word you mark known leaves *now* and
 * quietly comes back weeks later when you are about to forget it — the part
 * that actually builds retention, costing no extra interaction. Reset brings
 * the whole deck back.
 */
export function Deck({ onBack }: { onBack: () => void }) {
  const [state, setState] = useState<DeckState | null>(null);
  const [index, setIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [showResting, setShowResting] = useState(false);
  const [done, setDone] = useState(0);

  async function load(includeResting = showResting) {
    setLoading(true);
    try {
      const next = await api.deck(includeResting);
      setState(next);
      setIndex(0);
      setFlipped(false);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const cards: DeckCard[] = state?.cards ?? [];
  const card = cards[index];

  async function mark(known: boolean) {
    if (!card) return;
    setBusy(true);
    try {
      // 0.85 is a clean "Good" for FSRS; 0.2 is "Again". Two buttons rather
      // than four, because a learner can answer "did you know it?" honestly
      // and cannot answer "how hard was it, out of four?" honestly.
      await api.gradeReview(card.id, known ? 0.85 : 0.2);
      setDone(done + 1);

      // A known card leaves the deck at once. An unknown one goes to the back,
      // so it returns in this session rather than in three days.
      const remaining = known
        ? cards.filter((c) => c.id !== card.id)
        : [...cards.filter((c) => c.id !== card.id), card];

      setState({ ...state!, cards: remaining, due_now: state!.due_now - (known ? 1 : 0) });
      setIndex(remaining.length === 0 ? 0 : index % Math.max(remaining.length, 1));
      setFlipped(false);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!card || busy) return;
      if (!flipped && (e.key === " " || e.key === "Enter")) {
        e.preventDefault();
        setFlipped(true);
      } else if (flipped) {
        if (e.key === "ArrowRight" || e.key === "1") mark(true);
        if (e.key === "ArrowLeft" || e.key === "2") mark(false);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [card, flipped, busy, index, cards.length]);

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-72 rounded-[var(--radius-card)]" />
      </div>
    );
  }

  return (
    <div className="space-y-6 fade-up">
      <div className="flex items-center justify-between gap-3">
        <Button variant="ghost" size="sm" onClick={onBack}>← Back</Button>
        <div className="flex items-center gap-2">
          {state && state.resting > 0 && (
            <Badge tone="ok">{state.resting} known</Badge>
          )}
          {cards.length > 0 && (
            <span className="text-sm text-[var(--text-muted)]">
              {index + 1} of {cards.length}
            </span>
          )}
        </div>
      </div>

      {!card ? (
        <DeckEmpty
          state={state}
          done={done}
          onReset={async () => {
            setBusy(true);
            try {
              await api.resetDeck();
              setDone(0);
              await load(false);
            } finally {
              setBusy(false);
            }
          }}
          onAddVocab={async () => {
            setBusy(true);
            try {
              await api.enqueueVocab();
              await load(false);
            } finally {
              setBusy(false);
            }
          }}
          busy={busy}
        />
      ) : (
        <>
          <button
            onClick={() => setFlipped(!flipped)}
            className="w-full text-left"
            aria-label={flipped ? "Show the Arabic" : "Show the meaning"}
          >
            <Card className="flex min-h-72 flex-col justify-center p-8" interactive>
              <div className="flex justify-center">
                <Badge tone={card.kind === "vocab" ? "neutral" : "warn"}>
                  {card.kind === "vocab" ? "word" : "grammar"}
                </Badge>
              </div>

              <p className="arabic mt-6 text-center text-5xl" dir="rtl" lang="ar">
                {card.front}
              </p>

              {flipped ? (
                <div className="mt-6 space-y-3 border-t border-[var(--border-soft)] pt-6 fade-up">
                  <p className="text-center text-2xl font-medium">{card.back}</p>
                  {card.hint && (
                    <p className="arabic bidi-isolate text-center text-base text-[var(--text-muted)]"
                       dir="rtl" lang="ar">
                      {card.hint}
                    </p>
                  )}
                  {card.lapses > 0 && (
                    <p className="text-center text-xs text-[var(--text-subtle)]">
                      missed {card.lapses} {card.lapses === 1 ? "time" : "times"} before
                    </p>
                  )}
                </div>
              ) : (
                <p className="mt-6 text-center text-xs text-[var(--text-subtle)]">
                  Tap, or press space, to reveal
                </p>
              )}
            </Card>
          </button>

          {flipped && (
            <div className="grid grid-cols-2 gap-3 fade-up">
              <Button variant="secondary" onClick={() => mark(false)} disabled={busy}
                      className="flex-col py-4">
                <span>Still learning</span>
                <span className="text-[10px] opacity-60">← stays in the deck</span>
              </Button>
              <Button onClick={() => mark(true)} disabled={busy} className="flex-col py-4">
                <span>I know it</span>
                <span className="text-[10px] opacity-70">→ leaves the deck</span>
              </Button>
            </div>
          )}

          {done > 0 && (
            <p className="text-center text-xs text-[var(--text-subtle)]">
              {done} reviewed this session
            </p>
          )}
        </>
      )}

      {/* Deck settings. Reset is destructive enough to confirm, but it only
          rewinds scheduling — nothing is deleted. */}
      {state && state.total > 0 && (
        <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
          <div className="text-xs text-[var(--text-muted)]">
            {state.total} cards · {state.due_now} in the deck · {state.resting} resting
            {state.retired > 0 && ` · ${state.retired} retired`}
          </div>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                const next = !showResting;
                setShowResting(next);
                load(next);
              }}
            >
              {showResting ? "Hide known" : "Show all"}
            </Button>
            <ConfirmButton
              label="Reset deck"
              confirmLabel="Reset"
              question="Put every card back in the deck?"
              busy={busy}
              onConfirm={async () => {
                setBusy(true);
                try {
                  await api.resetDeck();
                  setDone(0);
                  setShowResting(false);
                  await load(false);
                } finally {
                  setBusy(false);
                }
              }}
            />
          </div>
        </Card>
      )}
    </div>
  );
}

function DeckEmpty({
  state,
  done,
  onReset,
  onAddVocab,
  busy,
}: {
  state: DeckState | null;
  done: number;
  onReset: () => void;
  onAddVocab: () => void;
  busy?: boolean;
}) {
  if (state && state.total === 0) {
    return (
      <EmptyState
        title="Your deck is empty"
        body="Harvest words from a book you are reading, and mistakes you make while practising are added here automatically."
        action={
          <Button onClick={onAddVocab} loading={busy}>
            Add my vocabulary
          </Button>
        }
      />
    );
  }

  return (
    <EmptyState
      title={done > 0 ? "Deck cleared" : "Nothing due right now"}
      body={
        done > 0
          ? `You went through ${done} ${done === 1 ? "card" : "cards"}. The ones you knew will come back when you are about to forget them.`
          : `${state?.resting ?? 0} cards are resting — they return when it is time.`
      }
      action={
        <Button variant="secondary" onClick={onReset} loading={busy}>
          Reset the deck
        </Button>
      }
    />
  );
}
