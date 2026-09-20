import { useEffect, useState } from "react";
import { api, type VocabCard } from "../lib/api";
import { Badge, Button, Card, EmptyState, Input, Skeleton, SparkleButton } from "../ui";

/** Pick words out of the text yourself.
 *
 *  Harvesting decides what is worth learning for you. This is the escape hatch
 *  for when it is wrong: you are reading, you hit a word you do not know, and
 *  you want it regardless of what the extractor judged.
 *
 *  Only pages you have reached appear — the same gate as everywhere else. */
export function WordPicker({ resourceId }: { resourceId: string }) {
  const [chunks, setChunks] = useState<
    { id: string; chunk_index: number; text: string; page_start: number }[]
  >([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<{ word: string; sentence: string } | null>(null);
  const [translation, setTranslation] = useState("");
  const [saving, setSaving] = useState(false);
  const [translating, setTranslating] = useState(false);
  const [aiNote, setAiNote] = useState<string | null>(null);
  const [root, setRoot] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [added, setAdded] = useState<VocabCard[]>([]);

  useEffect(() => {
    api
      .resourceChunks(resourceId)
      .then(setChunks)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [resourceId]);

  async function askAi() {
    if (!selected) return;
    setTranslating(true);
    setAiNote(null);
    try {
      const r = await api.translateWord(selected.word, selected.sentence);
      if (r.translatable) {
        setTranslation(r.translation);
        setRoot(r.root);
        setAiNote(r.note);
      } else {
        setAiNote(r.note ?? "That does not look like a whole word.");
      }
    } catch (e) {
      setAiNote(e instanceof Error ? e.message : String(e));
    } finally {
      setTranslating(false);
    }
  }

  async function save() {
    if (!selected || !translation.trim()) return;
    setSaving(true);
    setNote(null);
    try {
      const card = await api.addVocabManual({
        arabic: selected.word,
        translation: translation.trim(),
        resource_id: resourceId,
        context_sentence: selected.sentence.slice(0, 900),
        root: root ?? undefined,
      });
      setAdded([card, ...added]);
      setSelected(null);
      setTranslation("");
      setRoot(null);
      setAiNote(null);
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-24 rounded-[var(--radius-card)]" />
        <Skeleton className="h-24 rounded-[var(--radius-card)]" />
      </div>
    );
  }

  if (chunks.length === 0) {
    return (
      <EmptyState
        title="No readable text yet"
        body="This resource has not finished processing, or your reading position is at the very beginning."
      />
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-[var(--text-muted)]">
        Tap any word you do not know. Only pages you have reached are shown.
      </p>

      {selected && (
        <Card className="sticky top-2 z-10 space-y-3 border-[var(--accent)] p-4">
          <div className="flex items-center justify-between gap-3">
            <p className="arabic text-2xl" dir="rtl" lang="ar">{selected.word}</p>
            <Button variant="ghost" size="sm" onClick={() => setSelected(null)}>
              Cancel
            </Button>
          </div>
          {/* The sparkle sits inside the field: the AI is filling in THIS box,
              and a separate button beside it would read as a different action. */}
          <div className="relative">
            <Input
              autoFocus
              value={translation}
              onChange={(e) => setTranslation(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && save()}
              placeholder="What does it mean?"
              className="pr-10"
            />
            <SparkleButton
              onClick={askAi}
              loading={translating}
              title="Let AI translate it"
            />
          </div>
          {aiNote && (
            <p className="text-xs text-[var(--text-muted)]">{aiNote}</p>
          )}
          <Button onClick={save} loading={saving} disabled={!translation.trim()}>
            Add to vocabulary
          </Button>
          {note && <p className="text-sm text-[var(--bad-text)]">{note}</p>}
        </Card>
      )}

      {added.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {added.map((c) => (
            <Badge key={c.id} tone="ok">
              <span className="arabic bidi-isolate" dir="rtl" lang="ar">{c.arabic}</span>
            </Badge>
          ))}
        </div>
      )}

      <div className="space-y-3">
        {chunks.map((chunk) => (
          <Card key={chunk.id} className="p-5">
            <p className="mb-2 text-xs text-[var(--text-subtle)]">page {chunk.page_start}</p>
            <p className="arabic text-xl leading-loose" dir="rtl" lang="ar">
              {/* Each word is its own button. Splitting on whitespace keeps
                  the run intact for the bidi algorithm — reordering words here
                  would render the passage wrong. */}
              {chunk.text.split(/(\s+)/).map((token, i) =>
                token.trim() ? (
                  <button
                    key={i}
                    onClick={() =>
                      {
                        setSelected({
                          word: token.replace(/[.,،؛؟!:"()]/g, ""),
                          sentence: chunk.text,
                        });
                        setTranslation("");
                        setRoot(null);
                        setAiNote(null);
                      }
                    }
                    className="rounded px-0.5 transition-colors hover:bg-[var(--accent-soft)]
                               hover:text-[var(--accent-text)]"
                  >
                    {token}
                  </button>
                ) : (
                  token
                ),
              )}
            </p>
          </Card>
        ))}
      </div>
    </div>
  );
}
