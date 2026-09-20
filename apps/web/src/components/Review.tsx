import { useEffect, useState } from "react";
import { api, type QueueStats, type ReviewCard } from "../lib/api";
import { Badge, Button, Card, EmptyState, Skeleton } from "../ui";

/** Spec §2.4 — spaced repetition over things already got wrong.
 *
 *  The four buttons map to FSRS grades. They are phrased as how it FELT rather
 *  than as a score, because a learner can report effort honestly and cannot
 *  report a percentage honestly. */
const GRADES = [
  { label: "Forgot", score: 0.0, tone: "bad" as const, key: "1" },
  { label: "Hard", score: 0.5, tone: "warn" as const, key: "2" },
  { label: "Good", score: 0.8, tone: "neutral" as const, key: "3" },
  { label: "Easy", score: 1.0, tone: "ok" as const, key: "4" },
];

export function Review({ onBack }: { onBack: () => void }) {
  const [cards, setCards] = useState<ReviewCard[]>([]);
  const [stats, setStats] = useState<QueueStats | null>(null);
  const [index, setIndex] = useState(0);
  const [revealed, setRevealed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [grading, setGrading] = useState(false);
  const [lastResult, setLastResult] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    try {
      const [due, s] = await Promise.all([api.reviewDue(), api.reviewStats()]);
      setCards(due);
      setStats(s);
      setIndex(0);
      setRevealed(false);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const card = cards[index];

  async function grade(score: number) {
    if (!card) return;
    setGrading(true);
    try {
      const result = await api.gradeReview(card.id, score);
      setLastResult(
        result.retired
          ? `Retired — you know it.`
          : `Back in ${formatInterval(result.interval_days)}.`,
      );
      if (index + 1 >= cards.length) {
        await load();
      } else {
        setIndex(index + 1);
        setRevealed(false);
      }
    } finally {
      setGrading(false);
    }
  }

  // Number keys grade without reaching for the mouse — the difference between
  // a review session that gets done and one that does not.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!card || grading) return;
      if (!revealed && (e.key === " " || e.key === "Enter")) {
        e.preventDefault();
        setRevealed(true);
        return;
      }
      if (revealed) {
        const g = GRADES.find((x) => x.key === e.key);
        if (g) grade(g.score);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [card, revealed, grading, index, cards.length]);

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-64 rounded-[var(--radius-card)]" />
      </div>
    );
  }

  if (!card) {
    return (
      <div className="space-y-5 fade-up">
        <Button variant="ghost" size="sm" onClick={onBack}>← Back</Button>
        <EmptyState
          title={stats?.total_active ? "Nothing due right now" : "Your queue is empty"}
          body={
            stats?.total_active
              ? `${stats.total_active} cards are scheduled — they will come back when you are about to forget them.`
              : "Mistakes you make while practising are added here automatically, and resurface at widening intervals."
          }
          action={
            <Button
              variant="secondary"
              onClick={async () => {
                await api.enqueueVocab();
                load();
              }}
            >
              Add my vocabulary
            </Button>
          }
        />
        {stats && stats.retired > 0 && (
          <p className="text-center text-xs text-[var(--text-subtle)]">
            {stats.retired} retired — learned well enough to stop.
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-6 fade-up">
      <div className="flex items-center justify-between">
        <Button variant="ghost" size="sm" onClick={onBack}>← Back</Button>
        <div className="flex items-center gap-2">
          <Badge>{card.kind === "vocab" ? "vocabulary" : "grammar"}</Badge>
          <span className="text-sm text-[var(--text-muted)]">
            {index + 1} of {cards.length}
          </span>
        </div>
      </div>

      <button onClick={() => setRevealed(true)} className="w-full text-left" disabled={revealed}>
        <Card className="flex min-h-56 flex-col justify-center p-8" interactive={!revealed}>
          <p className="arabic text-center text-4xl" dir="rtl" lang="ar">
            {card.front}
          </p>

          {revealed ? (
            <div className="mt-6 space-y-4 border-t border-[var(--border-soft)] pt-6 fade-up">
              <p className="text-center text-xl font-medium">{card.back}</p>
              {card.hint && (
                <p className="text-center text-sm text-[var(--text-muted)]">{card.hint}</p>
              )}
              {card.lapses > 0 && (
                <p className="text-center text-xs text-[var(--text-subtle)]">
                  forgotten {card.lapses} {card.lapses === 1 ? "time" : "times"} before
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

      {revealed && (
        <div className="grid grid-cols-4 gap-2 fade-up">
          {GRADES.map((g) => (
            <Button
              key={g.label}
              variant={g.tone === "bad" ? "danger" : g.tone === "ok" ? "primary" : "secondary"}
              onClick={() => grade(g.score)}
              disabled={grading}
              className="flex-col py-3"
            >
              <span>{g.label}</span>
              <span className="text-[10px] opacity-60">{g.key}</span>
            </Button>
          ))}
        </div>
      )}

      {lastResult && (
        <p className="text-center text-sm text-[var(--text-muted)]">{lastResult}</p>
      )}
    </div>
  );
}

function formatInterval(days: number): string {
  if (days < 1) return "less than a day";
  if (days < 2) return "a day";
  if (days < 30) return `${Math.round(days)} days`;
  if (days < 365) return `${Math.round(days / 30)} months`;
  return `${(days / 365).toFixed(1)} years`;
}
