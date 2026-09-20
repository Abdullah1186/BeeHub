# BeeHub — how this repo works

A guide to the codebase as it stands: what each piece does, why it is shaped
that way, and which decisions departed from `BeehubSpec.md`.

For *what the product is*, read the spec. This document is about the build.

---

## 1. The one-paragraph version

You upload Arabic learning material. It is extracted, checked for extraction
damage, split into page-bounded chunks, and embedded. When you practise, the app
picks a passage **you have actually read**, asks Claude to write a question
grounded in that passage, and grades your answer against key points that were
extracted at generation time. Every mark is computed in Python from the model's
discrete verdicts, never taken as a number from the model.

---

## 2. The core loop

```
┌──────────┐   upload    ┌──────────────┐   queue    ┌──────────┐
│  You     │────────────▶│  FastAPI     │───────────▶│  worker  │
└──────────┘             │  /resources  │            └────┬─────┘
                         └──────────────┘                 │
                                                          ▼
                    ┌─────────────────────────────────────────────┐
                    │  extract → normalise → QUALITY GATE → chunk │
                    └──────────────────┬──────────────────────────┘
                                       │ passed?
                         ┌─────────────┴──────────────┐
                        no                           yes
                         │                            │
                         ▼                            ▼
                 ingest_status =              resource_chunks
                 'failed', 0 chunks           (+ embeddings)
                 NOTHING generated                    │
                                                      ▼
                                          ┌───────────────────────┐
                                          │  POSITION GATE (§5.2) │
                                          │  page_end <= position │
                                          └───────────┬───────────┘
                                                      ▼
                                       select_chunk_window (contiguous)
                                                      │
                                                      ▼
                                       ┌──────────────────────────┐
                                       │ Claude: generate question│
                                       │ + key_points + quotes    │
                                       └──────────┬───────────────┘
                                                  │
                                    grounding check: every quote
                                    must be verbatim in the passage
                                                  │
                                                  ▼
                                          generated_items (cached)
                                                  │
                          you answer ─────────────┤
                                                  ▼
                                       ┌──────────────────────────┐
                                       │ Claude: grade + tag      │
                                       │ verdicts, not a score    │
                                       └──────────┬───────────────┘
                                                  ▼
                                       compute_score()  ← Python
                                                  │
                                    ┌─────────────┼─────────────┐
                                    ▼             ▼             ▼
                               attempts      error_tags    model_calls
                             (content +      (taxonomy)     (cost log)
                              language)
```

Two properties this shape is built to guarantee:

1. **A question can only come from material you have reached.** Enforced in SQL,
   in one function, re-checked at serve time.
2. **A question can only come from text that actually exists.** Every key point
   carries a verbatim quote, checked as a substring before the item is stored.

---

## 3. Repo layout

```
BeeHub/
├── apps/api/               FastAPI backend — a self-contained deployable
│   ├── app/                Python package
│   │   ├── ingest/         PDF → text → quality gate → chunks
│   │   ├── retrieval/      gated chunk selection
│   │   ├── embeddings/     Voyage provider (+ deterministic fake)
│   │   ├── ai/             Claude client, routing, pricing
│   │   ├── schemas/        Pydantic models = the model's output contract
│   │   ├── grading/        score arithmetic (pure functions)
│   │   ├── skills/         the LOADER for skill files (not the files)
│   │   ├── api/            HTTP endpoints
│   │   └── worker.py       ingestion job runner
│   ├── skills/             ALL prompt text lives here (§5.1)
│   │   ├── _shared/        conventions, CEFR, taxonomy, output contract
│   │   ├── generate-comprehension-questions.md
│   │   └── grade-short-answer.md
│   ├── config/models.yaml  model routing, no prompt text
│   └── tests/              142 tests, no network, no API key
│
├── evals/                  measurement harness
│   ├── cases/              62 golden cases with known-correct outcomes
│   ├── cassettes/          recorded responses → replay is free
│   ├── baselines/          per-case pass record → regression detection
│   └── runner.py
│
├── supabase/
│   ├── migrations/         schema, RLS, gate functions
│   ├── tests/gate_test.sql the §5.2 guarantee, attacked
│   └── local/              auth stub for offline testing
│
└── .github/workflows/      free CI + gated paid CI

> **Why skills/ sits inside apps/api rather than at the repo root** (departing
> from the spec's layout): the backend is the only thing that needs them at
> runtime, so keeping them inside makes it a self-contained deployable. Path
> resolution is then a fixed `parents[1]`, with no discovery logic, no env vars,
> and no build-context requirements. An earlier root-level layout resolved
> paths by climbing `parents[3]`, which worked locally and would have broken on
> any deployment whose build context was `apps/api/` — booting green and failing
> on the first practice request.
```

---

## 4. The parts that carry weight

### 4.1 The quality gate — `app/ingest/quality.py`

The highest-risk failure in the system is a PDF that extracts as garbage, gets
chunked, and produces confident questions about text that is not what the book
says. You answer correctly from the page and are marked wrong.

So extraction is **gated**, not trusted:

```
        extract
           │
           ▼
   NFKC normalise ──── repairs presentation forms (U+FExx → base letters)
           │
           ▼
   ┌───────────────────────────────────────────┐
   │ arabic ratio        < 0.15  → scan/empty  │
   │ presentation forms  > 0.02  → bad encoding│
   │ mean word length    > 25    → no spaces   │
   │ reversed order      > 0.40  → visual order│
   │ mirrored text       > 0.50  → char mirror │
   │ fragmentation       > 0.20  → split words │
   │ orphan diacritics   > 0.30  → detached    │
   └───────────────┬───────────────────────────┘
                   ▼
        ok  │  degraded  │  failed
             practice     NO chunks
             + warning    NO generation
```

Two of these detectors exist because real PDFs failed in ways the others missed:

- **Mirrored text.** A generated Arabic PDF extracted fully reversed — word order
  *and* letters within each word. The word-position heuristic could not see it,
  because reversing a line also reverses the particles it looks for (`في` → `يف`).
  Detected morphologically: Arabic words overwhelmingly start with `ال` and end
  with `ة`/`ى`, and reversal inverts that distribution. Scores 0.93 on mirrored
  text, 0.0 on correct Arabic.

- **Intra-word fragmentation.** A real poetry PDF passed every check while 11% of
  its tokens were single letters — `فَقُلْتُ` had become `فَق لْت`. The glyphs and
  their order were fine; only token counting reveals it.

> **Never "fix" apparently-backwards Arabic by reversing it.** Extractors return
> logical order; reversing again produces double-reversed text that looks
> plausible and is wrong. Detect and quarantine instead.

### 4.2 The position gate — `supabase/migrations/0003_functions.sql`

Spec §5.2: never generate from material past where the learner has reached.

```sql
resolve_max_page(resource, user)
  ├─ not your resource      → -1   (expose nothing)
  ├─ position_value IS NULL → MAX  (untracked, all fair game)
  └─ position_value = N     → N
```

Everything funnels through that one function. It is deliberately **not**
reimplemented in Python: two implementations drift, and one of them eventually
leaks.

It is re-applied at **serve** time as well as generation time, because you can
move your position *backwards* — an item generated when you were further ahead
must stop being served.

`supabase/tests/gate_test.sql` attacks it: 1000 random selections, cross-user
access, position rollback, window contiguity, and the grounding constraint.

> **A bug this caught:** `array_length('{}', 1)` returns NULL, not 0 — and a
> Postgres CHECK that evaluates to NULL **passes**. The grounding constraint was
> silently inert and accepted ungrounded items. `cardinality()` is the correct
> form.

### 4.3 Retrieval is contiguous, not top-k — `app/retrieval/selector.py`

Question generation does **not** use vector search.

There is no query when the task is "ask me about what I just read". Top-k
similarity returns semantically related but narratively *disconnected* fragments
— exactly the input that produces incoherent comprehension questions.

Instead: a contiguous run of chunks, weighted toward recent pages.

> **A bug this caught:** the first recency weighting (`chunk_index * random()`)
> put 99.3% of draws in the last ten pages; pages 1–20 were never selected in
> 2000 draws. Review of earlier material was impossible. Now a mixture — 60%
> from the recent third, else uniform — giving ~20% early / ~80% recent.

Embeddings are used for vocab context and Phase 2 thematic search. They live in
exactly one table: `resource_chunks.embedding`, `vector(1024)`.

### 4.4 Grading: verdicts from the model, numbers from Python

```
generation time ──▶ key_points: [{id, text, source_quote}]
                         │        (each quote verbatim in the passage)
                         ▼
grading time  ──▶ per key point: conveyed │ partially │ absent │ contradicted
                  plus error tags from a CLOSED taxonomy
                         │
                         ▼
compute_score()  ──▶ content_score   (→ reading CEFR)
                     language_score  (→ writing CEFR)
                     final_score
```

Three decisions encoded here:

**Key points come from generation, not grading.** The grader only decides whether
each was conveyed — far more repeatable than "grade this answer", and it costs
nothing extra.

**`contradicted` ≠ `absent`.** Saying the opposite is a comprehension failure;
saying nothing is an omission. A four-value enum catches near-misses that a
boolean would miss entirely.

**Minor errors cost nothing.** A learner who conveys the meaning with a hamza slip
has comprehended. The error is still tagged and still feeds metrics and the
review queue — it just does not reduce the mark. This is the fair-to-paraphrase
guarantee, enforced in code rather than requested in a prompt.

The model's own holistic score is recorded but **never used**. When it disagrees
with the computed score by more than 0.3, the attempt is flagged — and those
flags become free eval cases.

### 4.5 Skills — `skills/*.md`, loaded by `app/skills/loader.py`

All prompt text lives in markdown. No prompt strings in Python (§5.1).

```
error-taxonomy.yaml ─┬─▶ taxonomy.py  → closed StrEnums (Pydantic)
                     └─▶ loader.py    → rendered into the prompt
```

One file feeds both, so the enum and the prompt cannot drift. A test asserts
every enum member appears in the rendered prompt — the model cannot emit what it
was never shown.

**`prompt_hash` is sha256 of the fully rendered prompt**, not of the single file.
Editing `error-taxonomy.yaml` changes the hash of every skill that includes it.
Without that, evals would attribute a result to the wrong prompt version and you
would tune against a lie.

### 4.6 Routing — `config/models.yaml` + `app/ai/router.py`

Routes to a **pool**, not a bare model. A pool is one prompt-cache namespace;
caches are model-scoped, so each extra model fragments the caching that §5.4
calls the biggest lever on spend.

| Pool | Model | Used for |
|---|---|---|
| `judgment` | `claude-sonnet-5` | generation, grading, tagging, CEFR |
| `mechanical` | `claude-haiku-4-5` | bulk vocab extraction (batched) |

**Opus is excluded for cost**, overriding §5.3. Sonnet is ~60% cheaper per graded
answer (~$10 vs $25 per 1000). `router.py` raises if any pool resolves to Opus,
so the decision cannot be undone by an unreviewed config edit.

The risk this accepts: §5.3 put Opus on error tagging because Arabic morphology
is hard and bad tags poison the metrics. The tagging eval's **false-positive rate
on correct sentences** is the tripwire.

**Measured, and the decision holds.** Tagging scores 34/40 (85%) with a
**0% false-positive rate** — Sonnet did not invent a single error across 8
correct sentences, including fully vocalised text, a three-term iḍāfa chain,
correct dual agreement, and the passive. That was the failure mode that would
have quietly corrupted the metrics tab, review queue, and writing CEFR.

Of the 6 failures, 3 are defensible alternative categorisations rather than
misses — `فاطمة ذهب` tagged `agreement/gender` instead of
`morphology/verb_conjugation` is an honest reading of the same error. Only 3 are
true misses (conditional mood, one register slip, one hamza seat).

---

## 5. The evals harness

The problem: you have a grader that assigns marks. How do you know it is good?

If you make it stricter, you might fix near-misses and simultaneously start
punishing correct paraphrases — and never notice, because you would only see it
as unexplained CEFR drift months later.

### Four tiers

| Tier | When | Cost | What it proves |
|---|---|---|---|
| 0 | every commit | $0 | logic, schemas, arithmetic, the SQL gate |
| 1 | every PR | $0 | replays cassettes; nothing regressed |
| 2 | `skills/` changed | ~$0.60 | the model, today, behaves this way |
| 3 | manual/scheduled | ~$0.60 | model drift, with repetitions |

### The cassette mechanism

```
cassette key = sha256(prompt_hash + case_id)

prompt unchanged ──▶ replay from disk ──▶ $0
prompt  changed  ──▶ key misses       ──▶ CANNOT REPLAY, CI fails
```

You **cannot** change a prompt and quietly pass on stale recordings. Either you
re-measure, or the build stays red.

### The cases

- `short_answer.yaml` — 22 cases. `paraphrase/*` must score **high**;
  `near_miss/*` must score **low**. Engineered to be unambiguous, so no LLM judge
  is needed (a judge would put a second unversioned prompt in the measurement
  loop).
- `error_tagging.yaml` — 40 cases, 32 with known errors plus **8 clean sentences**
  that measure false positives. The clean ones matter more: a tagger that invents
  errors in correct Arabic makes the metrics tab lie, and recall alone will never
  reveal it.

### Per-case regression detection

Aggregate scores hide drift. A real example from this repo:

| | before | after |
|---|---|---|
| `near_miss/wrong_place` | fail | **pass** |
| `paraphrase/concise` | pass | **fail** |
| pass rate | 95% | **95%** |

The average is identical; a fix and a break cancelled out. The runner compares
**every case individually** and fails on any pass → fail flip, naming it.

> On investigation the grader was right and the *test* was wrong — the answer
> genuinely omitted detail. The expectation was corrected, not the prompt. That
> is a legitimate resolution, but only when it follows from reading the
> reasoning, not as a reflex.

### What replay does and does not prove

| Run | Proves |
|---|---|
| live | the grader, today, behaves this way |
| replay | your code turns those verdicts into these scores; nothing regressed |

A green replay means *"nothing changed since the last real measurement."* It does
not mean the grader works. If Claude's behaviour shifts underneath us, cassettes
still replay green — which is what Tier 3 is for.

---

## 6. Where the spec was wrong

Verified against current docs and live APIs.

| Spec | Reality | Why it matters |
|---|---|---|
| Sonnet 5 = $3/$15 | **$2/$10** | cost model was wrong |
| `claude-haiku-4-5-20251001` | `claude-haiku-4-5` | dated IDs are wrong for current models |
| `vector(1536)` | **1024** (Voyage) | Anthropic has no embeddings API; 1536 presumed OpenAI |
| "JSON only, validate, retry" | `messages.parse(output_format=…)` | constrained decoding makes parse failure near-impossible |
| "cache every skill file" | min prefix is **model-dependent** | below it, caching silently does nothing while still charging the write premium |
| `budget_tokens` | removed on Sonnet 5 (400) | use `output_config.effort` |
| retrieval as a model-called tool | retrieve-then-generate | the gate must be deterministic; a tool loop also forfeits the Batch API |
| Opus for tagging/essays/CEFR | Sonnet everywhere | cost; risk tracked by the tagging eval |

---

## 7. Running it

```bash
make install     # venv + deps
make test        # 142 tests, no network, no API key
make db-test     # position gate against real Postgres (Docker)
make eval        # replay evals from cassettes — free
make check       # all of the above

make eval-live   # real API, re-records cassettes (~$0.60)
make api         # uvicorn on :8000
```

CI runs `test`, `db-test` and `eval` on every push — **with no API key in the
environment**, so it cannot spend money even through a bug. The live workflow
fires only when `skills/` or `config/models.yaml` changes, behind a GitHub
environment that can require approval.

---

## 8. Current state

**Working end to end:** ingestion with the quality gate, the position gate,
embeddings, grounded question generation, grading with error tagging, score
arithmetic, cost telemetry, and the evals harness.

**Measured:** short-answer 22/22. Prompt caching live — 7799 tokens written once,
read thereafter, dropping per-grade cost from $0.035 to ~$0.006.

**Not yet built:** frontend, vocab flashcards, review queue, metrics tab,
speaking, photo upload. Phases 2–4 of the spec.

**Known limitation:** `في القدس` extracts too fragmented to generate from — the
model correctly refuses with `answerable_from_source: false`. Heavily formatted
bilingual poetry PDFs may simply not be usable material; plain Arabic prose
should work far better.
