import { useEffect, useState } from "react";
import { ApiError, api, type Grade, type Question } from "../lib/api";

const SEVERITY: Record<string, string> = {
  minor: "border-stone-300 text-stone-600",
  moderate: "border-amber-400 text-amber-700",
  blocking: "border-red-400 text-red-700",
};

const VERDICT: Record<string, { label: string; className: string }> = {
  conveyed:           { label: "Got it",       className: "bg-green-50 text-green-700" },
  partially_conveyed: { label: "Partly",       className: "bg-amber-50 text-amber-700" },
  absent:             { label: "Missing",      className: "bg-stone-100 text-stone-600" },
  contradicted:       { label: "Contradicted", className: "bg-red-50 text-red-700" },
};

export function Practice({ resourceId, onBack }: { resourceId: string; onBack: () => void }) {
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
      // A 409 is the position gate or the grounding check doing their job —
      // present it as information, not as a failure.
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

  if (loading) return <p className="text-sm text-stone-500">Preparing a question…</p>;

  if (error) {
    return (
      <div className="space-y-4">
        <div
          className={`rounded-lg border p-4 text-sm ${
            error.expected
              ? "border-stone-200 bg-stone-50 text-stone-700"
              : "border-red-200 bg-red-50 text-red-700"
          }`}
        >
          {error.message}
        </div>
        <div className="flex gap-2">
          <button onClick={load} className="rounded-lg border border-stone-300 px-3 py-1.5 text-sm">
            Try again
          </button>
          <button onClick={onBack} className="rounded-lg border border-stone-300 px-3 py-1.5 text-sm">
            Back
          </button>
        </div>
      </div>
    );
  }

  if (!question) return null;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <button onClick={onBack} className="text-sm text-stone-500 hover:text-stone-800">
          ← Back
        </button>
        <span className="rounded-full bg-bee-50 px-2 py-0.5 text-xs text-bee-700">
          {question.difficulty_cefr}
        </span>
      </div>

      {/* The question. dir/lang are on the element itself so the browser's bidi
          algorithm sees the boundary of the Arabic run. */}
      <div className="rounded-lg border border-stone-200 bg-white p-6">
        <p className="arabic" dir="rtl" lang="ar">
          {question.question_arabic}
        </p>
        {question.question_english && (
          <p className="mt-3 border-t border-stone-100 pt-3 text-sm text-stone-500">
            {question.question_english}
          </p>
        )}
      </div>

      {!grade ? (
        <>
          <textarea
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            rows={4}
            dir="rtl"
            lang="ar"
            placeholder="اكتب إجابتك هنا…"
            className="arabic-input w-full rounded-lg border border-stone-300 p-4
                       focus:border-bee-500 focus:outline-none focus:ring-1 focus:ring-bee-500"
          />
          <button
            onClick={submit}
            disabled={submitting || !answer.trim()}
            className="rounded-lg bg-bee-600 px-4 py-2 text-sm font-medium text-white
                       hover:bg-bee-700 disabled:opacity-50"
          >
            {submitting ? "Grading…" : "Submit answer"}
          </button>
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
      <div className="space-y-4">
        <div className="rounded-lg border border-stone-200 bg-stone-50 p-4 text-sm">
          {grade.ungradable_reason ?? "This answer could not be graded."}
        </div>
        <button onClick={onNext} className="rounded-lg bg-bee-600 px-4 py-2 text-sm text-white">
          Next question
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="rounded-lg border border-stone-200 bg-white p-4">
        <p className="arabic bidi-isolate text-base" dir="rtl" lang="ar">
          {answer}
        </p>
      </div>

      {/* Two scores, shown separately. A right answer in imperfect Arabic
          should visibly score well on understanding and less on accuracy —
          that distinction is the point (§2.5). */}
      <div className="grid grid-cols-3 gap-3">
        <Score label="Understanding" value={grade.content_score} />
        <Score label="Accuracy" value={grade.language_score} />
        <Score label="Overall" value={grade.final_score} emphasis />
      </div>

      <div>
        <h4 className="text-xs font-medium uppercase tracking-wide text-stone-400">
          What was expected
        </h4>
        <ul className="mt-2 space-y-2">
          {question.key_points.map((kp) => {
            const verdict = grade.key_point_verdicts.find((v) => v.id === kp.id);
            const style = VERDICT[verdict?.status ?? "absent"];
            return (
              <li key={kp.id} className="flex items-start gap-3 text-sm">
                <span className={`mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-xs ${style.className}`}>
                  {style.label}
                </span>
                <div>
                  <p className="text-stone-700">{kp.text}</p>
                  {verdict?.why && <p className="text-xs text-stone-500">{verdict.why}</p>}
                </div>
              </li>
            );
          })}
        </ul>
      </div>

      {grade.errors.length > 0 && (
        <div>
          <h4 className="text-xs font-medium uppercase tracking-wide text-stone-400">
            Language notes
          </h4>
          <ul className="mt-2 space-y-2">
            {grade.errors.map((tag, i) => (
              <li
                key={i}
                className={`rounded border-l-2 bg-white py-2 pl-3 pr-2 text-sm ${
                  SEVERITY[tag.severity] ?? SEVERITY.minor
                }`}
              >
                <p className="arabic bidi-isolate text-base" dir="rtl" lang="ar">
                  <span className="line-through opacity-60">{tag.span}</span>
                  {tag.correction && <span className="mr-2">← {tag.correction}</span>}
                </p>
                <p className="mt-1 text-xs text-stone-600">{tag.explanation}</p>
                <p className="mt-0.5 text-[11px] text-stone-400">
                  {tag.category} · {tag.subcategory} · {tag.severity}
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}

      {grade.feedback && (
        <p className="rounded-lg bg-bee-50 p-4 text-sm text-stone-700">{grade.feedback}</p>
      )}

      <button
        onClick={onNext}
        className="rounded-lg bg-bee-600 px-4 py-2 text-sm font-medium text-white hover:bg-bee-700"
      >
        Next question
      </button>
    </div>
  );
}

function Score({ label, value, emphasis }: { label: string; value: number; emphasis?: boolean }) {
  const pct = Math.round(value * 100);
  return (
    <div className={`rounded-lg border p-3 ${emphasis ? "border-bee-200 bg-bee-50" : "border-stone-200 bg-white"}`}>
      <p className="text-xs text-stone-500">{label}</p>
      <p className={`mt-1 text-2xl ${emphasis ? "text-bee-700" : "text-stone-800"}`}>{pct}%</p>
    </div>
  );
}
