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

      <Card className="divide-y divide-[var(--border-soft)]">
        {filtered.map((c) => (
          <div key={c.id} className="flex items-start justify-between gap-4 p-4">
            <div className="min-w-0">
              <p className="arabic bidi-isolate text-2xl" dir="rtl" lang="ar">{c.arabic}</p>
              {c.context_sentence && (
                <p className="arabic bidi-isolate mt-1 truncate text-sm text-[var(--text-subtle)]"
                   dir="rtl" lang="ar">
                  {c.context_sentence}
                </p>
              )}
            </div>
            <div className="flex shrink-0 flex-col items-end gap-1">
              <p className="text-sm">{c.translation}</p>
              <div className="flex gap-1">
                {c.pos && <Badge>{c.pos}</Badge>}
                {c.root && (
                  <Badge tone="accent">
                    <span className="arabic bidi-isolate" dir="rtl" lang="ar">{c.root}</span>
                  </Badge>
                )}
              </div>
            </div>
          </div>
        ))}
      </Card>
    </div>
  );
}
