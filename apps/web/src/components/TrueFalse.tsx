import { useEffect, useState } from "react";
import { ApiError, api } from "../lib/api";
import { Badge, Button, Card, Skeleton, Spinner } from "../ui";

type Statement = { id: string; statement_arabic: string; statement_english: string };
type Verdict = {
  id: string;
  statement_arabic: string;
  correct: boolean;
  correct_answer: boolean;
  explanation: string;
  source_quote: string;
};

/** Spec §2.3 — true/false.
 *
 *  A set at a time rather than one statement: a single true/false item is a
 *  coin flip, and a score out of one tells the learner nothing. */
export function TrueFalse({ resourceId }: { resourceId: string }) {
  const [item, setItem] = useState<{
    item_id: string;
    difficulty_cefr: string;
    statements: Statement[];
  } | null>(null);
  const [answers, setAnswers] = useState<Record<string, boolean>>({});
  const [result, setResult] = useState<{
    score: number;
    correct_count: number;
    total: number;
    verdicts: Verdict[];
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<{ message: string; expected: boolean } | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    setResult(null);
    setAnswers({});
    try {
      setItem(await api.trueFalse(resourceId));
    } catch (e) {
      const expected = e instanceof ApiError && e.isNoContent;
      setError({ message: e instanceof Error ? e.message : String(e), expected });
      setItem(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [resourceId]);

  async function submit() {
    if (!item) return;
    setSubmitting(true);
    try {
      setResult(await api.answerTrueFalse(item.item_id, answers));
    } catch (e) {
      setError({ message: e instanceof Error ? e.message : String(e), expected: false });
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <div className="space-y-3">
        {[0, 1, 2].map((i) => <Skeleton key={i} className="h-20 rounded-[var(--radius-card)]" />)}
        <div className="flex items-center gap-2 text-sm text-[var(--text-muted)]">
          <Spinner /> Writing statements from what you have read…
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-4 fade-up">
        <Card className={`p-5 ${error.expected ? "" : "border-[var(--bad-text)]/30 bg-[var(--bad-bg)]"}`}>
          <p className={`text-sm ${error.expected ? "" : "text-[var(--bad-text)]"}`}>
            {error.message}
          </p>
        </Card>
        <Button variant="secondary" onClick={load}>Try again</Button>
      </div>
    );
  }

  if (!item) return null;

  const allAnswered = item.statements.every((s) => s.id in answers);

  return (
    <div className="space-y-5 fade-up">
      <div className="flex items-center justify-between">
        <p className="text-sm text-[var(--text-muted)]">
          True or false, according to the passage?
        </p>
        <Badge tone="accent">Level {item.difficulty_cefr}</Badge>
      </div>

      <div className="space-y-3">
        {item.statements.map((s) => {
          const verdict = result?.verdicts.find((v) => v.id === s.id);
          const given = answers[s.id];

          return (
            <Card
              key={s.id}
              className={`p-5 ${
                verdict
                  ? verdict.correct
                    ? "border-[var(--ok-text)]/40"
                    : "border-[var(--bad-text)]/40"
                  : ""
              }`}
            >
              <p className="arabic text-xl" dir="rtl" lang="ar">{s.statement_arabic}</p>
              <p className="mt-1 text-sm text-[var(--text-muted)]">{s.statement_english}</p>

              {!result ? (
                <div className="mt-4 grid grid-cols-2 gap-2">
                  <Button
                    variant={given === true ? "primary" : "secondary"}
                    onClick={() => setAnswers({ ...answers, [s.id]: true })}
                  >
                    True
                  </Button>
                  <Button
                    variant={given === false ? "primary" : "secondary"}
                    onClick={() => setAnswers({ ...answers, [s.id]: false })}
                  >
                    False
                  </Button>
                </div>
              ) : (
                verdict && (
                  <div className="mt-4 space-y-2 border-t border-[var(--border-soft)] pt-3">
                    <div className="flex items-center gap-2">
                      <Badge tone={verdict.correct ? "ok" : "bad"}>
                        {verdict.correct ? "Correct" : "Wrong"}
                      </Badge>
                      <span className="text-sm text-[var(--text-muted)]">
                        It is {verdict.correct_answer ? "true" : "false"}
                      </span>
                    </div>
                    <p className="text-sm">{verdict.explanation}</p>
                    {/* The evidence. Showing the quote is what makes the mark
                        checkable rather than something to take on trust. */}
                    <p className="arabic bidi-isolate rounded bg-[var(--surface-alt)] px-3 py-2
                                  text-base" dir="rtl" lang="ar">
                      {verdict.source_quote}
                    </p>
                  </div>
                )
              )}
            </Card>
          );
        })}
      </div>

      {!result ? (
        <Button size="lg" onClick={submit} loading={submitting} disabled={!allAnswered}>
          {allAnswered ? "Check answers" : `Answer all ${item.statements.length}`}
        </Button>
      ) : (
        <div className="space-y-4">
          <Card className="flex items-center justify-between p-5">
            <span className="text-sm text-[var(--text-muted)]">Score</span>
            <span className="text-2xl font-semibold text-[var(--accent-text)]">
              {result.correct_count} / {result.total}
            </span>
          </Card>
          <Button size="lg" onClick={load}>Next set</Button>
        </div>
      )}
    </div>
  );
}
