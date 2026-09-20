import { useEffect, useMemo, useState } from "react";
import { api, type VocabCard } from "../lib/api";
import { Badge, Card, EmptyState, Input, Skeleton } from "../ui";

/** Every word you have, as a table. The deck is for practising; this is for
 *  seeing what you have collected and finding a specific word. */
export function VocabTable() {
  const [cards, setCards] = useState<VocabCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");

  useEffect(() => {
    api
      .vocabDeck(undefined)
      .then(setCards)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return cards;
    return cards.filter(
      (c) =>
        c.arabic.includes(query.trim()) ||
        c.translation.toLowerCase().includes(q) ||
        (c.root ?? "").includes(query.trim()),
    );
  }, [cards, query]);

  if (loading) {
    return (
      <div className="space-y-2">
        {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-14 rounded-lg" />)}
      </div>
    );
  }

  if (cards.length === 0) {
    return (
      <EmptyState
        title="No words yet"
        body="Collect words from a passage, or add them by hand while reading."
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search Arabic, meaning or root…"
        />
        <span className="shrink-0 text-sm text-[var(--text-muted)]">
          {filtered.length} of {cards.length}
        </span>
      </div>

      {/* A real grid, not a flex row per card.
          Flex sizes each row to its own content, so a long Arabic word pushes
          its meaning left and nothing lines up down the page. Fixed columns
          put every word, meaning and root in the same place. */}
      <Card className="overflow-hidden">
        <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] gap-4
                        border-b border-[var(--border)] bg-[var(--surface-alt)]
                        px-4 py-2 text-[11px] uppercase tracking-wide
                        text-[var(--text-subtle)]">
          <span className="text-right">Word</span>
          <span>Meaning</span>
          <span className="text-right">Root</span>
        </div>

        <div className="divide-y divide-[var(--border-soft)]">
          {filtered.map((c) => (
            <div
              key={c.id}
              className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] items-center
                         gap-4 px-4 py-3"
            >
              <div className="min-w-0">
                <p className="arabic bidi-isolate truncate text-2xl" dir="rtl" lang="ar">
                  {c.arabic}
                </p>
                {c.context_sentence && (
                  <p className="arabic bidi-isolate truncate text-xs text-[var(--text-subtle)]"
                     dir="rtl" lang="ar">
                    {c.context_sentence}
                  </p>
                )}
              </div>

              <div className="min-w-0">
                <p className="truncate text-sm">{c.translation}</p>
                {c.pos && (
                  <p className="text-xs text-[var(--text-subtle)]">{c.pos}</p>
                )}
              </div>

              <div className="justify-self-end">
                {c.root ? (
                  <Badge tone="accent">
                    <span className="arabic bidi-isolate" dir="rtl" lang="ar">{c.root}</span>
                  </Badge>
                ) : (
                  <span className="text-xs text-[var(--text-subtle)]">—</span>
                )}
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
