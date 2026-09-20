import { useEffect, useState } from "react";
import { api, type VocabCard } from "../lib/api";
import { Badge, Button, Card, EmptyState, Skeleton, Spinner } from "../ui";

/** Spec §2.3 — Quizlet-style flashcards, harvested from the learner's own
 *  material rather than a generic word list. */
export function Vocab({
  resourceId,
  onBack,
  hideBack,
}: {
  resourceId: string;
  onBack: () => void;
  hideBack?: boolean;
}) {
  const [cards, setCards] = useState<VocabCard[]>([]);
  const [index, setIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [loading, setLoading] = useState(true);
  const [harvesting, setHarvesting] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function load() {
    try {
      setCards(await api.vocabDeck(resourceId));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [resourceId]);

  async function harvest() {
    setHarvesting(true);
    setNote(null);
    try {
      const result = await api.harvestVocab(resourceId);
      await load();
      // Three different outcomes hide behind "added: 0", and they need
      // different actions from the learner. Saying "nothing worth learning"
      // for all of them is wrong — and actively misleading when the words
      // WERE found and then thrown away as damaged.
      setNote(
        result.added > 0
          ? `Added ${result.added} new ${result.added === 1 ? "word" : "words"}.`
          : result.rejected_damaged > 0
            ? `Found ${result.rejected_damaged} ${
                result.rejected_damaged === 1 ? "word" : "words"
              }, but they came out of the PDF split mid-word, so they would teach the wrong spelling. This usually means the file itself extracted poorly.`
            : result.skipped_duplicates > 0
              ? "Nothing new here — you already have these."
              // Deliberately vague about the cause, because the app cannot tell
            // them apart: the model may have found a heading, or judged the
            // words too basic for the CEFR level it was given — and that level
            // is a default until the estimation job runs. Claiming "words you
            // already know" asserts knowledge the system does not have.
            : "Nothing new came back from that passage. Try again — a different part of the book may have more.",
      );
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e));
    } finally {
      setHarvesting(false);
    }
  }

  if (loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-4 w-20" />
        <Skeleton className="h-64 rounded-[var(--radius-card)]" />
      </div>
    );
  }

  const card = cards[index];

  return (
    <div className="space-y-6 fade-up">
      <div className="flex items-center justify-between">
        {!hideBack && (
          <Button variant="ghost" size="sm" onClick={onBack}>← Back</Button>
        )}
        {cards.length > 0 && (
          <span className="text-sm text-[var(--text-muted)]">
            {index + 1} of {cards.length}
          </span>
        )}
      </div>

      {cards.length === 0 ? (
        <EmptyState
          title="No words yet"
          body="Harvest vocabulary from a passage you have read. Words come from your own book, not a generic list."
          action={
            <Button onClick={harvest} loading={harvesting}>
              {harvesting ? "Reading a passage…" : "Harvest words"}
            </Button>
          }
        />
      ) : (
        <>
          {/* The card. Tap anywhere to flip — the whole surface is the control,
              which is what people expect from a flashcard. */}
          <button
            onClick={() => setFlipped(!flipped)}
            className="w-full text-left"
            aria-label={flipped ? "Show the Arabic" : "Show the meaning"}
          >
            <Card className="flex min-h-64 flex-col justify-center p-8" interactive>
              {!flipped ? (
                <>
                  <p className="arabic text-center text-5xl" dir="rtl" lang="ar">
                    {card.arabic}
                  </p>
                  <p className="mt-6 text-center text-xs text-[var(--text-subtle)]">
                    Tap to reveal
                  </p>
                </>
              ) : (
                <div className="space-y-5 fade-up">
                  <p className="text-center text-2xl font-medium">{card.translation}</p>

                  <div className="flex justify-center gap-2">
                    {card.pos && <Badge>{card.pos}</Badge>}
                    {card.root && (
                      <Badge tone="accent">
                        <span className="arabic bidi-isolate" dir="rtl" lang="ar">
                          {card.root}
                        </span>
                      </Badge>
                    )}
                  </div>

                  {card.context_sentence && (
                    <div className="border-t border-[var(--border-soft)] pt-4">
                      <p className="text-xs uppercase tracking-wide text-[var(--text-subtle)]">
                        In context
                      </p>
                      <p className="arabic mt-2 text-lg" dir="rtl" lang="ar">
                        {card.context_sentence}
                      </p>
                    </div>
                  )}
                </div>
              )}
            </Card>
          </button>

          <div className="flex items-center gap-3">
            <Button
              variant="secondary"
              disabled={index === 0}
              onClick={() => {
                setIndex(index - 1);
                setFlipped(false);
              }}
            >
              Previous
            </Button>
            <Button
              variant="secondary"
              disabled={index >= cards.length - 1}
              onClick={() => {
                setIndex(index + 1);
                setFlipped(false);
              }}
            >
              Next
            </Button>
            <Button
              variant="ghost"
              className="ml-auto"
              onClick={harvest}
              loading={harvesting}
            >
              {harvesting ? "Reading…" : "Harvest more"}
            </Button>
          </div>
        </>
      )}

      {note && (
        <Card className="flex items-center gap-2 bg-[var(--accent-soft)] p-4">
          {harvesting && <Spinner />}
          <p className="text-sm text-[var(--accent-text)]">{note}</p>
        </Card>
      )}
    </div>
  );
}
