import { useEffect, useState } from "react";
import { api, type Overview, type Resource } from "../lib/api";
import { Badge, Button, Card, EmptyState, Skeleton } from "../ui";

/** Spec §2.1 — today's tasks, streak, CEFR estimate, weak spots, quick start. */
export function Home({
  onLearn,
  onBrowse,
}: {
  onLearn: (resourceId: string | null) => void;
  onBrowse: () => void;
}) {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [resources, setResources] = useState<Resource[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([api.overview(), api.listResources()])
      .then(([o, r]) => {
        setOverview(o);
        setResources(r);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-9 w-56" />
        <div className="grid gap-4 sm:grid-cols-3">
          {[0, 1, 2].map((i) => <Skeleton key={i} className="h-28 rounded-[var(--radius-card)]" />)}
        </div>
        <Skeleton className="h-40 rounded-[var(--radius-card)]" />
      </div>
    );
  }

  const ready = resources.filter(
    (r) => r.ingest_status === "ok" || r.ingest_status === "degraded",
  );
  const reading = overview?.estimates.find((e) => e.skill === "reading");

  return (
    <div className="space-y-8 fade-up">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          {greeting()}
        </h1>
        <p className="mt-1 text-sm text-[var(--text-muted)]">
          {ready.length > 0
            ? "Pick up where you left off."
            : "Add something to read, and practice follows from it."}
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <Stat
          label="Streak"
          value={overview?.streak_days ?? 0}
          suffix={overview?.streak_days === 1 ? "day" : "days"}
        />
        <Stat label="This week" value={overview?.attempts_7d ?? 0} suffix="answers" />
        <Card className="p-5">
          <p className="text-xs uppercase tracking-wide text-[var(--text-subtle)]">Reading</p>
          {reading?.sufficient ? (
            <>
              <p className="mt-1 text-3xl font-semibold text-[var(--accent-text)]">
                {reading.cefr_level}
              </p>
              <p className="text-xs text-[var(--text-muted)]">
                {Math.round(reading.confidence * 100)}% confidence
              </p>
            </>
          ) : (
            <>
              <p className="mt-1 text-lg font-medium text-[var(--text-muted)]">Not yet</p>
              <p className="text-xs text-[var(--text-subtle)]">
                {reading?.n_observations ?? 0} of 15 answers needed
              </p>
            </>
          )}
        </Card>
      </div>

      {/* Quick start */}
      {ready.length === 0 ? (
        <EmptyState
          title="No material yet"
          body="Upload a PDF or register a book, and questions are generated from what you have actually read."
          action={<Button onClick={onBrowse}>Add material</Button>}
        />
      ) : (
        <section className="space-y-3">
          <h2 className="text-sm font-medium text-[var(--text-muted)]">Continue</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            {ready.slice(0, 4).map((r) => (
              <Card key={r.id} interactive className="p-4">
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
                <Button size="sm" className="mt-4 w-full" onClick={() => onLearn(r.id)}>
                  Practise
                </Button>
              </Card>
            ))}
          </div>
        </section>
      )}

      {overview && overview.weak_spots.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-medium text-[var(--text-muted)]">Weak spots</h2>
          <Card className="divide-y divide-[var(--border-soft)]">
            {overview.weak_spots.map((w) => (
              <div key={`${w.category}/${w.subcategory}`} className="flex items-center justify-between p-4">
                <div>
                  <p className="text-sm font-medium">{humanise(w.subcategory)}</p>
                  <p className="text-xs text-[var(--text-subtle)]">{humanise(w.category)}</p>
                </div>
                <Badge tone={w.severity_mix.blocking ? "bad" : "warn"}>
                  {w.count} {w.count === 1 ? "time" : "times"}
                </Badge>
              </div>
            ))}
          </Card>
        </section>
      )}
    </div>
  );
}

function Stat({ label, value, suffix }: { label: string; value: number; suffix: string }) {
  return (
    <Card className="p-5">
      <p className="text-xs uppercase tracking-wide text-[var(--text-subtle)]">{label}</p>
      <p className="mt-1 text-3xl font-semibold">{value}</p>
      <p className="text-xs text-[var(--text-muted)]">{suffix}</p>
    </Card>
  );
}

export function humanise(s: string) {
  return s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

function greeting() {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}
