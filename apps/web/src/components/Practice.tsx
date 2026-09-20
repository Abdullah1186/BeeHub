import { useEffect, useState } from "react";
import { ApiError, api, type Grade, type Question } from "../lib/api";
import { Badge, Button, Card, ScoreRing, Skeleton, Spinner } from "../ui";
import { humanise } from "./Home";

const VERDICT: Record<string, { label: string; tone: "ok" | "warn" | "neutral" | "bad" }> = {
  conveyed: { label: "Got it", tone: "ok" },
  partially_conveyed: { label: "Partly", tone: "warn" },
  absent: { label: "Missing", tone: "neutral" },
  contradicted: { label: "Contradicted", tone: "bad" },
};

export function Practice({
  resourceId,
  onBack,
  hideBack,
}: {
  resourceId: string;
  onBack: () => void;
  hideBack?: boolean;
}) {
  const [question, setQuestion] = useState<Question | null>(null);
  const [answer, setAnswer] = useState("");
  const [grade, setGrade] = useState<Grade | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<{ message: string; expected: boolean } | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    setGrade(null);
    setAnswer("");
    try {
      setQuestion(await api.nextQuestion(resourceId));
    } catch (e) {
      // 409 means the position gate has nothing to offer, or no groundable
      // question could be made. Expected behaviour, not a fault.
      const expected = e instanceof ApiError && e.isNoContent;
      setError({ message: e instanceof Error ? e.message : String(e), expected });
      setQuestion(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [resourceId]);

  async function submit() {
    if (!question || !answer.trim()) return;
    setSubmitting(true);
    try {
      setGrade(await api.submitAnswer(question.item_id, answer));
    } catch (e) {
      setError({ message: e instanceof Error ? e.message : String(e), expected: false });
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <div className="space-y-5">
        <Skeleton className="h-4 w-20" />
        <Card className="p-6">
          <Skeleton className="h-7 w-3/4" />
          <Skeleton className="mt-3 h-4 w-1/2" />
        </Card>
        <div className="flex items-center gap-2 text-sm text-[var(--text-muted)]">
          <Spinner /> Writing a question from what you have read…
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-4 fade-up">
        <Card
          className={`p-5 ${
            error.expected ? "" : "border-[var(--bad-text)]/30 bg-[var(--bad-bg)]"
          }`}
        >
          <p className={`text-sm ${error.expected ? "" : "text-[var(--bad-text)]"}`}>
            {error.message}
          </p>
        </Card>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={load}>Try again</Button>
          <Button variant="ghost" onClick={onBack}>Back</Button>
        </div>
      </div>
    );
  }

  if (!question) return null;

  return (
    <div className="space-y-6 fade-up">
      <div className="flex items-center justify-between">
        {!hideBack && (
          <Button variant="ghost" size="sm" onClick={onBack}>← Back</Button>
        )}
        <Badge tone="accent">{question.difficulty_cefr}</Badge>
      </div>

      <Card className="p-6">
        <p className="arabic text-2xl" dir="rtl" lang="ar">
          {question.question_arabic}
        </p>
        {question.question_english && (
          <p className="mt-4 border-t border-[var(--border-soft)] pt-4 text-sm text-[var(--text-muted)]">
            {question.question_english}
          </p>
        )}
      </Card>

      {!grade ? (
        <>
          <textarea
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            rows={4}
            dir="rtl"
            lang="ar"
            placeholder="اكتب إجابتك هنا…"
            className="arabic-input w-full rounded-[var(--radius-card)] border
                       border-[var(--border)] bg-[var(--surface)] p-5 text-lg
                       text-[var(--text)] placeholder:text-[var(--text-subtle)]
                       focus:border-[var(--accent)] focus:outline-none
                       focus:ring-2 focus:ring-[var(--accent)]/20"
          />
          <Button size="lg" onClick={submit} loading={submitting} disabled={!answer.trim()}>
            {submitting ? "Grading…" : "Submit answer"}
          </Button>
        </>
      ) : (
        <Feedback grade={grade} question={question} answer={answer} onNext={load} />
      )}
    </div>
  );
}

function Feedback({
  grade,
  question,
  answer,
  onNext,
}: {
  grade: Grade;
  question: Question;
  answer: string;
  onNext: () => void;
}) {
  if (!grade.gradable) {
    return (
      <div className="space-y-4 fade-up">
        <Card className="p-5">
          <p className="text-sm">{grade.ungradable_reason ?? "This answer could not be graded."}</p>
        </Card>
        <Button onClick={onNext}>Next question</Button>
      </div>
    );
  }

  return (
    <div className="space-y-6 fade-up">
      <Card className="p-5">
        <p className="arabic bidi-isolate text-lg" dir="rtl" lang="ar">{answer}</p>
      </Card>

      {/* Understanding and accuracy are shown apart, because a correct answer
          in imperfect Arabic should visibly score well on one and less on the
          other. Averaging them would hide exactly what the learner needs. */}
      <Card className="flex items-center justify-around p-6">
        <ScoreRing value={grade.content_score} label="Understanding" />
        <ScoreRing value={grade.language_score} label="Accuracy" />
        <ScoreRing value={grade.final_score} label="Overall" size={96} />
      </Card>

      <section>
        <h4 className="text-xs font-medium uppercase tracking-wide text-[var(--text-subtle)]">
          What was expected
        </h4>
        <Card className="mt-2 divide-y divide-[var(--border-soft)]">
          {question.key_points.map((kp) => {
            const verdict = grade.key_point_verdicts.find((v) => v.id === kp.id);
            const style = VERDICT[verdict?.status ?? "absent"];
            return (
              <div key={kp.id} className="flex items-start gap-3 p-4">
                <Badge tone={style.tone}>{style.label}</Badge>
                <div className="min-w-0">
                  <p className="text-sm">{kp.text}</p>
                  {verdict?.why && (
                    <p className="mt-0.5 text-xs text-[var(--text-muted)]">{verdict.why}</p>
                  )}
                </div>
              </div>
            );
          })}
        </Card>
      </section>

      {grade.errors.length > 0 && (
        <section>
          <h4 className="text-xs font-medium uppercase tracking-wide text-[var(--text-subtle)]">
            Language notes
          </h4>
          <div className="mt-2 space-y-2">
            {grade.errors.map((tag, i) => (
              <Card key={i} className="p-4">
                <div className="flex items-start justify-between gap-3">
                  <p className="arabic bidi-isolate text-lg" dir="rtl" lang="ar">
                    <span className="text-[var(--bad-text)] line-through opacity-70">
                      {tag.span}
                    </span>
                    {tag.correction && (
                      <span className="mr-3 text-[var(--ok-text)]">{tag.correction}</span>
                    )}
                  </p>
                  <Badge
                    tone={
                      tag.severity === "blocking" ? "bad"
                        : tag.severity === "moderate" ? "warn" : "neutral"
                    }
                  >
                    {tag.severity}
                  </Badge>
                </div>
                <p className="mt-2 text-sm text-[var(--text-muted)]">{tag.explanation}</p>
                <p className="mt-1 text-xs text-[var(--text-subtle)]">
                  {humanise(tag.category)} · {humanise(tag.subcategory)}
                </p>
              </Card>
            ))}
          </div>
        </section>
      )}

      {grade.feedback && (
        <Card className="bg-[var(--accent-soft)] p-5">
          <p className="text-sm text-[var(--accent-text)]">{grade.feedback}</p>
        </Card>
      )}

      <Button size="lg" onClick={onNext}>Next question</Button>
    </div>
  );
}
