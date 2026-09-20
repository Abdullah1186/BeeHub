import { useEffect, useMemo, useState } from "react";
import { api, type Overview } from "../lib/api";
import { Badge, Button, Card, EmptyState, Skeleton } from "../ui";
import { BarList, ColumnChart, LineChart, Meter } from "../ui/charts";
import { humanise } from "./Home";

/**
 * Spec §2.5 — the metrics dashboard.
 *
 * One panel with the whole picture, and chips to choose what is in it. A
 * dashboard that shows everything shows nothing: which numbers matter changes
 * week to week, so the selection belongs to the learner.
 *
 * Every panel is a chart or a table, not a lone number. A number answers "how
 * many"; a learner is usually asking "is this going anywhere", which only a
 * shape answers.
 */

const PANELS = [
  { id: "progress", label: "Progress", on: true },
  { id: "activity", label: "Activity", on: true },
  { id: "vocab", label: "Vocabulary", on: true },
  { id: "errors", label: "Errors", on: true },
  { id: "spend", label: "AI spend", on: false },
] as const;

type PanelId = (typeof PANELS)[number]["id"];
const STORAGE_KEY = "beehub.metrics.panels";

export function Metrics() {
  const [data, setData] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);
  const [asTable, setAsTable] = useState(false);
  const [enabled, setEnabled] = useState<Set<PanelId>>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) return new Set(JSON.parse(saved) as PanelId[]);
    } catch {
      /* private windows and blocked site data both throw */
    }
    return new Set(PANELS.filter((p) => p.on).map((p) => p.id));
  });

  useEffect(() => {
    api.overview().then(setData).catch(() => {}).finally(() => setLoading(false));
  }, []);

  function toggle(id: PanelId) {
    const next = new Set(enabled);
    next.has(id) ? next.delete(id) : next.add(id);
    setEnabled(next);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify([...next]));
    } catch {
      /* a preference, not state the app depends on */
    }
  }

  const show = useMemo(() => (id: PanelId) => enabled.has(id), [enabled]);

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-9 w-32" />
        <Skeleton className="h-96 rounded-[var(--radius-card)]" />
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

  const reading = data.estimates.find((e) => e.skill === "reading");
  const writing = data.estimates.find((e) => e.skill === "writing");

  return (
    <div className="space-y-5 fade-up">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="rule-gold text-2xl font-semibold tracking-tight">Metrics</h1>
          <p className="mt-2 text-sm text-[var(--text-muted)]">
            {data.attempts_total} answers graded · {data.vocab.total} words collected
          </p>
        </div>
        {/* The table view is the relief the light palette's contrast warning
            requires, and it is how you read exact values. */}
        <Button variant="secondary" size="sm" onClick={() => setAsTable(!asTable)}>
          {asTable ? "Show charts" : "Show table"}
        </Button>
      </div>

      <div className="flex flex-wrap gap-2">
        {PANELS.map((p) => {
          const on = show(p.id);
          return (
            <button
              key={p.id}
              onClick={() => toggle(p.id)}
              aria-pressed={on}
              className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                on
                  ? "border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--accent-text)]"
                  : "border-[var(--border)] text-[var(--text-subtle)] hover:text-[var(--text)]"
              }`}
            >
              {on ? "✓ " : ""}{p.label}
            </button>
          );
        })}
      </div>

      {asTable ? (
        <TableView data={data} />
      ) : (
        <Card className="divide-y divide-[var(--border-soft)]">
          {enabled.size === 0 && (
            <p className="py-12 text-center text-sm text-[var(--text-subtle)]">
              Everything is switched off. Turn a panel on above.
            </p>
          )}

          {show("progress") && (
            <Panel title="Progress" caption="Understanding and accuracy, per answer.">
              <div className="grid gap-6 sm:grid-cols-[1fr_200px]">
                <LineChart
                  series={[
                    {
                      name: "Understanding",
                      points: data.score_history.map((p, i) => ({
                        x: `#${i + 1} · ${p.date}`,
                        y: p.content,
                      })),
                    },
                    {
                      name: "Accuracy",
                      points: data.score_history.map((p, i) => ({
                        x: `#${i + 1} · ${p.date}`,
                        y: p.language,
                      })),
                    },
                  ]}
                />
                <div className="space-y-4">
                  {[reading, writing].map(
                    (e) =>
                      e && (
                        <div key={e.skill}>
                          <div className="flex items-baseline justify-between">
                            <span className="text-sm capitalize">{e.skill}</span>
                            {e.sufficient ? (
                              <span className="text-2xl font-semibold text-[var(--accent-text)]">
                                {e.cefr_level}
                              </span>
                            ) : (
                              <Badge>building</Badge>
                            )}
                          </div>
                          <div className="mt-1.5 h-2 overflow-hidden rounded-full
                                          bg-[var(--surface-alt)]">
                            <div
                              className="h-full rounded-full transition-[width] duration-700"
                              style={{
                                width: `${Math.min(1, e.n_observations / 15) * 100}%`,
                                background: "var(--series-1)",
                              }}
                            />
                          </div>
                          <p className="mt-1 text-xs text-[var(--text-subtle)]">
                            {e.sufficient
                              ? `${Math.round(e.confidence * 100)}% confident`
                              : `${e.n_observations} of 15 answers needed`}
                          </p>
                        </div>
                      ),
                  )}
                </div>
              </div>
            </Panel>
          )}

          {show("activity") && (
            <Panel title="Activity" caption="Answers per day, last 14 days.">
              <ColumnChart
                data={data.activity.map((a) => ({
                  label: a.date,
                  value: a.count,
                  caption: a.date === data.activity[0].date ? "14 days ago" : "today",
                }))}
              />
              <div className="mt-4 flex gap-6 text-sm">
                <Stat label="This week" value={String(data.attempts_7d)} />
                <Stat label="Streak" value={`${data.streak_days}d`} />
                <Stat
                  label="Mean understanding"
                  value={
                    data.mean_content_score != null
                      ? `${Math.round(data.mean_content_score * 100)}%`
                      : "—"
                  }
                />
              </div>
            </Panel>
          )}

          {show("vocab") && data.vocab.total > 0 && (
            <Panel title="Vocabulary" caption="What you have collected, and whether it is sticking.">
              <div className="grid gap-6 sm:grid-cols-2">
                <div className="space-y-4">
                  <Meter
                    value={data.vocab.known}
                    max={data.vocab.total}
                    label="Known"
                    caption={`${data.vocab.due_now} still in the deck`}
                  />
                  <div>
                    <div className="flex items-baseline justify-between">
                      <span className="text-sm">Retention</span>
                      <span className="text-sm tabular-nums text-[var(--text-muted)]">
                        {data.vocab.retention_rate != null
                          ? `${Math.round(data.vocab.retention_rate * 100)}%`
                          : "—"}
                      </span>
                    </div>
                    <div className="mt-1.5 h-2.5 overflow-hidden rounded-full
                                    bg-[var(--surface-alt)]">
                      <div
                        className="h-full rounded-full transition-[width] duration-700"
                        style={{
                          width: `${(data.vocab.retention_rate ?? 0) * 100}%`,
                          background: "var(--series-1)",
                        }}
                      />
                    </div>
                    <p className="mt-1 text-xs text-[var(--text-subtle)]">
                      {data.vocab.total_reviews
                        ? `recalled on ${data.vocab.total_reviews} reviews`
                        : "no reviews yet"}
                    </p>
                  </div>
                </div>
                <div>
                  <p className="mb-2 text-xs uppercase tracking-wide text-[var(--text-subtle)]">
                    By book
                  </p>
                  <BarList
                    items={data.vocab.by_resource.map((r) => ({
                      label: r.title,
                      value: r.count,
                    }))}
                    format={(v) => `${v} words`}
                  />
                </div>
              </div>
            </Panel>
          )}

          {show("errors") && (
            <Panel title="Errors" caption="Which parts of the grammar are costing you.">
              {data.error_categories.length > 0 ? (
                <div className="grid gap-6 sm:grid-cols-2">
                  <BarList
                    items={data.error_categories.map((c) => ({
                      label: humanise(c.label),
                      value: c.count,
                      hint: `${Math.round(c.share * 100)}% of all errors`,
                    }))}
                  />
                  <div>
                    <p className="mb-2 text-xs uppercase tracking-wide text-[var(--text-subtle)]">
                      Most frequent
                    </p>
                    <div className="space-y-2">
                      {data.weak_spots.map((w) => (
                        <div key={`${w.category}/${w.subcategory}`}
                             className="flex items-center justify-between gap-3 text-sm">
                          <span className="truncate">{humanise(w.subcategory)}</span>
                          <Badge tone={w.severity_mix.blocking ? "bad" : "warn"}>
                            {w.count}×
                          </Badge>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              ) : (
                <p className="text-sm text-[var(--text-muted)]">
                  No grammar errors tagged yet — nothing to report, which is the good case.
                </p>
              )}
            </Panel>
          )}

          {show("spend") && (
            <Panel title="AI spend" caption="§7: you cannot optimise spend you cannot see.">
              <div className="grid gap-6 sm:grid-cols-2">
                <div>
                  <p className="mb-2 text-xs uppercase tracking-wide text-[var(--text-subtle)]">
                    Per day
                  </p>
                  <ColumnChart
                    data={data.spend_by_day.map((d) => ({
                      label: `${d.date}: $${d.cost.toFixed(3)}`,
                      value: d.cost,
                    }))}
                    height={90}
                  />
                </div>
                <div>
                  <p className="mb-2 text-xs uppercase tracking-wide text-[var(--text-subtle)]">
                    By model
                  </p>
                  <BarList
                    items={data.spend_by_model.map((m) => ({
                      label: m.model,
                      value: m.cost,
                    }))}
                    format={(v) => `$${v.toFixed(4)}`}
                  />
                  <p className="mt-3 text-sm">
                    Total{" "}
                    <span className="font-semibold">${data.cost_usd_total.toFixed(4)}</span>
                  </p>
                </div>
              </div>
            </Panel>
          )}
        </Card>
      )}
    </div>
  );
}

function Panel({
  title,
  caption,
  children,
}: {
  title: string;
  caption?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="p-5">
      <div className="mb-4">
        <h2 className="text-sm font-medium">{title}</h2>
        {caption && <p className="text-xs text-[var(--text-subtle)]">{caption}</p>}
      </div>
      {children}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-[var(--text-subtle)]">{label}</p>
      <p className="text-lg font-semibold tabular-nums">{value}</p>
    </div>
  );
}

/** The same numbers, exactly. Charts show shape; this shows values. */
function TableView({ data }: { data: Overview }) {
  const rows: [string, string][] = [
    ["Answers graded", String(data.attempts_total)],
    ["Answers this week", String(data.attempts_7d)],
    ["Streak", `${data.streak_days} days`],
    [
      "Mean understanding",
      data.mean_content_score != null ? `${Math.round(data.mean_content_score * 100)}%` : "—",
    ],
    [
      "Mean accuracy",
      data.mean_language_score != null ? `${Math.round(data.mean_language_score * 100)}%` : "—",
    ],
    ...data.estimates.map(
      (e) =>
        [
          `${humanise(e.skill)} level`,
          e.sufficient
            ? `${e.cefr_level} (${Math.round(e.confidence * 100)}% confident)`
            : `building — ${e.n_observations}/15 answers`,
        ] as [string, string],
    ),
    ["Words collected", String(data.vocab.total)],
    ["Words known", String(data.vocab.known)],
    ["Words in the deck", String(data.vocab.due_now)],
    [
      "Retention",
      data.vocab.retention_rate != null
        ? `${Math.round(data.vocab.retention_rate * 100)}% over ${data.vocab.total_reviews} reviews`
        : "no reviews yet",
    ],
    ...data.error_categories.map(
      (c) => [`Errors · ${humanise(c.label)}`, String(c.count)] as [string, string],
    ),
    ...data.spend_by_model.map(
      (m) => [`Spend · ${m.model}`, `$${m.cost.toFixed(4)}`] as [string, string],
    ),
    ["Spend · total", `$${data.cost_usd_total.toFixed(4)}`],
  ];

  return (
    <Card className="overflow-hidden">
      <table className="w-full text-sm">
        <tbody className="divide-y divide-[var(--border-soft)]">
          {rows.map(([label, value]) => (
            <tr key={label}>
              <td className="px-4 py-2.5 text-[var(--text-muted)]">{label}</td>
              <td className="px-4 py-2.5 text-right font-medium tabular-nums">{value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}
