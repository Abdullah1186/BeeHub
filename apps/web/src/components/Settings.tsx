import { useEffect, useState } from "react";
import { api, type UserSettings } from "../lib/api";
import { Badge, Card, Input, Skeleton } from "../ui";

/** Spec §2.6 — target level, daily goal, dialect preference. */

const LEVELS = [
  { id: "A1", label: "A1", blurb: "Words and set phrases" },
  { id: "A2", label: "A2", blurb: "Short simple texts" },
  { id: "B1", label: "B1", blurb: "Straightforward factual prose" },
  { id: "B2", label: "B2", blurb: "Articles and argument" },
  { id: "C1", label: "C1", blurb: "Long, complex, literary" },
  { id: "C2", label: "C2", blurb: "Virtually anything" },
];

export function Settings() {
  const [settings, setSettings] = useState<UserSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saved, setSaved] = useState<string | null>(null);

  useEffect(() => {
    api
      .settings()
      .then(setSettings)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  async function save(patch: Partial<UserSettings>) {
    const next = await api.updateSettings(patch);
    setSettings(next);
    setSaved("Saved");
    setTimeout(() => setSaved(null), 1800);
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-9 w-32" />
        <Skeleton className="h-40 rounded-[var(--radius-card)]" />
      </div>
    );
  }

  return (
    <div className="space-y-8 fade-up">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
          <p className="mt-1 text-sm text-[var(--text-muted)]">
            How practice is pitched to you.
          </p>
        </div>
        {saved && <Badge tone="ok">{saved}</Badge>}
      </div>

      <section className="space-y-3">
        <div>
          <h2 className="text-sm font-medium">Your level</h2>
          {/* This is not cosmetic: the vocabulary extractor uses it to decide
              how much elementary vocabulary to skip, so it directly changes
              what you are taught. */}
          <p className="mt-0.5 text-xs text-[var(--text-muted)]">
            Sets how hard questions are, and how much basic vocabulary is kept when
            collecting words. A lower level keeps more.
          </p>
        </div>

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {LEVELS.map((l) => {
            const active = settings?.target_level === l.id;
            return (
              <button key={l.id} onClick={() => save({ target_level: l.id })}
                      aria-pressed={active}>
                <Card
                  interactive
                  className={`p-3 text-left transition-all ${
                    active
                      ? "border-[var(--accent)] bg-[var(--accent-soft)] ring-2 ring-[var(--accent)]"
                      : ""
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className={`text-lg font-semibold ${
                      active ? "text-[var(--accent-text)]" : ""
                    }`}>
                      {l.label}
                    </span>
                    {active && (
                      <span className="flex h-4 w-4 items-center justify-center rounded-full
                                       bg-[var(--accent)] text-[var(--accent-fg)]">
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="none">
                          <path d="m5 13 4 4L19 7" stroke="currentColor" strokeWidth="3"
                                strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      </span>
                    )}
                  </div>
                  <p className="mt-0.5 text-xs text-[var(--text-muted)]">{l.blurb}</p>
                </Card>
              </button>
            );
          })}
        </div>

        {!settings?.target_level && (
          <p className="text-xs text-[var(--text-subtle)]">
            Not set — practice is currently pitched at A2 by default.
          </p>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-medium">Daily goal</h2>
        <div className="flex items-center gap-3">
          <Input
            type="number"
            min={1}
            max={200}
            defaultValue={settings?.daily_goal ?? 10}
            onBlur={(e) => {
              const v = Number(e.target.value);
              if (v && v !== settings?.daily_goal) save({ daily_goal: v });
            }}
            className="w-28"
          />
          <span className="text-sm text-[var(--text-muted)]">answers a day</span>
        </div>
      </section>

    </div>
  );
}
