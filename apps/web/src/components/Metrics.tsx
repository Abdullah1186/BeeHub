import { useEffect, useState } from "react";
import { api, type Overview } from "../lib/api";
import { Badge, Card, EmptyState, Skeleton } from "../ui";
import { humanise } from "./Home";

/** Spec §2.5 — CEFR per skill with honest confidence, error breakdown,
 *  activity, and cost. Everything here is computed from recorded rows; no
 *  model call happens to render this page. */
export function Metrics() {
  const [data, setData] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .overview()
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-9 w-32" />
        <div className="grid gap-4 sm:grid-cols-2">
          <Skeleton className="h-32 rounded-[var(--radius-card)]" />
          <Skeleton className="h-32 rounded-[var(--radius-card)]" />
        </div>
      </div>
    );
  }

  if (!data || data.attempts_total === 0) {
    return (
      <EmptyState
        title="No data yet"
        body="Answer a few questions and your levels, weak spots and activity appear here."
      />
    );
  }

  const peak = Math.max(...data.activity.map((a) => a.count), 1);

  return (
    <div className="space-y-8 fade-up">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Metrics</h1>
        <p className="mt-1 text-sm text-[var(--text-muted)]">
          {data.attempts_total} answers graded so far.
        </p>
      </div>

      {/* Per-skill CEFR. Reading and writing are measured separately because
          they genuinely diverge — a learner can understand far more than they
          can produce (§2.5). */}
      <section className="space-y-3">
        <h2 className="text-sm font-medium text-[var(--text-muted)]">Level by skill</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          {data.estimates.map((e) => (
            <Card key={e.skill} className="p-5">
              <div className="flex items-start justify-between">
                <p className="text-sm font-medium capitalize">{e.skill}</p>
                {e.sufficient ? (
                  <Badge tone="accent">{Math.round(e.confidence * 100)}% confident</Badge>
                ) : (
                  <Badge>building</Badge>
                )}
              </div>

              {e.sufficient ? (
                <p className="mt-2 text-4xl font-semibold text-[var(--accent-text)]">
                  {e.cefr_level}
                </p>
              ) : (
                <>
                  <p className="mt-2 text-lg text-[var(--text-muted)]">Not enough data</p>
                  <p className="mt-1 text-xs text-[var(--text-subtle)]">
                    {e.n_observations} of 15 graded answers
                  </p>
                </>
              )}

              <p className="mt-3 text-xs text-[var(--text-subtle)]">
                {e.skill === "reading"
                  ? "From how well you answer, judged against the source."
                  : "From the grammatical accuracy of your Arabic."}
              </p>
            </Card>
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-medium text-[var(--text-muted)]">Activity</h2>
        <Card className="p-5">
          <div className="flex h-24 items-end gap-1">
            {data.activity.map((d) => (
              <div key={d.date} className="group relative flex-1" title={`${d.date}: ${d.count}`}>
                <div
                  className="w-full rounded-sm bg-[var(--accent)] transition-all"
                  style={{
                    height: `${Math.max(3, (d.count / peak) * 96)}px`,
                    opacity: d.count === 0 ? 0.15 : 0.45 + (d.count / peak) * 0.55,
                  }}
                />
              </div>
            ))}
          </div>
          <div className="mt-2 flex justify-between text-xs text-[var(--text-subtle)]">
            <span>14 days ago</span>
            <span>today</span>
          </div>
        </Card>
      </section>

      {data.weak_spots.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-medium text-[var(--text-muted)]">
            Where the errors are
          </h2>
          <Card className="divide-y divide-[var(--border-soft)]">
            {data.weak_spots.map((w) => (
              <div key={`${w.category}/${w.subcategory}`} className="p-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium">{humanise(w.subcategory)}</p>
                    <p className="text-xs text-[var(--text-subtle)]">{humanise(w.category)}</p>
                  </div>
                  <span className="text-lg font-semibold text-[var(--text-muted)]">{w.count}</span>
                </div>
                <div className="mt-2 flex gap-1.5">
                  {Object.entries(w.severity_mix).map(([sev, n]) => (
                    <Badge
                      key={sev}
                      tone={sev === "blocking" ? "bad" : sev === "moderate" ? "warn" : "neutral"}
                    >
                      {n} {sev}
                    </Badge>
                  ))}
                </div>
              </div>
            ))}
          </Card>
        </section>
      )}

      {/* Spec §2.5: total known, retention rate, words due for review. */}
      {data.vocab.total > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-medium text-[var(--text-muted)]">Vocabulary</h2>
          <div className="grid gap-4 sm:grid-cols-4">
            <Small label="Collected" value={String(data.vocab.total)} />
            <Small label="Known" value={String(data.vocab.known)} />
            <Small label="In the deck" value={String(data.vocab.due_now)} />
            <Small
              label="Retention"
              value={
                data.vocab.retention_rate != null
                  ? `${Math.round(data.vocab.retention_rate * 100)}%`
                  : "—"
              }
            />
          </div>

          {data.vocab.total_reviews > 0 && (
            <p className="text-xs text-[var(--text-subtle)]">
              Retention is successful reviews as a share of all{" "}
              {data.vocab.total_reviews} — whether the words are sticking, not how
              many were collected.
            </p>
          )}

          {data.vocab.by_resource.length > 0 && (
            <Card className="divide-y divide-[var(--border-soft)]">
              {data.vocab.by_resource.map((r) => (
                <div key={r.title} className="flex items-center justify-between p-4">
                  <p className="arabic bidi-isolate truncate text-base" dir="rtl" lang="ar">
                    {r.title}
                  </p>
                  <Badge>{r.count} words</Badge>
                </div>
              ))}
            </Card>
          )}
        </section>
      )}

      <section className="space-y-3">
        <h2 className="text-sm font-medium text-[var(--text-muted)]">Totals</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <Small
            label="Mean understanding"
            value={
              data.mean_content_score != null
                ? `${Math.round(data.mean_content_score * 100)}%`
                : "—"
            }
          />
          {/* §7: you cannot optimise spend you cannot see. */}
          <Small label="AI spend" value={`$${data.cost_usd_total.toFixed(2)}`} />
        </div>
      </section>
    </div>
  );
}

function Small({ label, value }: { label: string; value: string }) {
  return (
    <Card className="p-4">
      <p className="text-xs uppercase tracking-wide text-[var(--text-subtle)]">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
    </Card>
  );
}
